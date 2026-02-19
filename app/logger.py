"""Organized sensor logging by type and name."""

import json
from datetime import datetime
from pathlib import Path


class SensorLogger:
    """Log sensor data organized by type and name."""

    def __init__(self, base_path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_sensor_file(self, sensor):
        """Get the log file path for a sensor."""
        category = sensor.get("category", "other")
        name = self._sanitize_name(sensor.get("name", f"sensor_{sensor['id']}"))

        # Create category directory
        category_dir = self.base_path / category
        category_dir.mkdir(parents=True, exist_ok=True)

        return category_dir / f"{name}.json"

    def _sanitize_name(self, name):
        """Sanitize sensor name for use as filename."""
        # Replace spaces and special chars
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    def _load_sensor_log(self, filepath):
        """Load existing sensor log or create new structure."""
        if filepath.exists():
            with open(filepath) as f:
                return json.load(f)
        return {
            "sensor_info": {},
            "readings": []
        }

    def _save_sensor_log(self, filepath, data):
        """Save sensor log to file."""
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def log_sensor(self, sensor):
        """Log a single sensor reading."""
        # Skip motion sensors when no presence detected
        if sensor.get("category") == "motion" and not sensor.get("presence"):
            return

        filepath = self._get_sensor_file(sensor)
        log_data = self._load_sensor_log(filepath)

        # Update sensor info
        log_data["sensor_info"] = {
            "id": sensor.get("id"),
            "name": sensor.get("name"),
            "type": sensor.get("type"),
            "category": sensor.get("category"),
        }

        # Create reading entry
        reading = {
            "timestamp": sensor.get("timestamp"),
            "battery": sensor.get("battery"),
            "reachable": sensor.get("reachable"),
            "last_updated": sensor.get("last_updated"),
        }

        # Add type-specific data
        category = sensor.get("category")
        if category == "motion":
            reading["presence"] = sensor.get("presence")
        elif category == "temperature":
            reading["temperature"] = sensor.get("temperature")
        elif category == "light":
            reading["light_level"] = sensor.get("light_level")
            reading["dark"] = sensor.get("dark")
            reading["daylight"] = sensor.get("daylight")
        elif category == "switch":
            reading["button_event"] = sensor.get("button_event")
        elif category == "daylight":
            reading["daylight"] = sensor.get("daylight")
        else:
            reading["raw_state"] = sensor.get("raw_state")

        # Append reading
        log_data["readings"].append(reading)

        # Keep last 1000 readings per sensor
        if len(log_data["readings"]) > 1000:
            log_data["readings"] = log_data["readings"][-1000:]

        self._save_sensor_log(filepath, log_data)

    def log_all(self, sensors):
        """Log all sensors."""
        for sensor in sensors:
            self.log_sensor(sensor)

    def get_sensor_history(self, category, name, limit=100):
        """Get history for a specific sensor."""
        name = self._sanitize_name(name)
        filepath = self.base_path / category / f"{name}.json"

        if not filepath.exists():
            return []

        with open(filepath) as f:
            data = json.load(f)
            return data.get("readings", [])[-limit:]

    def get_latest_reading(self, category, name):
        """Get the latest reading for a sensor."""
        history = self.get_sensor_history(category, name, limit=1)
        return history[0] if history else None

    def list_sensors(self):
        """List all logged sensors."""
        sensors = []
        for category_dir in self.base_path.iterdir():
            if category_dir.is_dir():
                for sensor_file in category_dir.glob("*.json"):
                    with open(sensor_file) as f:
                        data = json.load(f)
                        info = data.get("sensor_info", {})
                        info["readings_count"] = len(data.get("readings", []))
                        sensors.append(info)
        return sensors
