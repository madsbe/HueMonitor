"""FastAPI web server with WebSocket for real-time sensor monitoring."""

import asyncio
import json
import requests
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse

# Dashboard password — required before any changes are allowed
DASHBOARD_PASSWORD = "SolInc2027"

from app.bridge import HueBridge
from app.sensors import SensorReader
from app.lights import LightReader
from app.logger import SensorLogger
from app.notifications import PushoverNotifier, AlertManager
from app.eventstream import HueEventStream

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs" / "sensors"
STATIC_DIR = BASE_DIR / "static"


class SensorState:
    """Thread-safe in-memory state for sensors, lights, and events."""

    def __init__(self):
        self.sensors: dict = {}  # Current sensor states by id
        self.lights: dict = {}   # Current light states by id
        self.events: deque = deque(maxlen=100)  # Recent motion events
        self._lock = threading.Lock()
        # Runtime stats
        self.startup_time: datetime = datetime.now()
        self.total_events: int = 0
        self.events_by_sensor: dict = {}
        self.notifications_sent: int = 0
        self.last_poll_time: datetime = None
        self.poll_count: int = 0

    def update_sensors(self, sensors: list):
        with self._lock:
            for sensor in sensors:
                self.sensors[sensor["id"]] = sensor

    def update_lights(self, lights: list):
        with self._lock:
            for light in lights:
                self.lights[light["id"]] = light

    def add_event(self, event: dict):
        with self._lock:
            self.events.appendleft(event)
            self.total_events += 1
            name = event.get("sensor_name", "unknown")
            self.events_by_sensor[name] = self.events_by_sensor.get(name, 0) + 1

    def get_sensors(self) -> list:
        with self._lock:
            return list(self.sensors.values())

    def get_lights(self) -> list:
        with self._lock:
            return list(self.lights.values())

    def get_events(self) -> list:
        with self._lock:
            return list(self.events)


class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Globals
state = SensorState()
ws_manager = ConnectionManager()
_loop: asyncio.AbstractEventLoop = None
_shutdown_event = threading.Event()


def _load_settings():
    settings_path = CONFIG_DIR / "settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            return json.load(f)
    return {}


def _has_required_settings():
    """Check if settings file has required bridge_ip and api_key."""
    settings_path = CONFIG_DIR / "settings.json"
    if not settings_path.exists():
        return False
    try:
        with open(settings_path) as f:
            s = json.load(f)
        return bool(s.get("bridge_ip")) and bool(s.get("api_key"))
    except (json.JSONDecodeError, IOError):
        return False


def _check_password(request_or_payload, payload=None):
    """Check the X-Dashboard-Password header. Returns error response or None if OK."""
    if isinstance(request_or_payload, Request):
        pw = request_or_payload.headers.get("X-Dashboard-Password", "")
    elif isinstance(request_or_payload, dict):
        pw = request_or_payload.get("_password", "")
    else:
        pw = ""
    if payload and isinstance(payload, dict):
        pw = pw or payload.get("_password", "")
    if pw != DASHBOARD_PASSWORD:
        return JSONResponse({"error": "Invalid password"}, status_code=403)
    return None


def _run_event_stream(bridge_ip, api_key, logger, notifier, alert_manager):
    """Run event stream listener in a background thread."""
    stream = HueEventStream(bridge_ip, api_key)

    def on_motion(sensor_name, motion_detected, timestamp):
        time_str = timestamp.strftime("%H:%M:%S")

        event = {
            "sensor_name": sensor_name,
            "motion": motion_detected,
            "timestamp": timestamp.isoformat(),
            "time": time_str,
        }
        state.add_event(event)

        if motion_detected:
            # Log the motion event
            sensor_data = {
                "name": sensor_name,
                "category": "motion",
                "presence": True,
                "timestamp": timestamp.isoformat(),
            }
            logger.log_sensor(sensor_data)

            # Send push notification only if alert is enabled for this sensor
            if notifier and notifier.enabled:
                alert_manager.alerts = alert_manager._load_config()
                alert_cfg = next(
                    (a for a in alert_manager.alerts.get("sensors", [])
                     if a.get("sensor_name") == sensor_name),
                    None,
                )
                if alert_cfg and alert_cfg.get("enabled", True):
                    cooldown = alert_cfg.get("cooldown", 5)
                    if notifier.should_notify(f"event_{sensor_name}", cooldown):
                        if notifier.send(
                            "Motion Detected",
                            f"{sensor_name} at {time_str}",
                            priority=alert_cfg.get("priority", 0),
                            sound=alert_cfg.get("sound", "pushover"),
                        ):
                            state.notifications_sent += 1

        # Schedule broadcast to WebSocket clients
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast({"type": "motion_event", "data": event}),
                _loop,
            )

    while not _shutdown_event.is_set():
        try:
            stream.listen(on_motion)
        except Exception as e:
            print(f"Event stream error: {e}, reconnecting in 5s...")
            _shutdown_event.wait(5)


