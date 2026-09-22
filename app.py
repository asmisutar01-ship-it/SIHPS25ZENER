from flask import Flask, jsonify, render_template
import json
import os
import pandas as pd
import numpy as np

from risk_engine import calculate_risk, build_alert_details
from timesfm_forecast import forecast_node
from mqtt_ingestion import mqtt_ingestion
from supabase_db import sensor_database


app = Flask(__name__)
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
# HOME PAGE
# ============================================================

@app.route("/")
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