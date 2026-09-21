"""Supabase persistence for normalized sensor readings."""

import os

from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except ImportError:  # Keep JSON fallback available if the optional client is absent.
    Client = None
    create_client = None


load_dotenv()


class SensorDatabase:
    """Small database boundary used by MQTT ingestion and Flask data loading."""

    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.client = None

        if self.url and self.key and create_client:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as error:
                print(f"SUPABASE unavailable: {error}")

    @property
    def available(self):
        return self.client is not None

    def insert_reading(self, reading):
        """Upsert one MQTT reading, avoiding duplicates by node and timestamp."""
        if not self.client:
            return False

        record = {
            "timestamp": reading.get("timestamp"),
            "node_id": reading.get("node_id"),
            "tilt_x": reading.get("tilt_x_deg"),
            "tilt_y": reading.get("tilt_y_deg"),
            "vibration": reading.get("vibration_g"),
            "crack_disp_mm": reading.get("crack_disp_mm"),
            "temperature": reading.get("temperature_c"),
            "battery": reading.get("battery_v"),
            "state": reading.get("state") or reading.get("status") or "UNKNOWN",
        }

        try:
            self.client.table("sensor_readings").upsert(
                record,
                on_conflict="node_id,timestamp"
            ).execute()
            print("DATABASE INSERT SUCCESS")
            return True
        except Exception as error:
            print(f"SUPABASE INSERT FAILED: {error}")
            return False

    def read_readings(self):
        """Read all historical readings in timestamp order for TimesFM/dashboard."""
        if not self.client:
            return None

        try:
            response = (
                self.client.table("sensor_readings")
                .select("*")
                .order("timestamp")
                .execute()
            )
            rows = response.data or []
            print(f"DATABASE READ SUCCESS: {len(rows)} readings")
            return [self._to_sensor_reading(row) for row in rows]
        except Exception as error:
            print(f"SUPABASE READ FAILED: {error}")
            return None

    @staticmethod
    def _to_sensor_reading(row):
        state = row.get("state") or "UNKNOWN"
        return {
            "timestamp": row.get("timestamp"),
            "node_id": row.get("node_id"),
            "tilt_x_deg": row.get("tilt_x"),
            "tilt_y_deg": row.get("tilt_y"),
            "vibration_g": row.get("vibration"),
            "crack_disp_mm": row.get("crack_disp_mm"),
            "temperature_c": row.get("temperature"),
            "battery_v": row.get("battery"),
            "status": state,
            "state": state,
        }


sensor_database = SensorDatabase()
