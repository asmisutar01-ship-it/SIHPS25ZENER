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
    if current_crack is None:
        current_crack = node.get("crack_disp_mm")
    forecast_increase = node.get("forecast_increase")
    tilt_x = node.get("tilt_x")
    if tilt_x is None:
        tilt_x = node.get("tilt_x_deg")
    tilt_y = node.get("tilt_y")
    if tilt_y is None:
        tilt_y = node.get("tilt_y_deg")
    tilt_magnitude = node.get("tilt_magnitude")
    vibration = node.get("vibration")
    if vibration is None:
        vibration = node.get("vibration_g")
    timestamp = node.get("timestamp")

    reasons = []

    # ESP32: crack_disp_mm > 2.0 -> CRITICAL
    if current_crack is not None:
        if current_crack > 2.0:
            reasons.append(f"Crack displacement ({current_crack:.2f} mm) exceeds critical limit (>2.0 mm)")
        elif current_crack >= 1.0:
            reasons.append(f"Crack displacement ({current_crack:.2f} mm) is elevated")

    # ESP32: abs(tilt_x_deg) > 25.0 -> CRITICAL; > 10.0 -> WARNING
    if tilt_x is not None:
        if abs(tilt_x) > 25.0:
            reasons.append(f"Tilt X ({tilt_x:.1f}°) exceeds critical limit (±25.0°)")
        elif abs(tilt_x) > 10.0:
            reasons.append(f"Tilt X ({tilt_x:.1f}°) exceeds warning threshold (±10.0°)")

    # ESP32: abs(tilt_y_deg) > 25.0 -> CRITICAL; > 10.0 -> WARNING
    if tilt_y is not None:
        if abs(tilt_y) > 25.0:
            reasons.append(f"Tilt Y ({tilt_y:.1f}°) exceeds critical limit (±25.0°)")
        elif abs(tilt_y) > 10.0:
            reasons.append(f"Tilt Y ({tilt_y:.1f}°) exceeds warning threshold (±10.0°)")

    # Fallback to tilt_magnitude if individual axes are unavailable
    if (tilt_x is None and tilt_y is None) and tilt_magnitude is not None:
        if tilt_magnitude > 25.0:
            reasons.append(f"Tilt magnitude ({tilt_magnitude:.1f}°) exceeds critical limit (>25.0°)")
        elif tilt_magnitude > 10.0:
            reasons.append(f"Tilt magnitude ({tilt_magnitude:.1f}°) exceeds warning threshold (>10.0°)")

    # ESP32: vibration_g > 0.10 -> WARNING
    if vibration is not None:
        if vibration > 0.10:
            reasons.append(f"Vibration ({vibration:.2f} g) exceeds warning threshold (>0.10 g)")

    if forecast_increase is not None and forecast_increase >= 1.0:
        reasons.append("Forecast indicates further crack expansion")

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
    max_forecast = float(np.max(forecast)) if len(forecast) > 0 else float(current_crack)

    # Predicted increase in crack displacement
    forecast_increase = max_forecast - current_crack

    # Tilt magnitude in degrees (retained for display/metrics)
    tilt_magnitude = float(np.sqrt(tilt_x ** 2 + tilt_y ** 2))

    # --------------------------------------------------------
    # STATUS CLASSIFICATION (EXACT ESP32 SENSOR-NODE LOGIC)
    # --------------------------------------------------------
    # CRITICAL (STATE_ALERT):
    #   crack_disp_mm > 2.0 OR abs(tilt_x_deg) > 25.0 OR abs(tilt_y_deg) > 25.0
    # WARNING (STATE_WARNING):
    #   vibration_g > 0.10 OR abs(tilt_x_deg) > 10.0 OR abs(tilt_y_deg) > 10.0
    # NORMAL (STATE_NORMAL):
    #   Everything else
    # --------------------------------------------------------

    if (
        current_crack > 2.0
        or abs(tilt_x) > 25.0
        or abs(tilt_y) > 25.0
    ):
        risk = "CRITICAL"
        score = 8
    elif (
        vibration > 0.10
        or abs(tilt_x) > 10.0
        or abs(tilt_y) > 10.0
    ):
        risk = "WARNING"
        score = 4
    else:
        risk = "NORMAL"
        score = 1

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
        "tilt_x": tilt_x,
        "tilt_y": tilt_y,
        "vibration": vibration,
        "battery": battery,
        "sensor_health": sensor_health
    }