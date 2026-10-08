# -*- coding: utf-8 -*-
"""
Sewa Setu - Old Age Pension Portal
Government of Purvanchal, Department of Social Welfare

Developed by: Netlink Infosolutions Pvt Ltd (2023)
Maintenance contract ended 31/01/2026.
"""

import os
import io
import csv
import random
import hashlib
import configparser
import uuid
import secrets
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import requests
import psycopg2
from psycopg2 import pool
from flask import (Flask, request, session, redirect, url_for, render_template,
                   flash, send_file, abort, jsonify)
from fpdf import FPDF
from upload_validation import validate_uploaded_document
from application_validation import age_on_date, parse_dob, sanitize

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, "config", "app.ini"))

app = Flask(__name__)
SESSION_SECRET = os.environ.get("SEWA_SECRET_KEY")
if not SESSION_SECRET:
    raise RuntimeError("SEWA_SECRET_KEY must be configured outside the source tree")
app.secret_key = SESSION_SECRET
app.config["PERMANENT_SESSION_LIFETIME"] = 300

ADMIN_USERNAME = os.environ.get("SEWA_ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("SEWA_ADMIN_PASSWORD")
DB_PASSWORD = os.environ.get("SEWA_DB_PASSWORD")
if not ADMIN_USERNAME or not ADMIN_PASSWORD or not DB_PASSWORD:
    raise RuntimeError("SEWA_ADMIN_USERNAME, SEWA_ADMIN_PASSWORD, and "
                       "SEWA_DB_PASSWORD must be configured")

SMS_GATEWAY_URL = config.get("app", "sms_gateway_url")
OTP_VALIDITY_SECONDS = config.getint("app", "otp_validity_seconds")
UPLOAD_DIR = config.get("app", "upload_dir")
INDIA_TZ = ZoneInfo("Asia/Kolkata")
SCHEME_DEADLINE_DATE = datetime.strptime(
    config.get("pension", "scheme_deadline"), "%Y-%m-%d %H:%M"
).date()
# The configured date denotes the final day of applications. Close at the
# following midnight in India Standard Time.
SCHEME_DEADLINE = datetime.combine(
    SCHEME_DEADLINE_DATE + timedelta(days=1), time.min, tzinfo=INDIA_TZ
)
MIN_AGE = config.getint("pension", "min_age")
SLA_DAYS = config.getint("pension", "sla_days")

BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]
DB_POOL_MAX = config.getint("database", "pool_max", fallback=8)
_db_pool = None
_db_pool_pid = None

import logging
_logdir = "/var/log/sewasetu"
try:
    os.makedirs(_logdir, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_logdir, "sewasetu-app.log"))
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s in app: %(message)s"))
    app.logger.addHandler(_fh)
    app.logger.setLevel(logging.INFO)
except Exception:
    pass


def get_db():
    global _db_pool, _db_pool_pid
    pid = os.getpid()
    if _db_pool is None or _db_pool_pid != pid:
        _db_pool = pool.ThreadedConnectionPool(
            1, DB_POOL_MAX,
            host=config.get("database", "host"),
            port=config.get("database", "port"),
            dbname=config.get("database", "name"),
            user=config.get("database", "user"),
            password=DB_PASSWORD,
        )
        _db_pool_pid = pid
    return _db_pool.getconn()


def release_db(conn):
    if conn is None or _db_pool is None:
        return
    if conn.closed:
        _db_pool.putconn(conn, close=True)
        return
    conn.rollback()
    _db_pool.putconn(conn)


def hash_password(p):
    return hashlib.sha256(p.encode("utf-8")).hexdigest()


def india_now():
    return datetime.now(INDIA_TZ)


def database_now():
    return india_now().replace(tzinfo=None)


def send_sms(mobile, text):
    try:
        requests.post(SMS_GATEWAY_URL + "/api/send",
                      json={"to": mobile, "text": text}, timeout=5)
    except Exception as e:
        app.logger.error("sms gateway error: %s" % e)