async def _poll_sensors(bridge, logger, alert_manager, interval):
    """Periodically poll all sensors and lights, broadcast updates."""
    sensor_reader = SensorReader(bridge)
    light_reader = LightReader(bridge)

    while not _shutdown_event.is_set():
        try:
            # Poll sensors
            sensors = sensor_reader.read()
            state.update_sensors(sensors)

            # Log and check alerts
            for sensor in sensors:
                if sensor.get("category") in ("motion", "temperature"):
                    logger.log_sensor(sensor)
            if alert_manager:
                alert_manager.check_all(sensors)

            # Poll lights
            lights = light_reader.read()
            state.update_lights(lights)

            # Update poll stats
            state.last_poll_time = datetime.now()
            state.poll_count += 1

            # Broadcast to WebSocket clients
            await ws_manager.broadcast({
                "type": "sensor_update",
                "data": _group_sensors(sensors),
            })
            await ws_manager.broadcast({
                "type": "lights_update",
                "data": lights,
            })

        except Exception as e:
            print(f"Poll error: {e}")

        await asyncio.sleep(interval)


def _group_sensors(sensors):
    """Group sensors by category for API responses."""
    grouped = {}
    for s in sensors:
        cat = s.get("category", "other")
        grouped.setdefault(cat, []).append(s)
    return grouped


