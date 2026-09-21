"""Small MQTT ingestion layer for live Wokwi sensor readings."""

import json
import os
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

try:
    from sklearn.ensemble import IsolationForest
except ImportError:
    IsolationForest = None

from supabase_db import sensor_database


load_dotenv()


class MQTTIngestion:
    """Subscribe to sensor packets and expose normalized readings to Flask."""

    def __init__(self, broker=None, port=None, topic=None):
        self.broker = broker or os.getenv("MQTT_BROKER")
        port_value = port or os.getenv("MQTT_PORT")
        self.port = int(port_value) if port_value else None
        self.topic = topic or os.getenv("MQTT_TOPIC")
        self._lock = threading.Lock()
        self._readings = {}
        self._anomaly_history = {}
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self):
        """Start the network loop without blocking Flask startup."""
        if not self.broker or not self.port or not self.topic:
            print("MQTT unavailable: MQTT_BROKER, MQTT_PORT, and MQTT_TOPIC are required")
            return

        try:
            self.client.connect_async(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as error:
            print(f"MQTT unavailable: {error}")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self.connected = True
            client.subscribe(self.topic)
            print("MQTT CONNECTED")
            print(f"MQTT SUBSCRIBED: {self.topic}")
        else:
            print(f"MQTT connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=None, properties=None):
        self.connected = False
        print("MQTT DISCONNECTED")

    def _on_message(self, client, userdata, message):
        try:
            packet = json.loads(message.payload.decode("utf-8"))
            reading = self._normalize_packet(packet)
            if reading is None:
                print("MQTT malformed packet: missing node_id or metrics")
                return

            with self._lock:
                node_readings = self._readings.setdefault(reading["node_id"], [])
                node_readings.append(reading)
                self._readings[reading["node_id"]] = node_readings[-200:]

                anomaly = self._detect_anomaly(reading)

            sensor_database.insert_reading(reading)

            print("MESSAGE RECEIVED")
            print(f"NODE: {reading['node_id']}")
            print(f"DATA: {reading}")
            print(f"ANOMALY SCORE: {anomaly['score']}")
            print(f"AI ALERT: {anomaly['alert']} | STATUS: {reading['state']}")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"MQTT malformed packet: {error}")

    @staticmethod
    def _first_value(values, *keys):
        for key in keys:
            if key in values and values[key] is not None:
                return values[key]
        return None

    def _normalize_packet(self, packet):
        if not isinstance(packet, dict):
            return None

        node_id = packet.get("node_id")
        metrics = packet.get("metrics")
        if not node_id or not isinstance(metrics, dict):
            return None

        tilt = metrics.get("tilt")
        tilt = tilt if isinstance(tilt, dict) else {}
        timestamp = packet.get("timestamp") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        tilt_x = self._first_value(metrics, "tilt_x_deg", "tilt_x")
        tilt_y = self._first_value(metrics, "tilt_y_deg", "tilt_y")

        if tilt_x is None:
            tilt_x = self._first_value(tilt, "x", "tilt_x_deg")
        if tilt_y is None:
            tilt_y = self._first_value(tilt, "y", "tilt_y_deg")

        return {
            "timestamp": timestamp,
            "node_id": str(node_id),
            "tilt_x_deg": tilt_x,
            "tilt_y_deg": tilt_y,
            "vibration_g": self._first_value(metrics, "vibration_g", "vibration"),
            "crack_switch": self._first_value(metrics, "crack_switch"),
            "crack_disp_mm": self._first_value(metrics, "crack_disp_mm", "crack_displacement", "crack"),
            "temperature_c": self._first_value(metrics, "temperature_c", "temp_c", "temp", "temperature"),
            "battery_v": self._first_value(metrics, "battery_v", "battery"),
            "status": packet.get("state") or metrics.get("state") or "UNKNOWN",
            "state": packet.get("state") or metrics.get("state") or "UNKNOWN",
        }

    def _detect_anomaly(self, reading):
        """Run Isolation Forest on a short per-node rolling feature history."""
        features = [
            reading.get("tilt_x_deg") or 0.0,
            reading.get("tilt_y_deg") or 0.0,
            reading.get("vibration_g") or 0.0,
            reading.get("crack_disp_mm") or 0.0,
            reading.get("temperature_c") or 0.0,
        ]
        node_id = reading["node_id"]
        history = self._anomaly_history.setdefault(node_id, [])
        history.append(features)
        self._anomaly_history[node_id] = history[-100:]

        if IsolationForest is None or len(history) < 5:
            return {"score": "N/A", "alert": "INSUFFICIENT_HISTORY"}

        detector = IsolationForest(contamination="auto", random_state=42)
        detector.fit(history)
        score = float(detector.decision_function([features])[0])
        alert = "ANOMALY" if detector.predict([features])[0] == -1 else "NORMAL"
        return {"score": round(score, 4), "alert": alert}

    def get_readings(self):
        """Return a snapshot in the existing list-of-readings format."""
        with self._lock:
            return [reading for readings in self._readings.values() for reading in readings]

    def has_readings(self):
        with self._lock:
            return bool(self._readings)


mqtt_ingestion = MQTTIngestion()