def deadline_remaining():
    delta = SCHEME_DEADLINE - india_now()
    if delta.total_seconds() <= 0:
        return None
    return int(delta.total_seconds() // 3600)


def new_application_no():
    return "SSP" + india_now().strftime("%y") + str(random.randint(100000, 999999))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", hours_left=deadline_remaining())


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/__gateway/", defaults={"subpath": ""})
@app.route("/__gateway/<path:subpath>")
def gateway_proxy(subpath):
    # The SMS gateway contains OTPs and other sensitive messages. It is
    # intentionally internal-only and must never be republished here.
    abort(404)


# ---------------------------------------------------------------------------
# Application flow: mobile -> OTP -> form steps -> upload -> declaration
# ---------------------------------------------------------------------------

@app.route("/apply", methods=["GET", "POST"])
def apply():
    if deadline_remaining() is None:
        flash("The application window for this scheme has closed.")
        return redirect(url_for("index"))
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        captcha = request.form.get("captcha", "")
        if len(mobile) != 10 or not mobile.isdigit():
            flash("Something went wrong. Please try again.")
            return render_template("apply.html", captcha_q=make_captcha())
        code = str(random.randint(100000, 999999))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO otps (mobile, code, created_at) VALUES (%s, %s, %s)",
                    (mobile, code, database_now()))
        conn.commit()
        cur.close(); release_db(conn)
        send_sms(mobile, "Your Sewa Setu OTP is %s. Valid for 5 minutes." % code)
        session.permanent = True
        session["apply_mobile"] = mobile
        return redirect(url_for("verify"))
    return render_template("apply.html", captcha_q=make_captcha())


def make_captcha():
    a, b = random.randint(1, 9), random.randint(1, 9)
    session["captcha_answer"] = a + b
    return "%d + %d" % (a, b)


@app.route("/verify", methods=["GET", "POST"])
def verify():
    mobile = session.get("apply_mobile")
    if not mobile:
        return redirect(url_for("apply"))
    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT code, created_at FROM otps WHERE mobile = %s "
                    "ORDER BY id DESC LIMIT 1", (mobile,))
        row = cur.fetchone()
        cur.close(); release_db(conn)
        if row and row[0] == code:
            age = (database_now() - row[1]).total_seconds()
            if age > OTP_VALIDITY_SECONDS:
                app.logger.warning("otp expired mobile=%s age=%ds" % (mobile, int(age)))
                flash("OTP expired. Please request a new OTP.")
                return redirect(url_for("apply"))
            session["verified_mobile"] = mobile
            return redirect(url_for("form_step", step=1))
        flash("Invalid OTP.")
    return render_template("verify.html", mobile=mobile)


@app.route("/form/<int:step>", methods=["GET", "POST"])
def form_step(step):
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if step not in (1, 2, 3):
        abort(404)
    if request.method == "POST":
        data = session.get("form_data", {})
        for k, v in request.form.items():
            data[k] = v
        if step == 1:
            name = sanitize(data.get("applicant_name", ""), maxlen=100)
            dob = parse_dob(data.get("dob", ""))
            if not name:
                flash("Please enter the applicant's full name.")
                return render_template("form_step1.html", data=data, blocks=BLOCKS)
            if dob is None:
                flash("Please enter date of birth in DD/MM/YYYY format.")
                return render_template("form_step1.html", data=data, blocks=BLOCKS)
            today = india_now().date()
            if dob > today:
                flash("Date of birth cannot be in the future.")
                return render_template("form_step1.html", data=data, blocks=BLOCKS)
            if age_on_date(dob, today) < MIN_AGE:
                flash("Applicant must be at least %d years old on the date of application."
                      % MIN_AGE)
                return render_template("form_step1.html", data=data, blocks=BLOCKS)
            data["applicant_name"] = name
        session["form_data"] = data
        if step < 3:
            return redirect(url_for("form_step", step=step + 1))
        return redirect(url_for("upload"))
    return render_template("form_step%d.html" % step,
                           data=session.get("form_data", {}), blocks=BLOCKS)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if request.method == "POST":
        f = request.files.get("document")
        if f is None or f.filename == "":
            flash("Please select a JPG, JPEG, or PDF document.")
            return render_template("upload.html")
        content, extension, error = validate_uploaded_document(f)
        if error:
            flash(error)
            return render_template("upload.html")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = "%s_%s%s" % (
            session["verified_mobile"], uuid.uuid4().hex, extension
        )
        path = os.path.join(UPLOAD_DIR, filename)
        with open(path, "wb") as out:
            out.write(content)
        session["doc_path"] = path
        return redirect(url_for("declaration"))
    return render_template("upload.html")


