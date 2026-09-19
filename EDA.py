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

# Select one node
node = "MESH_A02"

node_df = df[df["node_id"] == node].copy()

# Sort by time
node_df = node_df.sort_values("timestamp")

# Keep required columns
node_df = node_df[
    ["timestamp", "crack_disp_mm"]
]

# Make timestamp the index
node_df = node_df.set_index("timestamp")

# Resample to 15-minute intervals
node_15min = node_df.resample("15min").mean()

print("\n--- Resampled data ---")
print(node_15min)

print("\n--- Missing values after resampling ---")
print(node_15min.isnull().sum())

# ==============================
# CREATE TIMESFM-READY DATA
# ==============================

node = "MESH_A02"

node_df = df[df["node_id"] == node].copy()

# Sort by timestamp
node_df = node_df.sort_values("timestamp")

# Keep only timestamp and target
node_df = node_df[
    ["timestamp", "crack_disp_mm"]
]

# Set timestamp as index
node_df = node_df.set_index("timestamp")

# Resample to 15-minute intervals
node_15min = node_df.resample("15min").mean()

# Interpolate missing values
node_15min["crack_disp_mm"] = (
    node_15min["crack_disp_mm"]
    .interpolate(method="linear")
)

print("\n--- TimesFM-ready data ---")
print(node_15min)

# to check if there are any remaining missing values after interpolation
print("\n--- Remaining missing values ---")
print(node_15min.isnull().sum())

# Create TimesFM input DataFrame

timesfm_df = node_15min.reset_index()

timesfm_df["unique_id"] = node

timesfm_df = timesfm_df.rename(
    columns={
        "timestamp": "ds",
        "crack_disp_mm": "y"
    }
)

timesfm_df = timesfm_df[
    ["unique_id", "ds", "y"]
]

print("\n--- Final TimesFM input ---")
print(timesfm_df)

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
# PREPARE FORECAST INPUT
# ==============================

context = timesfm_df["y"].values.astype(np.float32)

print("\nInput points:", len(context))
print("Last 5 observations:")
print(context[-5:])

# ==============================
# FIRST FORECAST
# ==============================

horizon = 8

outputs = list(
    model.predict_batch(
        [context],
        horizon=horizon,
        return_quantiles=True,
        use_symmetric_averaging=False
    )
)

forecast = outputs[0].forecast

print("\n--- FORECAST ---")

for i, value in enumerate(forecast):
    print(f"Future step {i+1}: {value:.3f} mm")

# ==============================
# FORECAST VISUALIZATION
# ==============================

# Historical timestamps
history_time = timesfm_df["ds"]

# Historical values
history_values = timesfm_df["y"]

# Create future timestamps
future_time = pd.date_range(
    start=history_time.iloc[-1] + pd.Timedelta(minutes=15),
    periods=horizon,
    freq="15min"
)

plt.figure(figsize=(12, 5))

# Historical data
plt.plot(
    history_time,
    history_values,
    marker="o",
    label="Historical"
)

# Forecast
plt.plot(
    future_time,
    forecast,
    marker="o",
    linestyle="--",
    label="TimesFM Forecast"
)

plt.xlabel("Time")
plt.ylabel("Crack displacement (mm)")
plt.title("MESH_A02 - Crack Displacement Forecast")

plt.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# ==============================
# SEND DATA TO RISK ENGINE
# ==============================

node = "MESH_A02"

latest = (
    df[df["node_id"] == node]
    .sort_values("timestamp")
    .iloc[-1]
)

current_crack = float(latest["crack_disp_mm"])
tilt_x = float(latest["tilt_x_deg"])
tilt_y = float(latest["tilt_y_deg"])
vibration = float(latest["vibration_g"])
battery = float(latest["battery_v"])


result = calculate_risk(
    current_crack=current_crack,
    forecast=forecast,
    tilt_x=tilt_x,
    tilt_y=tilt_y,
    vibration=vibration,
    battery=battery
)

print("\n==============================")
print("       RISK ENGINE")
print("==============================")

print("Node:", node)
print("Current crack:", result["current_crack"], "mm")
print("Maximum forecast:", result["max_forecast"], "mm")
print("Forecast increase:", result["forecast_increase"], "mm")
print("Tilt magnitude:", result["tilt_magnitude"], "degrees")
print("Vibration:", result["vibration"], "g")
print("Battery:", result["battery"], "V")

print("------------------------------")
print("STRUCTURAL RISK:", result["risk"])
print("RISK SCORE:", result["score"])
print("SENSOR HEALTH:", result["sensor_health"])