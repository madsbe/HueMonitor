"""Hue Bridge discovery and connection."""

import requests
import json
from pathlib import Path

DISCOVERY_URL = "https://discovery.meethue.com"


class HueBridge:
    """Manage connection to Hue Bridge."""

    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.ip = None
        self.api_key = None
        self._load_config()

    def _load_config(self):
        """Load bridge configuration."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                config = json.load(f)
                self.ip = config.get("bridge_ip")
                self.api_key = config.get("api_key")

    def _save_config(self):
        """Save bridge configuration."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"bridge_ip": self.ip, "api_key": self.api_key}
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

    def discover(self):
        """Discover Hue Bridge on the network."""
        print("Searching for Hue Bridge...")
        try:
            response = requests.get(DISCOVERY_URL, timeout=10)
            response.raise_for_status()
            bridges = response.json()

            if bridges:
                self.ip = bridges[0].get("internalipaddress")
                print(f"Found bridge at: {self.ip}")
                self._save_config()
                return True
        except requests.RequestException as e:
            print(f"Discovery error: {e}")
        return False

    def generate_api_key(self):
        """Generate API key (requires button press)."""
        if not self.ip:
            print("No bridge IP. Run discover() first.")
            return False

        url = f"http://{self.ip}/api"
        payload = {"devicetype": "hue_sensor_app#python"}

        print("\nPress the link button on your Hue Bridge, then press Enter...")
        input()

        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()

            if isinstance(result, list) and "success" in result[0]:
                self.api_key = result[0]["success"]["username"]
                print("API key generated!")
                self._save_config()
                return True
            elif isinstance(result, list) and "error" in result[0]:
                print(f"Error: {result[0]['error'].get('description')}")
        except requests.RequestException as e:
            print(f"Error: {e}")
        return False

    def connect(self):
        """Connect to bridge, discovering/generating key if needed."""
        if not self.ip:
            if not self.discover():
                return False

        if not self.api_key:
            if not self.generate_api_key():
                return False

        return self.test_connection()

    def test_connection(self):
        """Test the bridge connection."""
        try:
            url = f"http://{self.ip}/api/{self.api_key}/config"
            response = requests.get(url, timeout=5)
            data = response.json()
            if "name" in data:
                print(f"Connected to: {data['name']}")
                return True
        except requests.RequestException:
            pass
        return False

    @property
    def base_url(self):
        """Get the base API URL."""
        return f"http://{self.ip}/api/{self.api_key}"