@app.route("/declaration", methods=["GET", "POST"])
def declaration():
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if request.method == "POST":
        return handle_submission()
    return render_template("declaration.html")


def handle_submission():
    # TODO: split this up some day. It grew. - RK, 09/2024
    mobile = session.get("verified_mobile")
    data = session.get("form_data", {})
    doc_path = session.get("doc_path", "")

    name = sanitize(data.get("applicant_name", ""), maxlen=100)
    village = data.get("village", "").strip()
    block = data.get("block", "").strip()
    gender = data.get("gender", "")
    marital = data.get("marital_status", "")
    husband_name = data.get("husband_name", "")
    husband_employer = data.get("husband_employer", "")
    bank_account = data.get("bank_account", "").strip()
    ifsc = data.get("ifsc", "").strip().upper()
    dob_raw = data.get("dob", "").strip()

    if not name or not village or not block or not bank_account or not dob_raw:
        flash("Something went wrong. Please try again.")
        return redirect(url_for("form_step", step=1))

    if marital == "Widowed":
        if not husband_name or not husband_employer:
            flash("Something went wrong. Please try again.")
            return redirect(url_for("form_step", step=1))

    dob = parse_dob(dob_raw)
    if dob is None:
        flash("Please enter date of birth in DD/MM/YYYY format.")
        return redirect(url_for("form_step", step=1))

    today = india_now().date()
    if dob > today:
        flash("Date of birth cannot be in the future.")
        return redirect(url_for("form_step", step=1))
    age = age_on_date(dob, today)
    if age < MIN_AGE:
        flash("Applicant must be at least %d years old on the date of application."
              % MIN_AGE)
        return redirect(url_for("form_step", step=1))

    if india_now() >= SCHEME_DEADLINE:
        flash("The application deadline has passed.")
        return redirect(url_for("index"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM applications WHERE mobile = %s", (mobile,))
    if cur.fetchone()[0] > 0:
        cur.close(); release_db(conn)
        flash("An application already exists for this mobile number. "
              "Duplicate applications are not permitted.")
        return redirect(url_for("index"))

    app_no = new_application_no()
    try:
        cur.execute(
            """INSERT INTO applications
               (application_no, applicant_name, mobile, dob, gender, marital_status,
                husband_name, husband_employer, village, block, bank_account, ifsc,
                doc_path, status, submitted_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s)
               RETURNING id""",
            (app_no, name, mobile, dob, gender, marital, husband_name,
             husband_employer, village, block, bank_account, ifsc, doc_path,
             database_now()))
    except psycopg2.IntegrityError:
        conn.rollback()
        cur.close(); release_db(conn)
        flash("An application already exists for this mobile number. "
              "Duplicate applications are not permitted.")
        return redirect(url_for("index"))
    new_id = cur.fetchone()[0]

    # status portal account; password is DOB as DDMMYYYY per dept. circular
    portal_pass = dob.strftime("%d%m%Y")
    cur.execute("SELECT count(*) FROM portal_users WHERE mobile = %s", (mobile,))
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO portal_users (mobile, password_hash) VALUES (%s,%s)",
                    (mobile, hash_password(portal_pass)))
    conn.commit()

    app.logger.info("generating acknowledgment pdf application=%d" % new_id)
    pdf_bytes = generate_acknowledgment(cur, new_id)
    ack_dir = os.path.join(UPLOAD_DIR, "ack")
    os.makedirs(ack_dir, exist_ok=True)
    with open(os.path.join(ack_dir, "%d.pdf" % new_id), "wb") as out:
        out.write(pdf_bytes)

    cur.close(); release_db(conn)
    session.pop("form_data", None)
    session.pop("doc_path", None)
    session.pop("verified_mobile", None)
    send_sms(mobile, "Sewa Setu: application %s received. Track at the status portal "
                     "with mobile no. and password (DOB as DDMMYYYY)." % app_no)
    return render_template("confirmation.html", app_no=app_no, app_id=new_id)


def generate_acknowledgment(cur, app_id):
    cur.execute("SELECT application_no, applicant_name, mobile, dob, village, block, "
                "bank_account, ifsc, submitted_at, status FROM applications WHERE id = %s",
                (app_id,))
    row = cur.fetchone()
    pdf = FPDF()
    pdf.add_page()
    font_dir = "/usr/share/fonts/truetype/dejavu"
    font_name = "Helvetica"
    bold_style = "B"
    italic_style = "I"
    regular_path = os.path.join(font_dir, "DejaVuSans.ttf")
    if os.path.exists(regular_path):
        pdf.add_font("DejaVu", "", regular_path)
        font_name = "DejaVu"
        bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")
        italic_path = os.path.join(font_dir, "DejaVuSans-Oblique.ttf")
        if os.path.exists(bold_path):
            pdf.add_font("DejaVu", "B", bold_path)
        else:
            bold_style = ""
        if os.path.exists(italic_path):
            pdf.add_font("DejaVu", "I", italic_path)
        else:
            italic_style = ""
    pdf.set_font(font_name, bold_style, 14)
    pdf.cell(0, 10, "GOVERNMENT OF PURVANCHAL", ln=1, align="C")
    pdf.set_font(font_name, "", 11)
    pdf.cell(0, 8, "Department of Social Welfare", ln=1, align="C")
    pdf.cell(0, 8, "Old Age Pension Scheme - Acknowledgment", ln=1, align="C")
    pdf.ln(4)
    # decorative border, as per approved letterhead design
    pdf.rect(10, 12, 190, 270)
    labels = ["Application No", "Applicant Name", "Mobile", "Date of Birth",
              "Village", "Block", "Bank Account", "IFSC", "Submitted At", "Status"]
    pdf.set_font(font_name, "", 10)
    for label, val in zip(labels, row):
        try:
            pdf.cell(60, 8, label, border=1)
            pdf.cell(0, 8, str(val), border=1, ln=1)
        except Exception:
            pdf.cell(0, 8, "?", border=1, ln=1)
    pdf.ln(6)
    pdf.set_font(font_name, italic_style, 9)
    pdf.multi_cell(0, 5, "This is a computer generated acknowledgment. Processing SLA "
                         "as per the Purvanchal Right to Public Services Act applies.")
    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Status portal (citizen login)
# ---------------------------------------------------------------------------

@app.route("/status", methods=["GET", "POST"])
def status_login():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (mobile,))
        row = cur.fetchone()
        cur.close(); release_db(conn)
        if row and row[0] == hash_password(password):
            session["logged_in"] = True
            session["portal_mobile"] = mobile
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM applications WHERE mobile = %s "
                        "ORDER BY submitted_at DESC LIMIT 1", (mobile,))
            r = cur.fetchone()
            cur.close(); release_db(conn)
            if r:
                return redirect(url_for("view_application", app_id=r[0]))
            flash("No application found for this mobile number.")
            return redirect(url_for("status_login"))
        flash("Something went wrong. Please try again.")
    return render_template("status_login.html")


