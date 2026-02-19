"""Hue Event Stream for real-time sensor updates."""

import json
import requests
from datetime import datetime

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except (ImportError, AttributeError):
    pass


class HueEventStream:
    """Connect to Hue Bridge event stream for real-time updates."""

    def __init__(self, bridge_ip, api_key):
        self.bridge_ip = bridge_ip
        self.api_key = api_key
        self.base_url = f"https://{bridge_ip}"
        self.headers = {"hue-application-key": api_key}
        self._sensor_map = {}  # Map resource IDs to sensor names

    def _build_sensor_map(self):
        """Build a map of v2 resource IDs to sensor names."""
        url = f"{self.base_url}/clip/v2/resource/motion"
        try:
            response = requests.get(url, headers=self.headers, verify=False, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for sensor in data.get("data", []):
                    rid = sensor.get("id")
                    # Get the device name from owner
                    owner = sensor.get("owner", {})
                    owner_rid = owner.get("rid")
                    if owner_rid:
                        # Fetch device info
                        device_url = f"{self.base_url}/clip/v2/resource/device/{owner_rid}"
                        dev_resp = requests.get(device_url, headers=self.headers, verify=False, timeout=5)
                        if dev_resp.status_code == 200:
                            dev_data = dev_resp.json()
                            if dev_data.get("data"):
                                name = dev_data["data"][0].get("metadata", {}).get("name", f"Sensor_{rid[:8]}")
                                self._sensor_map[rid] = name
                    if rid not in self._sensor_map:
                        self._sensor_map[rid] = f"Motion_{rid[:8]}"
                print(f"Mapped {len(self._sensor_map)} motion sensors")
        except Exception as e:
            print(f"Error building sensor map: {e}")

    def get_sensor_name(self, resource_id):
        """Get sensor name from resource ID."""
        return self._sensor_map.get(resource_id, f"Unknown_{resource_id[:8]}")

    def listen(self, on_motion_callback, on_error_callback=None):
        """Listen to event stream and call callback on motion events.

        on_motion_callback(sensor_name, motion_detected, timestamp)
        """
        # Build sensor map first
        self._build_sensor_map()

        url = f"{self.base_url}/eventstream/clip/v2"
        print(f"Connecting to event stream at {url}...")

        try:
            response = requests.get(
                url,
                headers={**self.headers, "Accept": "text/event-stream"},
                verify=False,
                stream=True,
                timeout=None
            )

            if response.status_code != 200:
                print(f"Event stream error: {response.status_code}")
                return

            print("Connected to event stream. Listening for motion events...")
            print("Press Ctrl+C to stop\n")

            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            events = json.loads(data_str)
                            self._process_events(events, on_motion_callback)
                        except json.JSONDecodeError:
                            pass

        except KeyboardInterrupt:
            print("\nEvent stream stopped.")
        except Exception as e:
            print(f"Event stream error: {e}")
            if on_error_callback:
                on_error_callback(e)

    def _process_events(self, events, callback):
        """Process events from the stream."""
        for event in events:
            event_type = event.get("type")
            data_list = event.get("data", [])

            for data in data_list:
                resource_type = data.get("type")

                # Motion sensor event
                if resource_type == "motion":
                    rid = data.get("id")
                    motion = data.get("motion", {})
                    motion_detected = motion.get("motion")

                    if motion_detected is not None:
                        sensor_name = self.get_sensor_name(rid)
                        timestamp = datetime.now()
                        callback(sensor_name, motion_detected, timestamp)
