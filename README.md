# ZENER — Structural Health Monitoring System

ZENER is a Structural Health Monitoring (SHM) prototype developed for the SIH problem statement. The system monitors multiple sensor nodes placed on a structure and uses sensor data, risk analysis, and TimesFM forecasting to identify potential structural risks.

The current prototype uses JSON-based sensor data and a Flask dashboard. Cloud integration and live sensor connectivity are planned for the next stage.

## Project Overview

ZENER monitors structural parameters from multiple connected sensor nodes.

The system currently processes:

- Crack displacement
- X-axis tilt
- Y-axis tilt
- Vibration
- Battery voltage
- Node status

The collected data is processed by the backend, analyzed using a risk engine, and visualized through a web dashboard.

TimesFM 3.0 is used to forecast future crack displacement for each node.

---

## System Architecture

```text
Sensor Data
     │
     ▼
sensor_data.json
     │
     ▼
Flask Backend
     │
     ├───────────────┐
     ▼               ▼
TimesFM 3.0      Risk Engine
     │               │
     └───────┬───────┘
             ▼
       ZENER Dashboard
             │
             ├── Structural Overview
             ├── Risk Monitoring
             ├── Active Alerts
             ├── Node Status
             └── Node Details

