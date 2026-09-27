from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from functools import wraps
import json
import os
import secrets
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pandas as pd
import numpy as np

from risk_engine import calculate_risk, build_alert_details
from timesfm_forecast import forecast_node
from mqtt_ingestion import mqtt_ingestion
from supabase_db import sensor_database


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "zener-secret-shm-key-2026")
mqtt_ingestion.start()


# ============================================================
# LOAD SENSOR DATA
# ============================================================

def load_sensor_data():

    database_readings = sensor_database.read_readings()

    if database_readings:
        return database_readings

    if mqtt_ingestion.has_readings():
        return mqtt_ingestion.get_readings()

    file_path = os.path.join(
        os.path.dirname(__file__),
        "sensor_data.json"
    )

    with open(file_path, "r") as file:
        return json.load(file)


def numeric_value(value, default=None):

    if value is None or pd.isna(value):
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def effective_dashboard_status(sensor_status, risk_result):

    status = str(sensor_status).strip().upper() if sensor_status is not None else ""

    if status == "HARDWARE_FAULT":
        return "HARDWARE_FAULT"

    if status in {"CRITICAL", "WARNING", "NORMAL"}:
        return status

    score = numeric_value(risk_result.get("score"))
    if score is not None and np.isfinite(score):
        return risk_result.get("risk") or "UNKNOWN"

    if status:
        return status

    if risk_result.get("risk") == "HARDWARE_FAULT":
        return "HARDWARE_FAULT"

    return "UNKNOWN"


# ============================================================
# GET LATEST READING OF EVERY NODE
# ============================================================

def get_latest_readings(data):

    latest = {}

    for reading in data:

        node_id = reading["node_id"]

        if (
            node_id not in latest
            or reading["timestamp"] > latest[node_id]["timestamp"]
        ):
            latest[node_id] = reading

    return latest


# ============================================================
# CALCULATE RISK FOR ONE NODE
# ============================================================

def calculate_node_risk(df, node):

    node_df = df[
        df["node_id"] == node
    ].sort_values("timestamp")


    if node_df.empty:

        return None


    # Latest sensor reading
    latest = node_df.iloc[-1]


    current_crack = numeric_value(latest.get("crack_disp_mm"))
    tilt_x = numeric_value(latest.get("tilt_x_deg"), 0.0)
    tilt_y = numeric_value(latest.get("tilt_y_deg"), 0.0)
    vibration = numeric_value(latest.get("vibration_g"), 0.0)
    battery = numeric_value(latest.get("battery_v"))


    # --------------------------------------------------------
    # Hardware fault / missing crack data
    # --------------------------------------------------------

    if pd.isna(current_crack):

        tilt_magnitude = (
            tilt_x ** 2 +
            tilt_y ** 2
        ) ** 0.5

        result = {

            "risk": "HARDWARE_FAULT",

            "score": None,

            "current_crack": None,

            "max_forecast": None,

            "forecast_increase": None,

            "tilt_magnitude": tilt_magnitude,

            "vibration": vibration,

            "battery": battery,

            "sensor_health": "HARDWARE_FAULT"

        }

        print(f"AI/RISK RESULT: {node} -> {result['risk']}")
        return result


    # --------------------------------------------------------
    # TIMESFM FORECAST
    # --------------------------------------------------------

    forecast = forecast_node(
        df,
        node
    )


    # --------------------------------------------------------
    # Forecast unavailable
    # --------------------------------------------------------

    if forecast is None:

        result = {

            "risk": "UNKNOWN",

            "score": None,

            "current_crack": float(current_crack),

            "max_forecast": None,

            "forecast_increase": None,

            "tilt_magnitude": (
                tilt_x ** 2 +
                tilt_y ** 2
            ) ** 0.5,

            "vibration": vibration,

            "battery": battery,

            "sensor_health": "UNKNOWN"

        }

        print(f"AI/RISK RESULT: {node} -> {result['risk']}")
        return result


    # --------------------------------------------------------
    # RISK ENGINE
    # --------------------------------------------------------

    result = calculate_risk(
        float(current_crack),
        np.asarray(
            forecast,
            dtype=float
        ),
        float(tilt_x),
        float(tilt_y),
        float(vibration),
        battery if battery is not None else 0.0
    )

    result["battery"] = battery

    # Store TimesFM forecast so the dashboard can use it
    result["forecast"] = [
        float(value)
        for value in forecast
    ]

    print(f"AI/RISK RESULT: {node} -> {result['risk']}")

    return result


