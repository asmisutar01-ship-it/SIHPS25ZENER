import numpy as np
from datetime import datetime


def format_alert_time(timestamp_value):
    """Return HH:MM:SS from an ISO-like timestamp value."""
    if timestamp_value is None:
        return "N/A"

    try:
        if isinstance(timestamp_value, str):
            timestamp_value = timestamp_value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(timestamp_value)
        else:
            dt = timestamp_value

        return dt.strftime("%H:%M:%S")
    except Exception:
        return str(timestamp_value)


def build_alert_details(node):
    """Create a student-friendly alert summary with reason bullets and score."""
    risk = node.get("risk", "NORMAL")
    score = node.get("score")
    current_crack = node.get("current_crack")
    forecast_increase = node.get("forecast_increase")
    tilt_magnitude = node.get("tilt_magnitude")
    vibration = node.get("vibration")
    timestamp = node.get("timestamp")

    reasons = []

    if current_crack is not None:
        if current_crack >= 10:
            reasons.append("Crack displacement is high")
        elif current_crack >= 5:
            reasons.append("Crack displacement is elevated")

    if forecast_increase is not None:
        if forecast_increase >= 3:
            reasons.append("Forecast indicates further increase")
        elif forecast_increase >= 1:
            reasons.append("Forecast shows moderate increase")

    if tilt_magnitude is not None:
        if tilt_magnitude >= 2:
            reasons.append("Tilt magnitude exceeds threshold")
        elif tilt_magnitude >= 1:
            reasons.append("Tilt magnitude is elevated")

    if vibration is not None:
        if vibration >= 1.5:
            reasons.append("Vibration is high")
        elif vibration >= 0.5:
            reasons.append("Vibration is elevated")

    if not reasons:
        reasons.append("Sensor readings indicate abnormal trend")

    risk_score = int(score) if isinstance(score, (int, float)) else 0
    risk_score = max(0, min(10, risk_score))

    return {
        "node_id": node.get("node_id"),
        "risk": risk,
        "reasons": reasons,
        "risk_score": risk_score,
        "formatted_time": format_alert_time(timestamp),
        "timestamp": timestamp,
    }


def calculate_risk(
    current_crack,
    forecast,
    tilt_x,
    tilt_y,
    vibration,
    battery
):

    # Maximum predicted crack displacement
    max_forecast = float(np.max(forecast))

    # Predicted increase in crack displacement
    forecast_increase = max_forecast - current_crack

    # Tilt magnitude in degrees
    tilt_magnitude = np.sqrt(tilt_x ** 2 + tilt_y ** 2)

    score = 0

    # --------------------------
    # CURRENT CRACK
    # --------------------------

    if current_crack < 5:
        score += 0
    elif current_crack < 10:
        score += 1
    else:
        score += 2

    # --------------------------
    # FORECAST INCREASE
    # --------------------------

    if forecast_increase < 1:
        score += 0
    elif forecast_increase < 3:
        score += 1
    else:
        score += 2

    # --------------------------
    # TILT MAGNITUDE
    # --------------------------

    if tilt_magnitude < 1:
        score += 0
    elif tilt_magnitude < 2:
        score += 1
    else:
        score += 2

    # --------------------------
    # VIBRATION
    # --------------------------

    if vibration < 0.5:
        score += 0
    elif vibration < 1.5:
        score += 1
    else:
        score += 2

    # --------------------------
    # STRUCTURAL RISK
    # --------------------------

    if score <= 2:
        risk = "NORMAL"
    elif score <= 5:
        risk = "WARNING"
    else:
        risk = "CRITICAL"

    # --------------------------
    # SENSOR HEALTH
    # --------------------------

    if battery >= 3.3:
        sensor_health = "HEALTHY"
    elif battery >= 3.0:
        sensor_health = "LOW_BATTERY"
    else:
        sensor_health = "HARDWARE_WARNING"

    return {
        "risk": risk,
        "score": score,
        "current_crack": current_crack,
        "max_forecast": max_forecast,
        "forecast_increase": forecast_increase,
        "tilt_magnitude": float(tilt_magnitude),
        "vibration": vibration,
        "battery": battery,
        "sensor_health": sensor_health
    }