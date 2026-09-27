# ZENER — AI-Enabled Structural Health Monitoring System

> **Smart India Hackathon 2026 — Problem Statement 25**

ZENER is an IoT and AI-powered **Structural Health Monitoring (SHM)** system designed to continuously monitor structural conditions through distributed sensor nodes, detect abnormal behavior, estimate structural risk, forecast crack progression, and provide real-time alerts through a centralized dashboard.

The system combines **ESP32-based sensing, MQTT communication, Supabase cloud storage, Flask backend services, AI-based risk analysis, TimesFM forecasting, and a real-time monitoring dashboard** into a single pipeline.

---

## 🚨 Problem

Structural failures can develop gradually through changes in:

* Crack displacement
* Structural tilt
* Ground/structural vibration
* Other node-level sensor measurements

Traditional inspection methods are often periodic rather than continuous. This creates a need for a system capable of continuously collecting structural data and identifying potentially dangerous changes before they become critical.

---

## 💡 Our Solution

ZENER creates a distributed monitoring network where multiple sensor nodes collect structural parameters and transmit telemetry to a central system.

The collected data is:

1. Received through the communication layer.
2. Stored in the cloud.
3. Processed by the risk-analysis pipeline.
4. Forecast using time-series AI where applicable.
5. Classified into structural health states.
6. Visualized through a centralized dashboard.
7. Used to generate email alerts when a node becomes critical.

### Core monitoring states

```text
NORMAL
   ↓
WATCH
   ↓
CRITICAL
```

The system also distinguishes abnormal sensor behavior such as surface noise from potentially significant structural changes.

---

# 🏗️ System Architecture

```text
┌───────────────────────────────────────────┐
│              SENSOR NODES                 │
│                                           │
│ ESP32 + MPU6050 + Structural Sensors     │
│                                           │
│ Tilt │ Vibration │ Crack │ Battery       │
└───────────────────┬───────────────────────┘
                    │
                    │ MQTT
                    ▼
┌───────────────────────────────────────────┐
│          MQTT COMMUNICATION LAYER         │
│                                           │
│ Telemetry from distributed nodes          │
└───────────────────┬───────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────┐
│              SUPABASE                     │
│                                           │
│ sensor_readings                           │
│ authorized_users                           │
│ historical telemetry                      │
└───────────────────┬───────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────┐
│             FLASK BACKEND                 │
│                                           │
│ Data processing │ APIs │ Authentication   │
│ Session handling │ Alert processing       │
└───────────────┬───────────────┬───────────┘
                │               │
                ▼               ▼
       ┌────────────────┐  ┌────────────────┐
       │  RISK ENGINE   │  │    TimesFM     │
       │                │  │                │
       │ Risk scoring   │  │ Crack forecast │
       │ Status         │  │ Time-series AI │
       └───────┬────────┘  └───────┬────────┘
               │                   │
               └─────────┬─────────┘
                         ▼
              ┌──────────────────────┐
              │   ZENER DASHBOARD    │
              │                      │
              │ Node overview        │
              │ Critical status      │
              │ Crack trends         │
              │ Node details         │
              │ Forecast information │
              └──────────┬───────────┘
                         │
                CRITICAL NODE
                         │
                         ▼
              ┌──────────────────────┐
              │   EMAIL ALERT SYSTEM │
              │                      │
              │ Active authorized    │
              │ users receive alert  │
              └──────────────────────┘
```

---

# ⚙️ Technology Stack

| Layer             | Technology                              |
| ----------------- | --------------------------------------- |
| Microcontroller   | ESP32                                   |
| Sensors           | MPU6050 + structural monitoring sensors |
| Communication     | MQTT                                    |
| MQTT Broker       | EMQX / compatible MQTT broker           |
| Backend           | Python + Flask                          |
| Database          | Supabase / PostgreSQL                   |
| Authentication    | OTP-based email verification            |
| AI Forecasting    | TimesFM 3.0                             |
| Risk Analysis     | Custom risk engine                      |
| Anomaly Detection | Isolation Forest prototype              |
| Frontend          | HTML, CSS, JavaScript                   |
| Configuration     | Python dotenv                           |
| Version Control   | Git + GitHub                            |

---

# 📡 IoT Sensor Layer

Each monitoring node is designed to collect structural telemetry.

Typical node data includes:

```json
{
  "timestamp": "...",
  "node_id": "MESH_A07",
  "tilt_x_deg": 0.03,
  "tilt_y_deg": 0.04,
  "vibration_g": 0.02,
  "crack_disp_mm": 0.12,
  "battery_v": 3.72
}
```

The architecture supports multiple distributed nodes rather than relying on a single sensor.

Example node identifiers:

```text
MESH_A01
MESH_A02
MESH_A03
MESH_A07
...
```

---

# 🔄 MQTT Telemetry

Sensor nodes publish telemetry through MQTT.

Example topic:

```text
mines/subsidence/telemetry
```

The MQTT ingestion service receives incoming messages and forwards the data to the backend/cloud storage layer.

The system is therefore capable of moving from simulated telemetry to actual ESP32-generated sensor data without changing the overall dashboard architecture.

---

# ☁️ Supabase Cloud Database

Supabase is used as the central cloud data layer.

### `sensor_readings`

Stores historical sensor telemetry used by the dashboard and forecasting pipeline.

Typical fields include:

```text
timestamp
node_id
tilt_x_deg
tilt_y_deg
vibration_g
crack_disp_mm
battery_v
status
```

Historical readings are important because the forecasting system requires a time series rather than a single measurement.

---

# 🤖 AI / ML Pipeline

ZENER uses AI at multiple stages of the monitoring pipeline.

## 1. Risk Analysis

The risk engine combines current sensor measurements and forecasting information to estimate structural risk.

Conceptually:

```text
Current Crack
      +
Forecasted Crack
      +
Tilt
      +
Vibration
      +
Battery / Sensor Health
      ↓
Risk Engine
      ↓
Risk Score + Structural Status
```

The system can classify nodes into states such as:

```text
NORMAL
WATCH
CRITICAL
SURFACE_NOISE
CRITICAL_SUDDEN
```

---

## 2. TimesFM Crack Forecasting

**TimesFM** is used specifically for **crack-displacement forecasting**.

The dashboard focuses the main trend visualization on crack progression because crack forecasting is the primary time-series AI component.

Historical crack measurements are supplied to TimesFM, producing future crack estimates.

```text
Historical Crack Data
        ↓
     TimesFM
        ↓
Future Crack Forecast
        ↓
Maximum / Trend Analysis
        ↓
Risk Engine
```

This allows ZENER to move beyond simply reporting the current sensor value and provide an indication of possible future crack progression.

---

# 🧠 Structural Risk Engine

The risk engine evaluates multiple parameters instead of depending on a single sensor.

Example inputs:

```text
Current crack
Forecasted crack
Tilt X
Tilt Y
Vibration
Battery
```

A node can therefore be considered critical based on a combination of current conditions and predicted deterioration.

This is important because high vibration alone should not automatically imply structural failure.

For example:

```text
High vibration
+
Low crack displacement
+
Stable tilt
        ↓
Possible surface noise
```

whereas:

```text
Increasing crack
+
Increasing tilt
+
High vibration
+
Increasing forecast
        ↓
Higher structural risk
```

---

# 📊 ZENER Dashboard

The dashboard provides a centralized view of the complete monitoring network.

### Main dashboard capabilities

* Overall structural monitoring status
* Multiple node monitoring
* Node-wise health status
* Critical-node identification
* Crack trend visualization
* Forecast information
* Node-specific details
* Sensor values
* Battery information
* Risk information
* Real-time telemetry integration

### Node details

Clicking a node provides detailed information such as:

```text
Node ID
Tilt X
Tilt Y
Vibration
Crack displacement
Battery
Current status
Risk information
Forecast information
```

The dashboard is designed so that operators can move from:

```text
Overall Network
       ↓
Specific Node
       ↓
Sensor Details
       ↓
Risk / Forecast
```

---

# 🔐 Authorized Email Login

ZENER uses email-based OTP authentication.

Authorized users are stored dynamically in Supabase rather than being hard-coded into the application.

### `authorized_users`

```text
id
email
name
active
created_at
```

Login flow:

```text
Enter Email
     ↓
Check Supabase
     ↓
Authorized + Active?
     ↓
    YES
     ↓
Generate OTP
     ↓
Send OTP through configured email
     ↓
Verify OTP
     ↓
Create Session
     ↓
Dashboard Access
```

Unauthorized emails are rejected before an OTP is sent.

This allows authorized users to be added or deactivated without changing application code.

