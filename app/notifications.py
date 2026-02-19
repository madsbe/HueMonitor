"""Pushover notifications for sensor alerts."""

import requests
import json
from pathlib import Path
from datetime import datetime, timedelta


PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier:
    """Send notifications via Pushover (optional)."""

    def __init__(self, user_key=None, api_token=None):
        self.user_key = user_key
        self.api_token = api_token
        self._last_notifications = {}  # Track to avoid spam

    @property
    def enabled(self):
        """Check if Pushover is configured."""
        return bool(self.user_key and self.api_token)

    def send(self, title, message, priority=0, sound=None):
        """Send a Pushover notification.

        Priority levels:
            -2: Lowest (no notification)
            -1: Low (quiet)
             0: Normal
             1: High (bypass quiet hours)
             2: Emergency (requires acknowledgment)
        """
        if not self.enabled:
            return False

        payload = {
            "token": self.api_token,
            "user": self.user_key,
            "title": title,
            "message": message,
            "priority": priority,
        }

        if sound:
            payload["sound"] = sound

        try:
            response = requests.post(PUSHOVER_API_URL, data=payload, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Pushover error: {e}")
            return False

    def should_notify(self, key, cooldown_minutes=5):
        """Check if we should send notification (cooldown check)."""
        now = datetime.now()
        last = self._last_notifications.get(key)

        if last and (now - last) < timedelta(minutes=cooldown_minutes):
            return False

        self._last_notifications[key] = now
        return True


class AlertManager:
    """Manage sensor alerts and notifications."""

    def __init__(self, config_path, notifier=None):
        self.config_path = Path(config_path)
        self.notifier = notifier
        self.alerts = self._load_config()
        self._previous_states = {}

    @property
    def enabled(self):
        """Check if alerts are enabled (notifier configured)."""
        return self.notifier is not None and self.notifier.enabled

    def _load_config(self):
        """Load alert configuration."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {"sensors": []}

    def save_config(self):
        """Save alert configuration."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.alerts, f, indent=2)

    def add_alert(self, sensor_name, alert_type, condition, **kwargs):
        """Add an alert rule for a sensor.

        Alert types:
            - presence: Notify on motion detected
            - temperature: Notify when temp crosses threshold
            - battery: Notify when battery is low
            - offline: Notify when sensor goes offline

        Example:
            add_alert("Living Room Motion", "presence", "detected", cooldown=10)
            add_alert("Bedroom Temp", "temperature", "above", threshold=25)
            add_alert("Front Door", "battery", "below", threshold=20)
        """
        alert = {
            "sensor_name": sensor_name,
            "type": alert_type,
            "condition": condition,
            "enabled": True,
            **kwargs
        }
        self.alerts["sensors"].append(alert)
        self.save_config()

    def remove_alert(self, sensor_name):
        """Remove all alerts for a sensor."""
        self.alerts["sensors"] = [
            a for a in self.alerts["sensors"]
            if a.get("sensor_name") != sensor_name
        ]
        self.save_config()

    def check_sensor(self, sensor):
        """Check a sensor against configured alerts."""
        if not self.enabled:
            return

        name = sensor.get("name")
        sensor_id = sensor.get("id")

        for alert in self.alerts.get("sensors", []):
            if not alert.get("enabled"):
                continue

            if alert.get("sensor_name") != name:
                continue

            alert_type = alert.get("type")
            condition = alert.get("condition")
            cooldown = alert.get("cooldown", 5)

            notification_key = f"{sensor_id}_{alert_type}"

            # Check presence alerts
            if alert_type == "presence":
                presence = sensor.get("presence")
                prev_presence = self._previous_states.get(f"{sensor_id}_presence")

                if condition == "detected" and presence:
                    # Only alert on state change (was not present, now present)
                    if prev_presence is not True:
                        if self.notifier.should_notify(notification_key, cooldown):
                            from datetime import datetime
                            time_str = datetime.now().strftime("%H:%M:%S")
                            self.notifier.send(
                                "Motion Detected",
                                f"{name} at {time_str}",
                                priority=alert.get("priority", 0),
                                sound=alert.get("sound", "pushover")
                            )
                            print(f"  >> Alert sent: {name} motion detected")

                elif condition == "cleared" and not presence and prev_presence:
                    if self.notifier.should_notify(notification_key, cooldown):
                        self.notifier.send(
                            "Motion Cleared",
                            f"No motion at {name}",
                            priority=alert.get("priority", -1)
                        )

                self._previous_states[f"{sensor_id}_presence"] = presence

            # Check temperature alerts
            elif alert_type == "temperature":
                temp = sensor.get("temperature")
                threshold = alert.get("threshold")

                if temp is not None and threshold is not None:
                    if condition == "above" and temp > threshold:
                        if self.notifier.should_notify(notification_key, cooldown):
                            self.notifier.send(
                                "Temperature Alert",
                                f"{name}: {temp:.1f}°C (above {threshold}°C)",
                                priority=alert.get("priority", 0)
                            )
                    elif condition == "below" and temp < threshold:
                        if self.notifier.should_notify(notification_key, cooldown):
                            self.notifier.send(
                                "Temperature Alert",
                                f"{name}: {temp:.1f}°C (below {threshold}°C)",
                                priority=alert.get("priority", 0)
                            )

            # Check battery alerts
            elif alert_type == "battery":
                battery = sensor.get("battery")
                threshold = alert.get("threshold", 20)

                if battery is not None and battery < threshold:
                    if self.notifier.should_notify(notification_key, cooldown_minutes=60):
                        self.notifier.send(
                            "Low Battery",
                            f"{name}: Battery at {battery}%",
                            priority=alert.get("priority", 0)
                        )

            # Check offline alerts
            elif alert_type == "offline":
                reachable = sensor.get("reachable")
                prev_reachable = self._previous_states.get(f"{sensor_id}_reachable")

                if not reachable and prev_reachable:
                    if self.notifier.should_notify(notification_key, cooldown):
                        self.notifier.send(
                            "Sensor Offline",
                            f"{name} is no longer reachable",
                            priority=alert.get("priority", 1)
                        )

                self._previous_states[f"{sensor_id}_reachable"] = reachable

    def check_all(self, sensors):
        """Check all sensors against alerts."""
        for sensor in sensors:
            self.check_sensor(sensor)