@app.route("/application/<int:app_id>")
def view_application(app_id):
    if not session.get("logged_in") or not session.get("portal_mobile"):
        flash("Please login to view application status.")
        return redirect(url_for("status_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT application_no, applicant_name, mobile, dob, village, block, "
                "bank_account, ifsc, status, submitted_at, decided_at "
                "FROM applications WHERE id = %s AND mobile = %s",
                (app_id, session["portal_mobile"]))
    row = cur.fetchone()
    cur.close(); release_db(conn)
    if not row:
        abort(404)
    cutoff = database_now() - timedelta(days=SLA_DAYS)
    effective_status = row[8]
    if effective_status == "PENDING" and row[9] <= cutoff:
        effective_status = "DEEMED_APPROVED"
    row = row[:8] + (effective_status,) + row[9:]
    return render_template("application.html", a=row, app_id=app_id)


@app.route("/application/<int:app_id>/edit", methods=["GET", "POST"])
def edit_application(app_id):
    if not session.get("logged_in") or not session.get("portal_mobile"):
        flash("Please login to edit your application.")
        return redirect(url_for("status_login"))

    mobile = session["portal_mobile"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """SELECT applicant_name, mobile, dob, gender, marital_status,
                  husband_name, husband_employer, village, block,
                  bank_account, ifsc, status, submitted_at
           FROM applications
           WHERE id = %s AND mobile = %s""",
        (app_id, mobile))
    row = cur.fetchone()
    if not row:
        cur.close(); release_db(conn)
        abort(404)

    cutoff = database_now() - timedelta(days=SLA_DAYS)
    if row[11] != "PENDING" or row[12] <= cutoff:
        cur.close(); release_db(conn)
        flash("This application can no longer be edited because processing has "
              "finished or the 15-day deadline has passed.")
        return redirect(url_for("view_application", app_id=app_id))

    data = {
        "applicant_name": row[0],
        "dob": row[2].strftime("%d/%m/%Y"),
        "gender": row[3],
        "marital_status": row[4],
        "husband_name": row[5] or "",
        "husband_employer": row[6] or "",
        "village": row[7],
        "block": row[8],
        "bank_account": row[9],
        "ifsc": row[10],
    }
    if request.method == "POST":
        data.update(request.form.to_dict())
        name = sanitize(data.get("applicant_name", ""), maxlen=100)
        dob = parse_dob(data.get("dob", ""))
        today = india_now().date()
        if not name:
            flash("Please enter the applicant's full name.")
        elif dob is None:
            flash("Please enter date of birth in DD/MM/YYYY format.")
        elif dob > today:
            flash("Date of birth cannot be in the future.")
        elif age_on_date(dob, today) < MIN_AGE:
            flash("Applicant must be at least %d years old on the date of application."
                  % MIN_AGE)
        elif not data.get("village", "").strip() or not data.get("block", "").strip():
            flash("Please enter the applicant's village and block.")
        elif not data.get("bank_account", "").strip() or not data.get("ifsc", "").strip():
            flash("Please enter the bank account number and IFSC code.")
        elif (data.get("marital_status") == "Widowed" and
              (not data.get("husband_name", "").strip() or
               not data.get("husband_employer", "").strip())):
            flash("Please enter the husband's name and current employer for a widowed applicant.")
        else:
            cur.execute(
                """UPDATE applications
                   SET applicant_name = %s, dob = %s, gender = %s,
                       marital_status = %s, husband_name = %s,
                       husband_employer = %s, village = %s, block = %s,
                       bank_account = %s, ifsc = %s
                   WHERE id = %s AND mobile = %s AND status = 'PENDING'
                         AND submitted_at > %s""",
                (name, dob, data.get("gender", ""), data.get("marital_status", ""),
                 data.get("husband_name", "").strip(),
                 data.get("husband_employer", "").strip(),
                 data.get("village", "").strip(), data.get("block", "").strip(),
                 data.get("bank_account", "").strip(),
                 data.get("ifsc", "").strip().upper(), app_id, mobile, cutoff))
            if cur.rowcount != 1:
                conn.rollback()
                cur.close(); release_db(conn)
                flash("This application can no longer be edited because its status changed.")
                return redirect(url_for("view_application", app_id=app_id))
            conn.commit()
            cur.close(); release_db(conn)
            flash("Your application was updated successfully.")
            return redirect(url_for("view_application", app_id=app_id))

    cur.close(); release_db(conn)
    return render_template("edit_application.html", data=data, blocks=BLOCKS,
                           app_id=app_id)


@app.route("/ack/<int:app_id>.pdf")
def ack_pdf(app_id):
    mobile = session.get("portal_mobile")
    if not session.get("admin") and not mobile:
        return redirect(url_for("status_login"))
    conn = get_db()
    cur = conn.cursor()
    if session.get("admin"):
        cur.execute("SELECT id FROM applications WHERE id = %s", (app_id,))
    else:
        cur.execute("SELECT id FROM applications WHERE id = %s AND mobile = %s",
                    (app_id, mobile))
    if not cur.fetchone():
        cur.close(); release_db(conn)
        abort(404)
    path = os.path.join(UPLOAD_DIR, "ack", "%d.pdf" % app_id)
    if os.path.exists(path):
        cur.close(); release_db(conn)
        return send_file(path, mimetype="application/pdf")
    data = generate_acknowledgment(cur, app_id)
    cur.close(); release_db(conn)
    return send_file(io.BytesIO(data), mimetype="application/pdf")


@app.route("/status/reset", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        otp = request.form.get("otp", "").strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT mobile FROM portal_users WHERE mobile = %s", (mobile,))
        row = cur.fetchone()
        if not otp:
            if row:
                reset_code = str(random.randint(100000, 999999))
                session["reset_mobile"] = mobile
                session["reset_code"] = reset_code
                session["reset_created_at"] = database_now().isoformat()
                send_sms(mobile, "Your Sewa Setu password reset code is %s." % reset_code)
            cur.close(); release_db(conn)
            flash("If the mobile number exists, a verification code has been sent.")
            return render_template("reset.html", otp_requested=True, mobile=mobile)
        if (session.get("reset_mobile") != mobile or
                session.get("reset_code") != otp):
            cur.close(); release_db(conn)
            flash("Invalid or expired verification code.")
            return render_template("reset.html", otp_requested=True, mobile=mobile)
        created = datetime.fromisoformat(session.get("reset_created_at", ""))
        if (database_now() - created).total_seconds() > OTP_VALIDITY_SECONDS:
            cur.close(); release_db(conn)
            session.pop("reset_code", None)
            flash("Invalid or expired verification code.")
            return render_template("reset.html", otp_requested=True, mobile=mobile)
        newpass = secrets.token_urlsafe(9)
        cur.execute("UPDATE portal_users SET password_hash = %s WHERE mobile = %s",
                    (hash_password(newpass), mobile))
        conn.commit()
        send_sms(mobile, "Sewa Setu: your temporary password is %s." % newpass)
        session.pop("reset_mobile", None)
        session.pop("reset_code", None)
        session.pop("reset_created_at", None)
        cur.close(); release_db(conn)
        flash("Your password was reset and sent to your registered mobile number.")
    return render_template("reset.html")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME and
                request.form.get("password") == ADMIN_PASSWORD):
            session["logged_in"] = True
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.")
    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM applications GROUP BY status")
    by_status = cur.fetchall()
    cur.execute("SELECT count(*) FROM applications WHERE status = 'PENDING' "
                "AND submitted_at <= %s",
                (database_now() - timedelta(days=SLA_DAYS),))
    overdue = cur.fetchone()[0]
    cur.execute("SELECT block, count(*) FROM applications WHERE status = 'PENDING' "
                "GROUP BY block ORDER BY count(*) DESC")
    by_block = cur.fetchall()
    cur.close(); release_db(conn)
    return render_template("admin_dashboard.html", by_status=by_status,
                           overdue=overdue, by_block=by_block, sla=SLA_DAYS)


@app.route("/admin/applications")
def admin_list():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    status = request.args.get("status", "PENDING")
    page = int(request.args.get("page", 1))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, application_no, applicant_name, mobile, block, status, "
                "submitted_at FROM applications WHERE status = %s "
                "ORDER BY submitted_at ASC LIMIT 50 OFFSET %s",
                (status, (page - 1) * 50))
    rows = cur.fetchall()
    cur.close(); release_db(conn)
    return render_template("admin_list.html", rows=rows, status=status, page=page)