---

# 📧 Critical Node Email Alerts

ZENER can automatically notify authorized users when a node enters the `CRITICAL` state.

The system dynamically retrieves active authorized users from Supabase.

```text
Node telemetry
      ↓
Risk Engine
      ↓
CRITICAL
      ↓
Check previous state
      ↓
New CRITICAL state?
      ↓
     YES
      ↓
Fetch active authorized users
      ↓
Send email alert
```

The alert can contain:

```text
Node ID
Current status
Current crack value
Forecast value
Tilt
Vibration
Battery
Timestamp
Dashboard reference
```

### Anti-spam behavior

Emails are **not** sent for every CRITICAL sensor reading.

An alert is generated when:

```text
WATCH/NORMAL → CRITICAL
```

If the node remains CRITICAL:

```text
CRITICAL → CRITICAL
```

no repeated email is generated.

If it recovers:

```text
CRITICAL → NORMAL
```

and later becomes critical again:

```text
NORMAL → CRITICAL
```

a new alert is generated.

---

# 📁 Project Structure

The project contains the core AI/risk pipeline, backend/dashboard components, cloud integration, and supporting configuration.

A representative structure is:

```text
SIHPS25ZENER/
│
├── app.py
├── risk_engine.py
├── timesfm_forecast.py
├── mqtt_ingestion.py
├── supabase_db.py
├── EDA.py
│
├── templates/
│   ├── dashboard.html
│   └── node_details.html
│
├── sensor_data.json
├── requirements.txt
├── .gitignore
└── README.md
```

> The exact file structure may evolve as the hardware and cloud layers are integrated further.

# 🔮 Future Scope

The current architecture can be extended toward a complete field-deployable SHM platform.

### Edge AI Gateway

A Raspberry Pi can act as an edge gateway between the sensor mesh and the cloud.

```text
ESP32 Nodes
     ↓
Mesh Network
     ↓
Raspberry Pi Gateway
     ↓
Edge Processing
     ↓
Cloud
```

A lightweight anomaly/risk model can run locally to reduce latency and bandwidth requirements.

### Mesh Networking

The system can be extended from individual MQTT-connected nodes toward a distributed ESP32 mesh network.

### More Sensors

Future nodes can incorporate additional structural parameters such as:

* Advanced crack sensors
* Displacement sensors
* Environmental sensors
* Additional vibration sensing
* Structural strain measurements

### Improved Prediction

Future versions can combine multiple time-series variables rather than forecasting crack displacement alone.

### Mobile / Remote Alerts

The notification layer can later support additional channels alongside email.

---

# 🎯 Project Workflow

The complete ZENER workflow can be summarized as:

```text
SENSE
  ↓
ESP32 sensor nodes collect structural data
  ↓
TRANSMIT
  ↓
MQTT / mesh communication
  ↓
STORE
  ↓
Supabase cloud database
  ↓
ANALYZE
  ↓
Risk Engine + anomaly detection
  ↓
PREDICT
  ↓
TimesFM crack forecasting
  ↓
CLASSIFY
  ↓
NORMAL / WATCH / CRITICAL
  ↓
VISUALIZE
  ↓
ZENER monitoring dashboard
  ↓
ALERT
  ↓
Email notification to authorized users
```

---

# 🌟 Key Features

* 📡 Distributed IoT-based structural monitoring
* 🔗 MQTT telemetry communication
* ☁️ Supabase cloud data storage
* 🧠 AI-assisted structural risk analysis
* 📈 TimesFM-based crack forecasting
* 🚨 Critical-state detection
* 📊 Real-time monitoring dashboard
* 🔐 Authorized email OTP login
* 📧 Dynamic critical-node email alerts
* 🗄️ Historical sensor data storage
* 🔋 Battery and sensor-health monitoring
* 🔬 Extensible architecture for edge AI and mesh networking

---

# 🏆 Project Goal

ZENER aims to transform structural monitoring from periodic inspection into a **continuous, data-driven, predictive monitoring system**.

By combining IoT sensing, cloud infrastructure, AI forecasting, risk analysis, and real-time visualization, the platform provides a foundation for earlier detection of potentially dangerous structural changes.

---

## 👥 Team

**Team:** ZENER
**Project:** ZENER — Structural Health Monitoring
**Competition:** Smart India Hackathon 2026
**Problem Statement:** 25

---