def create_app():
    """Create and configure the FastAPI application."""
    settings = _load_settings()
    bridge = HueBridge(CONFIG_DIR / "settings.json")

    pushover_config = settings.get("pushover", {})
    notifier = PushoverNotifier(
        pushover_config.get("user_key"),
        pushover_config.get("api_token"),
    )
    alert_manager = AlertManager(CONFIG_DIR / "alerts.json", notifier)
    logger = SensorLogger(LOGS_DIR)

    polling_interval = settings.get("polling_interval", 30)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _loop
        _loop = asyncio.get_running_loop()
        _shutdown_event.clear()
        poll_task = None

        if _has_required_settings():
            # Connect to bridge
            if not bridge.connect():
                print("WARNING: Could not connect to Hue Bridge")

            # Auto-generate alerts.json from motion sensors if it doesn't exist
            if not (CONFIG_DIR / "alerts.json").exists():
                try:
                    reader = SensorReader(bridge)
                    sensors = reader.read()
                    motion = [s for s in sensors if s.get("category") == "motion"]
                    if motion:
                        alerts_config = {"sensors": []}
                        for s in motion:
                            alerts_config["sensors"].append({
                                "sensor_name": s["name"],
                                "type": "presence",
                                "condition": "detected",
                                "cooldown": 1,
                                "priority": 0,
                                "sound": "pushover",
                                "enabled": False,
                            })
                        alert_manager.alerts = alerts_config
                        alert_manager.save_config()
                        print(f"Auto-generated alerts.json with {len(motion)} motion sensors")
                except Exception as e:
                    print(f"Could not auto-generate alerts: {e}")

            # Start event stream in background thread
            stream_thread = threading.Thread(
                target=_run_event_stream,
                args=(bridge.ip, bridge.api_key, logger, notifier, alert_manager),
                daemon=True,
            )
            stream_thread.start()

            # Start periodic poller
            poll_task = asyncio.create_task(
                _poll_sensors(bridge, logger, alert_manager, polling_interval)
            )

            print("HueMonitor web dashboard running")
            print(f"Pushover notifications: {'enabled' if notifier.enabled else 'disabled'}")
        else:
            print("No configuration found. Setup wizard available at /")

        yield

        # Cleanup
        _shutdown_event.set()
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="HueMonitor", lifespan=lifespan)

    # --- Routes ---

    @app.post("/api/auth/verify")
    async def verify_password(request: Request):
        """Verify the dashboard password."""
        body = await request.json()
        pw = body.get("password", "")
        if pw == DASHBOARD_PASSWORD:
            return {"success": True}
        return JSONResponse({"success": False, "error": "Invalid password"}, status_code=403)

    @app.get("/")
    async def root():
        if not _has_required_settings():
            return FileResponse(STATIC_DIR / "setup.html")
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/dashboard")
    async def dashboard():
        """Always serve the dashboard (skip setup check)."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/setup")
    async def setup_page():
        """Always serve the setup wizard."""
        return FileResponse(STATIC_DIR / "setup.html")

    @app.get("/api/sensors")
    async def get_sensors():
        sensors = state.get_sensors()
        return _group_sensors(sensors)

    @app.get("/api/history/{category}/{name}")
    async def get_history(category: str, name: str, limit: int = 100):
        history = logger.get_sensor_history(category, name, limit=limit)
        return history

    @app.get("/api/alerts")
    async def get_alerts():
        # Re-read from disk to stay in sync
        alert_manager.alerts = alert_manager._load_config()
        result = dict(alert_manager.alerts)
        result["pushover_enabled"] = notifier.enabled
        return result

    @app.post("/api/alerts/toggle/{sensor_name}")
    async def toggle_alert(sensor_name: str, request: Request):
        """Toggle the enabled state of an alert by sensor name."""
        err = _check_password(request)
        if err:
            return err
        alert_manager.alerts = alert_manager._load_config()
        found = False
        new_state = None
        for alert in alert_manager.alerts.get("sensors", []):
            if alert.get("sensor_name") == sensor_name:
                alert["enabled"] = not alert.get("enabled", True)
                new_state = alert["enabled"]
                found = True
        if not found:
            return JSONResponse({"error": "Alert not found"}, status_code=404)
        alert_manager.save_config()
        # Broadcast updated alerts to all clients
        await ws_manager.broadcast({
            "type": "alerts_update",
            "data": alert_manager.alerts,
        })
        return {"sensor_name": sensor_name, "enabled": new_state}

    @app.get("/api/lights")
    async def get_lights():
        return state.get_lights()

    @app.post("/api/lights/{light_id}/toggle")
    async def toggle_light(light_id: str, request: Request):
        """Toggle a light on/off."""
        err = _check_password(request)
        if err:
            return err
        light_reader = LightReader(bridge)
        new_on = light_reader.toggle(light_id)
        if new_on is None:
            return JSONResponse({"error": "Light not found"}, status_code=404)

        # Re-read all lights and update state
        lights = light_reader.read()
        state.update_lights(lights)

        # Broadcast updated lights to all clients
        await ws_manager.broadcast({
            "type": "lights_update",
            "data": lights,
        })

        return {"light_id": light_id, "on": new_on}

    @app.get("/api/events")
    async def get_events():
        return state.get_events()

    @app.get("/api/stats")
    async def get_stats():
        """Get runtime statistics."""
        now = datetime.now()
        uptime = (now - state.startup_time).total_seconds()
        return {
            "started_at": state.startup_time.isoformat(),
            "uptime_seconds": int(uptime),
            "total_events": state.total_events,
            "events_by_sensor": dict(state.events_by_sensor),
            "notifications_sent": state.notifications_sent,
            "last_poll": state.last_poll_time.isoformat() if state.last_poll_time else None,
            "poll_count": state.poll_count,
            "connected_clients": len(ws_manager.active),
            "sensor_count": len(state.sensors),
            "light_count": len(state.lights),
            "bridge_connected": bridge.connected if hasattr(bridge, 'connected') else _has_required_settings(),
            "pushover_enabled": notifier.enabled,
            "polling_interval": polling_interval,
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            # Send initial state
            sensors = state.get_sensors()
            await websocket.send_json({
                "type": "sensor_update",
                "data": _group_sensors(sensors),
            })
            await websocket.send_json({
                "type": "lights_update",
                "data": state.get_lights(),
            })
            await websocket.send_json({
                "type": "events_init",
                "data": state.get_events(),
            })

            # Keep connection alive, listen for pings
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception:
            ws_manager.disconnect(websocket)

    # --- Settings Endpoints ---

    @app.get("/api/settings")
    async def get_settings():
        """Get current settings (API key masked)."""
        s = _load_settings()
        key = s.get("api_key", "")
        pushover = s.get("pushover", {})
        web = s.get("web", {})
        def _mask(val):
            if len(val) > 8:
                return val[:4] + "..." + val[-4:]
            return val

        pu_key = pushover.get("user_key", "")
        pu_token = pushover.get("api_token", "")
        return {
            "bridge_ip": s.get("bridge_ip", ""),
            "api_key_masked": (key[:6] + "..." + key[-4:]) if len(key) > 10 else key,
            "api_key": key,
            "polling_interval": s.get("polling_interval", 30),
            "web_host": web.get("host", "0.0.0.0"),
            "web_port": web.get("port", 8008),
            "pushover_user_key": pu_key,
            "pushover_user_key_masked": _mask(pu_key) if pu_key else "",
            "pushover_api_token": pu_token,
            "pushover_api_token_masked": _mask(pu_token) if pu_token else "",
            "pushover_enabled": notifier.enabled,
        }

    @app.post("/api/settings/pushover")
    async def save_pushover(request: Request):
        """Save Pushover configuration."""
        err = _check_password(request)
        if err:
            return err
        payload = await request.json()
        user_key = payload.get("user_key", "").strip()
        api_token = payload.get("api_token", "").strip()

        # Update settings.json
        s = _load_settings()
        if user_key and api_token:
            s["pushover"] = {"user_key": user_key, "api_token": api_token}
        else:
            s.pop("pushover", None)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_DIR / "settings.json", "w") as f:
            json.dump(s, f, indent=2)

        # Update the live notifier
        notifier.user_key = user_key or None
        notifier.api_token = api_token or None

        return {"success": True, "enabled": notifier.enabled}

    @app.post("/api/settings/server")
    async def save_server_settings(request: Request):
        """Save web server host, port, and polling interval."""
        err = _check_password(request)
        if err:
            return err
        payload = await request.json()
        s = _load_settings()
        host = payload.get("host", "").strip()
        port = payload.get("port")
        poll = payload.get("polling_interval")

        if host:
            s.setdefault("web", {})["host"] = host
        if port is not None:
            s.setdefault("web", {})["port"] = int(port)
        if poll is not None:
            s["polling_interval"] = int(poll)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_DIR / "settings.json", "w") as f:
            json.dump(s, f, indent=2)

        return {"success": True, "message": "Server settings saved. Restart to apply."}

    @app.post("/api/settings/pushover/test")
    async def test_pushover(request: Request):
        """Send a test Pushover notification."""
        err = _check_password(request)
        if err:
            return err
        payload = await request.json()
        user_key = payload.get("user_key", "").strip()
        api_token = payload.get("api_token", "").strip()
        if not user_key or not api_token:
            return {"success": False, "error": "User key and API token are required"}
        try:
            resp = requests.post("https://api.pushover.net/1/messages.json", data={
                "token": api_token,
                "user": user_key,
                "title": "HueMonitor Test",
                "message": "Push notifications are working!",
            }, timeout=10)
            resp.raise_for_status()
            return {"success": True}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/settings/generate-key")
    async def generate_api_key(request: Request):
        """Generate a new API key from the Hue Bridge.

        The user must press the link button on the bridge first.
        """
        err = _check_password(request)
        if err:
            return err
        payload = await request.json()
        bridge_ip = payload.get("bridge_ip", "").strip()
        if not bridge_ip:
            # Use current config
            bridge_ip = _load_settings().get("bridge_ip", "")
        if not bridge_ip:
            return {"success": False, "error": "No bridge IP configured"}
        try:
            url = f"http://{bridge_ip}/api"
            resp = requests.post(url, json={"devicetype": "HueMonitor#setup"}, timeout=10)
            result = resp.json()
            if isinstance(result, list) and result:
                if "success" in result[0]:
                    api_key = result[0]["success"]["username"]
                    # Save to settings.json
                    s = _load_settings()
                    s["bridge_ip"] = bridge_ip
                    s["api_key"] = api_key
                    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                    with open(CONFIG_DIR / "settings.json", "w") as f:
                        json.dump(s, f, indent=2)
                    return {"success": True, "api_key": api_key}
                elif "error" in result[0]:
                    desc = result[0]["error"].get("description", "Unknown error")
                    return {"success": False, "error": desc}
            return {"success": False, "error": "Unexpected response from bridge"}
        except requests.RequestException as e:
            return {"success": False, "error": f"Connection failed: {e}"}

    @app.post("/api/restart")
    async def restart_server_endpoint(request: Request):
        """Restart the HueMonitor server process."""
        err = _check_password(request)
        if err:
            return err
        import os
        import sys
        import signal
        import subprocess

        async def _restart():
            await asyncio.sleep(0.5)
            try:
                # Spawn new server process (detached, waits for port to free)
                cmd = [sys.executable] + sys.argv
                env = os.environ.copy()
                env["_HUE_RESTART_DELAY"] = "2"
                subprocess.Popen(cmd, start_new_session=True, env=env)
                print(f"Restart: spawned new process, shutting down current...")
            except Exception as e:
                print(f"Restart error: {e}")
                return
            # Kill current process
            os.kill(os.getpid(), signal.SIGTERM)

        asyncio.create_task(_restart())
        return {"success": True, "message": "Restarting..."}

    # --- Setup Wizard Endpoints ---

    @app.get("/api/setup/discover")
    def setup_discover():
        """Auto-discover Hue Bridge on the network."""
        try:
            resp = requests.get("https://discovery.meethue.com", timeout=10)
            resp.raise_for_status()
            bridges = resp.json()
            if bridges:
                return {"success": True, "bridge_ip": bridges[0].get("internalipaddress")}
            return {"success": False, "error": "No bridges found on the network"}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/setup/test")
    def setup_test(payload: dict):
        """Test bridge connection with provided credentials."""
        bridge_ip = payload.get("bridge_ip", "").strip()
        api_key = payload.get("api_key", "").strip()
        if not bridge_ip or not api_key:
            return {"success": False, "error": "Bridge IP and API key are required"}
        try:
            url = f"http://{bridge_ip}/api/{api_key}/config"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if "name" in data:
                return {"success": True, "bridge_name": data["name"], "sw_version": data.get("swversion")}
            if isinstance(data, list) and data and "error" in data[0]:
                return {"success": False, "error": data[0]["error"].get("description", "Unknown error")}
            return {"success": False, "error": "Unexpected response from bridge"}
        except requests.RequestException as e:
            return {"success": False, "error": f"Connection failed: {e}"}

    @app.post("/api/setup/save")
    async def setup_save(request: Request):
        """Save setup configuration."""
        err = _check_password(request)
        if err:
            return err
        payload = await request.json()
        bridge_ip = payload.get("bridge_ip", "").strip()
        api_key = payload.get("api_key", "").strip()
        if not bridge_ip or not api_key:
            return JSONResponse({"success": False, "error": "Bridge IP and API key are required"}, status_code=400)

        settings = {
            "bridge_ip": bridge_ip,
            "api_key": api_key,
            "polling_interval": int(payload.get("polling_interval", 30)),
            "web": {"host": "0.0.0.0", "port": 8008},
        }

        user_key = payload.get("pushover_user_key", "").strip()
        api_token = payload.get("pushover_api_token", "").strip()
        if user_key and api_token:
            settings["pushover"] = {"user_key": user_key, "api_token": api_token}

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_DIR / "settings.json", "w") as f:
            json.dump(settings, f, indent=2)

        return {"success": True, "message": "Configuration saved. Please restart HueMonitor."}

    return app


def start_server(host=None, port=None):
    """Start the web server.

    If host/port are not provided, reads from config/settings.json web section.
    Falls back to 0.0.0.0:8008 if nothing is configured.
    """
    import os
    import time
    import uvicorn

    # If spawned by restart, wait for old process to release the port
    delay = int(os.environ.pop("_HUE_RESTART_DELAY", "0"))
    if delay:
        print(f"Restart: waiting {delay}s for port to free...")
        time.sleep(delay)

    # Read host/port from settings.json if not explicitly provided
    if host is None or port is None:
        try:
            settings_path = CONFIG_DIR / "settings.json"
            if settings_path.exists():
                with open(settings_path) as f:
                    s = json.load(f)
                web = s.get("web", {})
                if host is None:
                    host = web.get("host", "0.0.0.0")
                if port is None:
                    port = web.get("port", 8008)
        except (json.JSONDecodeError, IOError):
            pass

    host = host or "0.0.0.0"
    port = port or 8008

    app = create_app()
    uvicorn.run(app, host=host, port=port)
