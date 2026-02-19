#!/usr/bin/env python3
"""Hue Sensor Logger - Main application."""

import argparse
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from app.bridge import HueBridge
from app.sensors import SensorReader
from app.logger import SensorLogger
from app.notifications import PushoverNotifier, AlertManager
from app.eventstream import HueEventStream

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs" / "sensors"


def load_settings():
    """Load application settings."""
    settings_path = CONFIG_DIR / "settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            return json.load(f)
    return {}


def save_settings(settings):
    """Save application settings."""
    settings_path = CONFIG_DIR / "settings.json"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def print_sensors(sensors):
    """Print sensor data to console."""
    print(f"\n{'='*60}")
    print(f"SENSORS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    if not sensors:
        print("No sensors found.")
        return

    # Group by category
    by_category = {}
    for sensor in sensors:
        cat = sensor.get("category", "other")
        by_category.setdefault(cat, []).append(sensor)

    for category, cat_sensors in sorted(by_category.items()):
        print(f"\n--- {category.upper()} ({len(cat_sensors)}) ---")

        for s in cat_sensors:
            status = []

            if s.get("battery") is not None:
                status.append(f"bat:{s['battery']}%")

            if category == "motion":
                status.append("MOTION" if s.get("presence") else "clear")
            elif category == "temperature":
                temp = s.get("temperature")
                if temp:
                    status.append(f"{temp:.1f}°C")
            elif category == "light":
                status.append(f"lux:{s.get('light_level')}")
            elif category == "daylight":
                status.append("DAY" if s.get("daylight") else "NIGHT")

            status_str = " | ".join(status) if status else ""
            print(f"  [{s['id']:>2}] {s['name']:<30} {status_str}")


def run_once(bridge, logger, alert_manager, verbose=True, log_categories=None):
    """Run a single sensor read cycle.

    Args:
        log_categories: List of sensor categories to log (default: ['motion'])
    """
    if log_categories is None:
        log_categories = ['motion']

    reader = SensorReader(bridge)
    sensors = reader.read()

    if verbose:
        print_sensors(sensors)

    # Log only specified sensor categories
    for sensor in sensors:
        if sensor.get("category") in log_categories:
            logger.log_sensor(sensor)

    # Check alerts
    if alert_manager:
        alert_manager.check_all(sensors)

    return sensors


def run_monitor(bridge, logger, alert_manager, interval=30, log_categories=None):
    """Run continuous monitoring."""
    if log_categories is None:
        log_categories = ['motion']

    print(f"\nStarting continuous monitoring (interval: {interval}s)")
    print(f"Logging categories: {', '.join(log_categories)}")
    print("Press Ctrl+C to stop\n")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\nStopping monitor...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    while running:
        try:
            run_once(bridge, logger, alert_manager, verbose=True, log_categories=log_categories)
            print(f"\nNext poll in {interval}s...")

            # Sleep in small increments to allow quick exit
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

    print("Monitor stopped.")


def cmd_list_sensors(bridge):
    """List all sensors."""
    reader = SensorReader(bridge)
    sensors = reader.read()
    print_sensors(sensors)


def cmd_list_alerts():
    """List configured alerts."""
    alerts_path = CONFIG_DIR / "alerts.json"
    if not alerts_path.exists():
        print("No alerts configured.")
        return

    with open(alerts_path) as f:
        alerts = json.load(f)

    print("\nConfigured Alerts:")
    print("-" * 50)

    for alert in alerts.get("sensors", []):
        status = "ON" if alert.get("enabled") else "OFF"
        print(f"  [{status}] {alert.get('sensor_name')}")
        print(f"       Type: {alert.get('type')} | Condition: {alert.get('condition')}")
        if alert.get("threshold"):
            print(f"       Threshold: {alert.get('threshold')}")
        print()


def cmd_show_logs():
    """Show logged sensors."""
    logger = SensorLogger(LOGS_DIR)
    sensors = logger.list_sensors()

    if not sensors:
        print("No sensor logs found.")
        return

    print("\nLogged Sensors:")
    print("-" * 50)

    for s in sensors:
        print(f"  {s.get('category')}/{s.get('name')} - {s.get('readings_count')} readings")


def run_stream(bridge, logger, notifier):
    """Run real-time event stream monitoring."""
    print("\nStarting real-time event stream...")

    stream = HueEventStream(bridge.ip, bridge.api_key)

    def on_motion(sensor_name, motion_detected, timestamp):
        time_str = timestamp.strftime("%H:%M:%S")
        date_str = timestamp.strftime("%Y-%m-%d")

        if motion_detected:
            # Print prominent motion detection message
            print(f"\n{'='*60}")
            print(f"🔔 MOTION DETECTED: {sensor_name}")
            print(f"   Time: {time_str} | Date: {date_str}")
            print(f"{'='*60}\n")

            # Log the motion event
            sensor_data = {
                "name": sensor_name,
                "category": "motion",
                "presence": True,
                "timestamp": timestamp.isoformat(),
            }
            logger.log_sensor(sensor_data)

            # Send notification
            if notifier and notifier.enabled:
                notifier.send(
                    "Motion Detected",
                    f"{sensor_name} at {time_str}",
                    priority=0,
                    sound="pushover"
                )
                print(f"  >> Pushover alert sent")
        else:
            # Print motion cleared (less prominent)
            print(f"  [{time_str}] {sensor_name}: clear")

    stream.listen(on_motion)


def main():
    parser = argparse.ArgumentParser(description="Hue Sensor Logger")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "monitor", "stream", "list", "alerts", "logs", "web"],
                        help="Command to execute (web = dashboard, stream = real-time)")
    parser.add_argument("-i", "--interval", type=int, default=30,
                        help="Polling interval in seconds (default: 30)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress console output")
    parser.add_argument("--host", type=str, default=None,
                        help="Web server host (default: from settings.json or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None,
                        help="Web server port (default: from settings.json or 8080)")
    parser.add_argument("--log", type=str, default="motion",
                        help="Sensor categories to log: motion,temperature,light,switch,daylight (default: motion)")

    args = parser.parse_args()

    # Parse logging categories
    log_categories = [cat.strip() for cat in args.log.split(",")]

    # Load settings
    settings = load_settings()

    # Initialize bridge
    bridge = HueBridge(CONFIG_DIR / "settings.json")

    # Handle non-connection commands first
    if args.command == "web":
        from app.web import start_server
        start_server(host=args.host, port=args.port)
        return

    if args.command == "alerts":
        cmd_list_alerts()
        return

    if args.command == "logs":
        cmd_show_logs()
        return

    # Connect to bridge
    if not bridge.connect():
        print("Failed to connect to Hue Bridge.")
        sys.exit(1)

    # Initialize components
    logger = SensorLogger(LOGS_DIR)

    # Initialize notifications (optional)
    pushover_config = settings.get("pushover", {})
    notifier = PushoverNotifier(
        pushover_config.get("user_key"),
        pushover_config.get("api_token")
    )
    alert_manager = AlertManager(CONFIG_DIR / "alerts.json", notifier)

    if notifier.enabled:
        print("Pushover notifications: enabled")
    else:
        print("Pushover notifications: disabled (configure in config/settings.json)")

    # Execute command
    if args.command == "list":
        cmd_list_sensors(bridge)

    elif args.command == "run":
        run_once(bridge, logger, alert_manager, verbose=not args.quiet, log_categories=log_categories)
        print(f"\nLogs saved to: logs/sensors/<category>/<sensor_name>.json")
        print(f"Logged categories: {', '.join(log_categories)}")

    elif args.command == "monitor":
        interval = args.interval or settings.get("polling_interval", 30)
        run_monitor(bridge, logger, alert_manager, interval, log_categories=log_categories)

    elif args.command == "stream":
        run_stream(bridge, logger, notifier)


if __name__ == "__main__":
    main()