# ============================================================
# BUILD ALL NODE RESULTS
# ============================================================

def build_node_list(data):

    # Convert JSON → DataFrame
    df = pd.DataFrame(data)

    # Convert timestamps
    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce"
    )

    # Sort data
    df = df.sort_values(
        [
            "node_id",
            "timestamp"
        ]
    )


    latest_readings = get_latest_readings(
        data
    )


    node_list = []
    forecast_data = {}


    for node_id in sorted(
        latest_readings.keys()
    ):

        latest = latest_readings[
            node_id
        ]

        risk_result = calculate_node_risk(
            df,
            node_id
        )


        if risk_result is None:
            continue


        combined = latest.copy()

        combined.update(
            risk_result
        )

        effective_status = effective_dashboard_status(
            latest.get("status"),
            risk_result
        )
        combined["status"] = effective_status
        combined["risk"] = effective_status

        if "forecast" in risk_result:

            forecast_data[node_id] = [
                float(value)
                for value in risk_result["forecast"]
            ]


        # Convert numpy values to normal Python values
        for key, value in combined.items():

            if isinstance(
                value,
                np.generic
            ):

                combined[key] = value.item()


        node_list.append(
            combined
        )
    return node_list, df, forecast_data


# ============================================================
# DASHBOARD CALCULATIONS
# ============================================================

def calculate_dashboard(data):

    node_list, df, forecast_data = build_node_list(
        data
    )


    # --------------------------------------------------------
    # Critical nodes
    # --------------------------------------------------------

    critical_nodes = [

        node

        for node in node_list

        if node["status"] == "CRITICAL"

    ]

    critical_count = len(
        critical_nodes
    )


    # --------------------------------------------------------
    # Maximum current crack
    # --------------------------------------------------------

    valid_cracks = [

        node

        for node in node_list

        if node["current_crack"] is not None

    ]


    if valid_cracks:

        max_crack_node_data = max(

            valid_cracks,

            key=lambda node:
            node["current_crack"]

        )


        max_crack = (
            max_crack_node_data[
                "current_crack"
            ]
        )

        max_crack_node = (
            max_crack_node_data[
                "node_id"
            ]
        )

    else:

        max_crack = 0

        max_crack_node = "N/A"


    # --------------------------------------------------------
    # Highest risk node
    # --------------------------------------------------------

    risk_priority = {

        "CRITICAL": 4,

        "WARNING": 3,

        "NORMAL": 2,

        "HARDWARE_FAULT": 1,

        "UNKNOWN": 0

    }


    highest_node = max(
        node_list,
        key=lambda node: risk_priority.get(node["status"], 0)
    ) if node_list else {
        "node_id": "N/A",
        "status": "UNKNOWN",
        "risk": "UNKNOWN",
        "score": None,
        "sensor_health": "UNKNOWN"
    }


    # --------------------------------------------------------
    # Overall risk
    # --------------------------------------------------------

    overall_risk = highest_node["status"]

    risk_score = highest_node.get("score")


    # --------------------------------------------------------
    # Alerts
    # --------------------------------------------------------

    alerts = [

        build_alert_details(node)

        for node in node_list

        if node["status"] in [

            "CRITICAL",

            "WARNING"

        ]

    ]


    alerts.sort(

        key=lambda node:
        node["timestamp"],

        reverse=True

    )


    # --------------------------------------------------------
    # Active nodes
    # --------------------------------------------------------

    active_nodes = sum(

        1

        for node in node_list

        if node["sensor_health"]
        != "HARDWARE_FAULT"

    )


    # --------------------------------------------------------
    # Node IDs
    # --------------------------------------------------------

    node_ids = sorted(
        node["node_id"]
        for node in node_list
    )

    # Fire critical alert emails on node transitions
    _check_and_fire_critical_alerts(node_list)

    print("DASHBOARD DATA UPDATED")

    return {

        "node_list": node_list,

        "node_ids": node_ids,

        "critical_count": critical_count,

        "total_nodes": len(node_list),

        "max_crack": max_crack,

        "max_crack_node": max_crack_node,

        "highest_node": highest_node,

        "overall_risk": overall_risk,

        "risk_score": risk_score,

        "alerts": alerts,

        "active_nodes": active_nodes,

        "sensor_data": data,

        "forecast_data": forecast_data

    }


