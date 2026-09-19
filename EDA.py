import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from timesfm3 import TimesFM3Forecaster, ModelConfig
from risk_engine import calculate_risk

# Load JSON
with open("sensor_data.json", "r") as file:
    data = json.load(file)

# Convert JSON to DataFrame
df = pd.DataFrame(data)

# Convert timestamp
df["timestamp"] = pd.to_datetime(df["timestamp"])

print("Shape:", df.shape)
print("\nColumns:")
print(df.columns.tolist())

print("\nFirst 5 rows:")
print(df.head())

print("\nData types:")
print(df.dtypes)

# -----------------------------
# EDA STEP 2: DATA QUALITY
# -----------------------------

# 1. Missing values
print("\n--- Missing Values ---")
print(df.isnull().sum())


# 2. Duplicate rows
print("\n--- Duplicate Rows ---")
print("Number of duplicate rows:", df.duplicated().sum())


# 3. Sort by node and timestamp
df = df.sort_values(["node_id", "timestamp"])


# 4. Calculate time difference between readings for each node
df["time_diff"] = df.groupby("node_id")["timestamp"].diff()

print("\n--- Time Differences ---")
print(df[["node_id", "timestamp", "time_diff"]].head(20))


# 5. Show different time intervals
print("\n--- Time Interval Distribution ---")
print(df["time_diff"].value_counts().sort_index())

# -----------------------------
# EDA STEP 3: NODE & STATUS ANALYSIS
# -----------------------------

print("\n--- Number of readings per node ---")
print(df["node_id"].value_counts().sort_index())


print("\n--- Status distribution ---")
print(df["status"].value_counts())


print("\n--- Status distribution by node ---")
print(pd.crosstab(df["node_id"], df["status"]))


print("\n--- Time range for each node ---")
print(
    df.groupby("node_id")["timestamp"]
      .agg(["min", "max"])
)

# -----------------------------
# EDA STEP 4: SENSOR STATISTICS
# -----------------------------

sensor_columns = [
    "tilt_x_deg",
    "tilt_y_deg",
    "vibration_g",
    "crack_disp_mm",
    "battery_v"
]

print("\n--- Sensor Statistics ---")
print(df[sensor_columns].describe())

# -----------------------------
# EDA STEP 5: CRACK DISPLACEMENT
# -----------------------------

node = "MESH_A02"

node_df = df[df["node_id"] == node].copy()
node_df = node_df.sort_values("timestamp")

# Create one plot for each sensor
sensors = [
    "tilt_x_deg",
    "tilt_y_deg",
    "vibration_g",
    "crack_disp_mm",
    "battery_v"
]

for sensor in sensors:
    plt.figure(figsize=(12, 4))

    plt.plot(
        node_df["timestamp"],
        node_df[sensor],
        marker="o"
    )

    plt.xlabel("Time")
    plt.ylabel(sensor)
    plt.title(f"{sensor} over time - {node}")

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# ==============================
# DATA PREPROCESSING
# ==============================


def forecast_node(node):
    """Create a TimesFM forecast for one node using its own crack displacement history."""
    node_df = df[df["node_id"] == node].copy()
    if node_df.empty:
        return None

    node_df = node_df.sort_values("timestamp")
    node_df = node_df[["timestamp", "crack_disp_mm"]].copy()
    node_df = node_df.set_index("timestamp")
    node_15min = node_df.resample("15min").mean()

    if node_15min.empty:
        return None

    node_15min["crack_disp_mm"] = (
        node_15min["crack_disp_mm"].interpolate(method="linear")
    )

    valid_y = node_15min["crack_disp_mm"].dropna()
    if len(valid_y) < 3:
        return None

    timesfm_df = node_15min.reset_index()
    timesfm_df["unique_id"] = node
    timesfm_df = timesfm_df.rename(columns={"timestamp": "ds", "crack_disp_mm": "y"})
    timesfm_df = timesfm_df[["unique_id", "ds", "y"]]

    context = timesfm_df["y"].dropna().astype(np.float32).values
    if len(context) < 3:
        return None

    outputs = list(
        model.predict_batch(
            [context],
            horizon=8,
            return_quantiles=True,
            use_symmetric_averaging=False
        )
    )

    return outputs[0].forecast


# ==============================
# LOAD TIMESFM 3.0
# ==============================

print("\nLoading TimesFM 3.0...")

config = ModelConfig(
    checkpoint_path="google/timesfm-3.0-pytorch",
    per_core_batch_size=1,
    device="cpu"
)

model = TimesFM3Forecaster(config)

print("TimesFM 3.0 loaded successfully!")

# ==============================
# FORECAST EACH NODE
# ==============================

nodes = sorted(df["node_id"].unique())
all_results = {}

for node in nodes:
    node_df = df[df["node_id"] == node].sort_values("timestamp")
    latest = node_df.iloc[-1] if not node_df.empty else None

    if latest is None:
        all_results[node] = {
            "risk": "UNKNOWN",
            "score": None,
            "current_crack": None,
            "max_forecast": None,
            "forecast_increase": None,
            "tilt_magnitude": None,
            "vibration": None,
            "battery": None,
            "sensor_health": "HARDWARE_WARNING"
        }
        continue

    current_crack = latest.get("crack_disp_mm")
    tilt_x = latest.get("tilt_x_deg", 0.0)
    tilt_y = latest.get("tilt_y_deg", 0.0)
    vibration = latest.get("vibration_g", 0.0)
    battery = latest.get("battery_v", 0.0)

    if pd.isna(current_crack):
        all_results[node] = {
            "risk": "UNKNOWN",
            "score": None,
            "current_crack": current_crack,
            "max_forecast": None,
            "forecast_increase": None,
            "tilt_magnitude": (tilt_x ** 2 + tilt_y ** 2) ** 0.5,
            "vibration": vibration,
            "battery": battery,
            "sensor_health": "HARDWARE_WARNING"
        }
        continue

    forecast = forecast_node(node)
    if forecast is None:
        all_results[node] = {
            "risk": "UNKNOWN",
            "score": None,
            "current_crack": float(current_crack),
            "max_forecast": None,
            "forecast_increase": None,
            "tilt_magnitude": (tilt_x ** 2 + tilt_y ** 2) ** 0.5,
            "vibration": vibration,
            "battery": battery,
            "sensor_health": "HARDWARE_WARNING"
        }
        continue

    result = calculate_risk(
        float(current_crack),
        np.asarray(forecast, dtype=float),
        float(tilt_x),
        float(tilt_y),
        float(vibration),
        float(battery)
    )
    all_results[node] = result

print("\n========================================")
print("       ALL NODE RISK SUMMARY")
print("========================================")

for node in nodes:
    result = all_results.get(node)
    if result is None:
        continue

    print(f"\nNode: {node}")
    print(f"Current Crack: {result.get('current_crack')}")
    print(f"Maximum Forecast: {result.get('max_forecast')}")
    print(f"Forecast Increase: {result.get('forecast_increase')}")
    print(f"Tilt Magnitude: {result.get('tilt_magnitude')}")
    print(f"Vibration: {result.get('vibration')}")
    print(f"Battery: {result.get('battery')}")
    print(f"Structural Risk: {result.get('risk')}")
    print(f"Risk Score: {result.get('score')}")
    print(f"Sensor Health: {result.get('sensor_health')}")