@app.route("/admin/application/<int:app_id>")
def admin_view(app_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT application_no, applicant_name, mobile, dob, gender, "
                "marital_status, village, block, bank_account, ifsc, doc_path, "
                "status, submitted_at, decided_at, decided_by "
                "FROM applications WHERE id = %s", (app_id,))
    row = cur.fetchone()
    cur.close(); release_db(conn)
    if not row:
        abort(404)
    return render_template("admin_view.html", a=row, app_id=app_id)


@app.route("/admin/approve/<int:app_id>", methods=["POST"])
def admin_approve(app_id):
    if not session.get("admin"):
        abort(403)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = 'APPROVED', decided_at = %s "
                "WHERE id = %s", (database_now(), app_id))
    conn.commit()
    cur.close(); release_db(conn)
    flash("Application approved.")
    return redirect(url_for("admin_list"))


@app.route("/admin/reject/<int:app_id>", methods=["POST"])
def admin_reject(app_id):
    if not session.get("admin"):
        abort(403)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = 'REJECTED', decided_at = %s "
                "WHERE id = %s", (database_now(), app_id))
    conn.commit()
    cur.close(); release_db(conn)
    flash("Application rejected.")
    return redirect(url_for("admin_list"))


# ---------------------------------------------------------------------------
# Unused / legacy
# ---------------------------------------------------------------------------

def export_to_excel(rows):
    # Was used for the monthly disbursement report before eKosh integration.
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["application_no", "name", "account", "ifsc", "amount"])
    for r in rows:
        writer.writerow(list(r) + ["250"])
    return out.getvalue()


def old_payment_gateway_callback(txn):
    # retained for reference; eChallan integration was descoped in Phase 2
    status = txn.get("STATUS")
    if status == "0300":
        return "SUCCESS"
    elif status == "0399":
        return "FAILED"
    return "PENDING"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
