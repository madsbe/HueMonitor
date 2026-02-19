"""Sensor reading and parsing."""

import requests
from datetime import datetime


SENSOR_TYPE_MAP = {
    "ZLLPresence": "motion",
    "ZLLTemperature": "temperature",
    "ZLLLightLevel": "light",
    "ZLLSwitch": "switch",
    "ZGPSwitch": "switch",
    "Daylight": "daylight",
}


class SensorReader:
    """Read and parse Hue sensor data."""

    def __init__(self, bridge):
        self.bridge = bridge

    def fetch_all(self):
        """Fetch all sensors from bridge."""
        try:
            url = f"{self.bridge.base_url}/sensors"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching sensors: {e}")
            return {}

    def parse(self, raw_sensors):
        """Parse raw sensor data into structured format."""
        sensors = []
        timestamp = datetime.now().isoformat()

        for sensor_id, data in raw_sensors.items():
            sensor_type = data.get("type", "Unknown")
            category = SENSOR_TYPE_MAP.get(sensor_type, "other")
            name = data.get("name", f"Sensor_{sensor_id}")
            state = data.get("state", {})
            config = data.get("config", {})

            sensor = {
                "id": sensor_id,
                "name": name,
                "type": sensor_type,
                "category": category,
                "timestamp": timestamp,
                "battery": config.get("battery"),
                "reachable": config.get("reachable", True),
                "last_updated": state.get("lastupdated"),
            }

            # Parse type-specific data
            if sensor_type == "ZLLPresence":
                sensor["presence"] = state.get("presence", False)

            elif sensor_type == "ZLLTemperature":
                temp = state.get("temperature")
                sensor["temperature"] = temp / 100.0 if temp else None

            elif sensor_type == "ZLLLightLevel":
                sensor["light_level"] = state.get("lightlevel")
                sensor["dark"] = state.get("dark")
                sensor["daylight"] = state.get("daylight")

            elif sensor_type == "Daylight":
                sensor["daylight"] = state.get("daylight")

            elif "Switch" in sensor_type:
                sensor["button_event"] = state.get("buttonevent")

            else:
                sensor["raw_state"] = state

            sensors.append(sensor)

        return sensors

    def read(self):
        """Read and parse all sensors."""
        raw = self.fetch_all()
        return self.parse(raw)

    def get_by_category(self, sensors, category):
        """Filter sensors by category."""
        return [s for s in sensors if s.get("category") == category]

    def get_by_name(self, sensors, name):
        """Find sensor by name."""
        for s in sensors:
            if s.get("name") == name:
                return s
        return None
