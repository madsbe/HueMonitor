"""Hue light reading and control."""

import requests
from datetime import datetime


LIGHT_TYPE_MAP = {
    "Extended color light": "color",
    "Color light": "color",
    "Color temperature light": "white_ambiance",
    "Dimmable light": "dimmable",
    "On/Off plug-in unit": "plug",
    "On/off light": "on_off",
}


class LightReader:
    """Read and control Hue lights."""

    def __init__(self, bridge):
        self.bridge = bridge

    def fetch_all(self):
        """Fetch all lights from bridge."""
        try:
            url = f"{self.bridge.base_url}/lights"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching lights: {e}")
            return {}

    def parse(self, raw_lights):
        """Parse raw light data into structured format."""
        lights = []
        timestamp = datetime.now().isoformat()

        for light_id, data in raw_lights.items():
            light_type = data.get("type", "Unknown")
            category = LIGHT_TYPE_MAP.get(light_type, "other")
            state = data.get("state", {})

            light = {
                "id": light_id,
                "name": data.get("name", f"Light_{light_id}"),
                "type": light_type,
                "category": category,
                "model": data.get("modelid"),
                "manufacturer": data.get("manufacturername"),
                "timestamp": timestamp,
                "on": state.get("on", False),
                "reachable": state.get("reachable", True),
            }

            # Brightness (1-254 scale -> 0-100%)
            bri = state.get("bri")
            if bri is not None:
                light["brightness"] = round(bri / 254 * 100)

            # Color temperature (mireds -> kelvin)
            ct = state.get("ct")
            if ct is not None:
                light["ct"] = ct
                light["ct_kelvin"] = round(1000000 / ct) if ct > 0 else None

            # Color info
            if state.get("colormode"):
                light["colormode"] = state["colormode"]
            if state.get("hue") is not None:
                light["hue"] = state["hue"]
                light["sat"] = state.get("sat")
            if state.get("xy"):
                light["xy"] = state["xy"]

            lights.append(light)

        return lights

    def read(self):
        """Read and parse all lights."""
        raw = self.fetch_all()
        return self.parse(raw)

    def set_state(self, light_id, **state):
        """Set the state of a light.

        Common state parameters:
            on (bool): Turn light on/off
            bri (int): Brightness 1-254
            ct (int): Color temperature in mireds
            hue (int): Hue 0-65535
            sat (int): Saturation 0-254
        """
        try:
            url = f"{self.bridge.base_url}/lights/{light_id}/state"
            response = requests.put(url, json=state, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error setting light state: {e}")
            return None

    def toggle(self, light_id):
        """Toggle a light on/off. Returns new state."""
        raw = self.fetch_all()
        light = raw.get(str(light_id))
        if not light:
            return None
        current_on = light.get("state", {}).get("on", False)
        new_on = not current_on
        self.set_state(light_id, on=new_on)
        return new_on