# ============================================================
# CRITICAL ALERT STATE TRACKER
# ============================================================

# Tracks the last known status per node to detect CRITICAL transitions.
_node_last_status = {}


def _send_critical_alert_emails(node_id, risk_result):
    """
    Query all active authorized users and send a CRITICAL alert email to each.
    Called only when a node transitions INTO CRITICAL for the first time.
    """
    recipients = sensor_database.get_active_authorized_users()
    if not recipients:
        print(f"CRITICAL ALERT: no active authorized users to notify for {node_id}")
        return

    score = risk_result.get("score")
    score_str = f"{score:.2f}" if score is not None else "N/A"
    crack = risk_result.get("current_crack")
    crack_str = f"{crack:.2f} mm" if crack is not None else "N/A"
    tilt = risk_result.get("tilt_magnitude")
    tilt_str = f"{tilt:.2f}°" if tilt is not None else "N/A"
    vibration = risk_result.get("vibration")
    vibration_str = f"{vibration:.4f} g" if vibration is not None else "N/A"

    subject = f"🚨 ZENER CRITICAL ALERT — Node {node_id}"
    body_text = (
        f"CRITICAL STRUCTURAL ALERT\n\n"
        f"Node {node_id} has transitioned to CRITICAL status.\n\n"
        f"Risk Score   : {score_str}\n"
        f"Crack Disp.  : {crack_str}\n"
        f"Tilt Magnitude: {tilt_str}\n"
        f"Vibration    : {vibration_str}\n\n"
        f"Please review the ZENER dashboard immediately.\n"
        f"ZENER Structural Health Monitoring Platform"
    )
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; color: #17202a; }}
        .container {{ max-width: 520px; margin: auto; background: #ffffff; border: 1px solid #e2e6ea; border-radius: 10px; padding: 32px; }}
        .brand {{ font-size: 20px; font-weight: bold; letter-spacing: 2px; color: #17202a; margin-bottom: 20px; }}
        .brand span {{ color: #7b8794; font-size: 13px; font-weight: normal; margin-left: 8px; border-left: 1px solid #d9dde1; padding-left: 8px; }}
        .alert-badge {{ background: #e53935; color: #fff; display: inline-block; padding: 6px 16px; border-radius: 20px; font-weight: 700; font-size: 13px; letter-spacing: 1px; margin-bottom: 18px; }}
        .title {{ font-size: 20px; font-weight: 700; margin-bottom: 8px; color: #b71c1c; }}
        .node-id {{ font-size: 28px; font-weight: 900; color: #e53935; letter-spacing: 2px; margin: 16px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ text-align: left; color: #55606d; font-size: 12px; font-weight: 600; padding: 6px 8px; border-bottom: 2px solid #e2e6ea; }}
        td {{ padding: 8px; font-size: 14px; border-bottom: 1px solid #f0f2f4; }}
        td.value {{ font-weight: 700; color: #17202a; }}
        .note {{ font-size: 13px; color: #55606d; line-height: 1.6; margin-top: 16px; }}
        .footer {{ font-size: 12px; color: #9aa5b1; margin-top: 24px; border-top: 1px solid #edf0f2; padding-top: 14px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="brand">ZENER <span>Structural Health Monitoring</span></div>
        <div class="alert-badge">&#x26A0; CRITICAL ALERT</div>
        <div class="title">Node Transitioned to CRITICAL</div>
        <div class="node-id">{node_id}</div>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Risk Score</td><td class="value">{score_str}</td></tr>
            <tr><td>Crack Displacement</td><td class="value">{crack_str}</td></tr>
            <tr><td>Tilt Magnitude</td><td class="value">{tilt_str}</td></tr>
            <tr><td>Vibration</td><td class="value">{vibration_str}</td></tr>
        </table>
        <p class="note">This node has exceeded safe operational thresholds. Please review the ZENER dashboard immediately and take appropriate action.</p>
        <div class="footer">ZENER SHM &middot; Critical Alert System</div>
    </div>
</body>
</html>"""

    for user in recipients:
        recipient_email = user.get("email", "").strip()
        if not recipient_email:
            continue
        ok, err = _smtp_send(recipient_email, subject, body_text, body_html)
        if ok:
            print(f"CRITICAL ALERT EMAIL SENT: {recipient_email} for node {node_id}")
        else:
            print(f"CRITICAL ALERT EMAIL FAILED: {recipient_email} — {err}")


def _smtp_send(recipient_email, subject, body_text, body_html):
    """Send a pre-composed email via SMTP. Returns (success, message)."""
    mail_address = os.getenv("MAIL_ADDRESS", "").strip()
    mail_password = os.getenv("MAIL_PASSWORD", "").strip()
    mail_host = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    mail_port = int(os.getenv("MAIL_PORT", "587"))

    if not mail_address or not mail_password:
        return False, "Email credentials not configured."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"ZENER SHM <{mail_address}>"
        msg["To"] = recipient_email
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        if mail_port == 465:
            server = smtplib.SMTP_SSL(mail_host, mail_port, timeout=15)
            server.login(mail_address, mail_password)
        else:
            server = smtplib.SMTP(mail_host, mail_port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(mail_address, mail_password)

        server.send_message(msg)
        server.quit()
        return True, "sent"
    except Exception as exc:
        return False, str(exc)


def _check_and_fire_critical_alerts(node_list):
    """
    Compare each node's current status to its last known status.
    Fire alert emails only on the NORMAL/WARNING → CRITICAL transition.
    """
    for node in node_list:
        node_id = node.get("node_id")
        current_status = node.get("status", "")
        previous_status = _node_last_status.get(node_id)

        if current_status == "CRITICAL" and previous_status != "CRITICAL":
            print(f"ALERT TRIGGER: {node_id} transitioned to CRITICAL (was {previous_status})")
            import threading as _threading
            _threading.Thread(
                target=_send_critical_alert_emails,
                args=(node_id, node),
                daemon=True
            ).start()

        _node_last_status[node_id] = current_status


# ============================================================
# AUTHENTICATION (SMTP Email OTP Flow)
# ============================================================

OTP_EXPIRY_SECONDS = 300  # 5 minutes
OTP_COOLDOWN_SECONDS = 60  # 60-second cooldown between resends
otp_storage = {}


def generate_otp():
    """Generate a temporary 6-digit numeric OTP."""
    return f"{secrets.randbelow(1000000):06d}"


def send_otp_email(recipient_email, otp_code):
    """
    Send the 6-digit OTP code to recipient via SMTP.
    Uses MAIL_ADDRESS and MAIL_PASSWORD (e.g. Gmail App Password) from .env.
    """
    mail_address = os.getenv("MAIL_ADDRESS", "").strip()
    mail_password = os.getenv("MAIL_PASSWORD", "").strip()
    mail_host = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    mail_port = int(os.getenv("MAIL_PORT", "587"))

    if not mail_address or not mail_password:
        return False, "Email credentials (MAIL_ADDRESS, MAIL_PASSWORD) are not configured in .env."

    subject = f"ZENER Verification Code: {otp_code}"
    body_text = f"""Hello,

Your 6-digit verification code for ZENER Structural Health Monitoring is:

{otp_code}

This code will expire in 5 minutes.
If you did not request this verification code, please ignore this email.

ZENER SHM Platform
"""
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; color: #17202a; }}
        .container {{ max-width: 480px; margin: auto; background: #ffffff; border: 1px solid #e2e6ea; border-radius: 10px; padding: 32px; }}
        .brand {{ font-size: 20px; font-weight: bold; letter-spacing: 2px; color: #17202a; margin-bottom: 20px; }}
        .brand span {{ color: #7b8794; font-size: 13px; font-weight: normal; margin-left: 8px; border-left: 1px solid #d9dde1; padding-left: 8px; }}
        .title {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; }}
        .otp-box {{ background: #f4f6f8; border: 2px dashed #17202a; border-radius: 8px; padding: 18px; text-align: center; margin: 24px 0; }}
        .otp-code {{ font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #17202a; }}
        .note {{ font-size: 13px; color: #55606d; line-height: 1.5; }}
        .footer {{ font-size: 12px; color: #9aa5b1; margin-top: 24px; border-top: 1px solid #edf0f2; padding-top: 14px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="brand">ZENER <span>Structural Health Monitoring</span></div>
        <div class="title">Authentication Code</div>
        <p>Use the following 6-digit one-time password to complete your sign-in to the ZENER dashboard:</p>
        <div class="otp-box">
            <div class="otp-code">{otp_code}</div>
        </div>
        <p class="note">This code is valid for <strong>5 minutes</strong>. If you did not request this login code, you can safely ignore this email.</p>
        <div class="footer">
            Secure OTP Authentication &middot; ZENER SHM
        </div>
    </div>
</body>
</html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"ZENER SHM <{mail_address}>"
        msg["To"] = recipient_email
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        if mail_port == 465:
            server = smtplib.SMTP_SSL(mail_host, mail_port, timeout=15)
            server.login(mail_address, mail_password)
        else:
            server = smtplib.SMTP(mail_host, mail_port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(mail_address, mail_password)

        server.send_message(msg)
        server.quit()
        return True, "Email sent successfully."
    except Exception as exc:
        return False, str(exc)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email or "@" not in email:
            return render_template(
                "login.html",
                step="email",
                email=email,
                error="Please enter a valid email address."
            )

        # --- Authorization check ---
        if not sensor_database.is_user_authorized(email):
            return render_template(
                "login.html",
                step="email",
                email=email,
                error="Unauthorized email address. Please contact your system administrator."
            )

        now = time.time()
        record = otp_storage.get(email)
        if record and (now - record.get("last_sent_at", 0) < OTP_COOLDOWN_SECONDS):
            remaining = int(OTP_COOLDOWN_SECONDS - (now - record["last_sent_at"]))
            return render_template(
                "login.html",
                step="verify",
                email=email,
                cooldown=remaining,
                error=f"Please wait {remaining} seconds before requesting a new code."
            )

        otp_code = generate_otp()
        success, message = send_otp_email(email, otp_code)

        if not success:
            return render_template(
                "login.html",
                step="email",
                email=email,
                error=f"Could not send OTP: {message}"
            )

        otp_storage[email] = {
            "otp": otp_code,
            "expires_at": now + OTP_EXPIRY_SECONDS,
            "last_sent_at": now
        }

        return render_template(
            "login.html",
            step="verify",
            email=email,
            cooldown=OTP_COOLDOWN_SECONDS,
            message=f"A 6-digit verification code has been sent to {email}. It expires in 5 minutes."
        )

    return render_template("login.html", step="email")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return redirect(url_for("login"))

    email = request.form.get("email", "").strip()
    token = request.form.get("token", "").strip() or request.form.get("otp", "").strip()

    if not email:
        return redirect(url_for("login"))

    if not token:
        return render_template(
            "login.html",
            step="verify",
            email=email,
            error="Please enter the 6-digit verification code."
        )

    record = otp_storage.get(email)
    now = time.time()

    if not record:
        return render_template(
            "login.html",
            step="verify",
            email=email,
            error="No active verification code found for this email. Please request a new one."
        )

    if now > record.get("expires_at", 0):
        otp_storage.pop(email, None)
        return render_template(
            "login.html",
            step="verify",
            email=email,
            error="The verification code has expired (5-minute limit). Please request a new one."
        )

    if record.get("otp") != token:
        return render_template(
            "login.html",
            step="verify",
            email=email,
            error="Invalid verification code. Please check your email and try again."
        )

    # Valid OTP verified!
    otp_storage.pop(email, None)
    session.clear()
    session["user"] = {
        "email": email
    }
    return redirect(url_for("dashboard"))


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    if "user" in session:
        return redirect(url_for("dashboard"))

    email = request.form.get("email", "").strip()
    if not email or "@" not in email:
        return redirect(url_for("login"))

    now = time.time()
    record = otp_storage.get(email)

    if record and (now - record.get("last_sent_at", 0) < OTP_COOLDOWN_SECONDS):
        remaining = int(OTP_COOLDOWN_SECONDS - (now - record["last_sent_at"]))
        return render_template(
            "login.html",
            step="verify",
            email=email,
            cooldown=remaining,
            error=f"Please wait {remaining} seconds before requesting a new code."
        )

    otp_code = generate_otp()
    success, message = send_otp_email(email, otp_code)

    if not success:
        return render_template(
            "login.html",
            step="verify",
            email=email,
            error=f"Could not resend OTP: {message}"
        )

    otp_storage[email] = {
        "otp": otp_code,
        "expires_at": now + OTP_EXPIRY_SECONDS,
        "last_sent_at": now
    }

    return render_template(
        "login.html",
        step="verify",
        email=email,
        cooldown=OTP_COOLDOWN_SECONDS,
        message=f"A new 6-digit verification code has been sent to {email}."
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
@login_required
def dashboard():

    data = load_sensor_data()

    dashboard_data = calculate_dashboard(
        data
    )


    return render_template(

        "dashboard.html",

        **dashboard_data

    )


# ============================================================
# NODE DETAILS PAGE
# ============================================================

@app.route("/node/<node_id>")
@login_required
def node_details(node_id):

    data = load_sensor_data()

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    node_data = df[
        df["node_id"] == node_id
    ].sort_values("timestamp")

    if node_data.empty:
        return render_template(
            "node_details.html",
            node_id=node_id,
            not_found=True,
            message=f"Node {node_id} not found.",
            back_to_dashboard="/",
            historical=[],
            forecast=[],
            latest={},
            risk={},
            node_data={}
        ), 404

    latest = node_data.iloc[-1].to_dict()
    historical = node_data.to_dict(orient="records")

    risk_result = calculate_node_risk(df, node_id)
    forecast = []

    if risk_result is not None:
        forecast = risk_result.get("forecast", [])

    node_data_record = {
        "node_id": node_id,
        "timestamp": latest.get("timestamp"),
        "current_crack": latest.get("crack_disp_mm"),
        "tilt_x_deg": latest.get("tilt_x_deg"),
        "tilt_y_deg": latest.get("tilt_y_deg"),
        "vibration_g": latest.get("vibration_g"),
        "battery_v": latest.get("battery_v")
    }

    if risk_result is None:
        risk_result = {
            "risk": "UNKNOWN",
            "score": None,
            "current_crack": latest.get("crack_disp_mm"),
            "max_forecast": None,
            "forecast_increase": None,
            "tilt_magnitude": None,
            "vibration": latest.get("vibration_g"),
            "battery": latest.get("battery_v"),
            "sensor_health": "UNKNOWN"
        }

    if risk_result.get("current_crack") is None or pd.isna(risk_result.get("current_crack")):
        forecast = []
        risk_result["risk"] = "HARDWARE_FAULT"
        risk_result["sensor_health"] = "HARDWARE_FAULT"

    context = {
        "node_id": node_id,
        "not_found": False,
        "historical": historical,
        "latest": latest,
        "risk": risk_result,
        "forecast": forecast,
        "back_to_dashboard": "/",
        "node_data": node_data_record
    }

    return render_template(
        "node_details.html",
        **context
    )


@app.route("/api/dashboard-data")
def dashboard_data_api():

    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = load_sensor_data()
    dashboard_data = calculate_dashboard(data)

    return jsonify({
        "node_list": dashboard_data["node_list"],
        "sensor_data": dashboard_data["sensor_data"],
        "forecast_data": dashboard_data["forecast_data"]
    })


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )