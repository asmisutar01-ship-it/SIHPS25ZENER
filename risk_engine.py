import numpy as np


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
    # FORECASTED CRACK
    # --------------------------

    if forecast_increase < 1:
        score += 0
    elif forecast_increase < 3:
        score += 1
    else:
        score += 2

    # --------------------------
    # TILT
    # --------------------------

    tilt_magnitude = (
        tilt_x ** 2 + tilt_y ** 2
    ) ** 0.5

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
        "tilt_magnitude": tilt_magnitude,
        "vibration": vibration,
        "battery": battery,
        "sensor_health": sensor_health
    }