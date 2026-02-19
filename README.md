# HueMonitor

Real-time Philips Hue monitoring dashboard with sensor tracking, light control, and push notifications.

## Features

- **Web Dashboard** — Real-time sensor and light monitoring via WebSocket
- **Light Control** — Toggle Hue lights on/off from the dashboard
- **Setup Wizard** — Browser-based configuration when no settings exist
- **Real-time Events** — Instant motion detection via Hue Event Stream API
- **Push Notifications** — Pushover alerts on motion detection (optional)
- **Auto-generated Alerts** — Alert rules created from discovered motion sensors on first run
- **CLI Tools** — Sensor listing, monitoring, streaming, and logging from the command line
- **Stats Dashboard** — Uptime, event counts, per-sensor breakdown, system status
- **Synology NAS Support** — Ready for deployment on Synology NAS

## Quick Start

### Requirements

- Python 3.8+
- Philips Hue Bridge on the same network

### Install

```bash
pip install -r requirements.txt
```

### Run the Web Dashboard

```bash
python main.py web
```

Open your browser at the configured port (default `http://localhost:8080`, or as set in `config/settings.json`). If no configuration exists, the **setup wizard** will guide you through connecting to your Hue Bridge.

## Web Dashboard

The dashboard has five tabs:

- **Sensors** — Motion, temperature sensors with real-time activity log sidebar
- **Lights** — All Hue lights with on/off toggle switches
- **Other** — Switches, daylight sensors, and other devices
- **Stats** — Server uptime, motion event counts, per-sensor breakdown, notifications sent, system info
- **Settings** — Pushover config, API key management, server host/port/polling, restart

All data updates in real-time via WebSocket — no manual refresh needed.

### Setup Wizard

When `config/settings.json` doesn't exist, the dashboard shows a step-by-step setup wizard:

1. **Bridge IP** — Enter manually or click "Discover" to auto-detect
2. **API Key** — Press the link button on your bridge, then click "Generate" (polls for 30 seconds)
3. **Pushover** (optional) — Configure push notification keys, or skip
4. **Test & Save** — Verify the connection and save

After saving, restart the server to connect. You can also access the setup wizard at `/setup` and the dashboard at `/dashboard` directly.

### Settings Tab

- **Pushover** — Add/change push notification keys (masked by default), send a test notification
- **API Key** — Generate a new Hue Bridge API key (press bridge link button first)
- **Server Config** — Change host, port, and polling interval (saved to `settings.json`)
- **Restart** — Restart the server from the browser after configuration changes

## CLI Commands

```bash
python main.py web                  # Start web dashboard (recommended)
python main.py stream               # Real-time motion stream (CLI)
python main.py monitor -i 10        # Poll every 10 seconds
python main.py run                  # Single sensor read
python main.py list                 # Show all sensor values
python main.py alerts               # Show configured alerts
python main.py logs                 # Show logged sensors
```

### Logging Options

By default, only motion sensors are logged. Control what gets logged:

```bash
python main.py run --log "motion,temperature"
python main.py run --log "motion,temperature,light,switch,daylight"
```

## Configuration

### config/settings.json

Created automatically by the setup wizard, or manually:

```json
{
  "bridge_ip": "192.168.1.100",
  "api_key": "your-hue-api-key",
  "pushover": {
    "user_key": "your-pushover-user-key",
    "api_token": "your-pushover-api-token"
  },
  "polling_interval": 30,
  "web": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

### config/alerts.json

Auto-generated from discovered motion sensors on first startup (all disabled by default). Use the dashboard toggles to enable/disable notifications per sensor, or edit manually:

```json
{
  "sensors": [
    {
      "sensor_name": "Kitchen",
      "type": "presence",
      "condition": "detected",
      "cooldown": 1,
      "priority": 0,
      "sound": "pushover",
      "enabled": true
    }
  ]
}
```

**Priority levels:** `-2` silent, `-1` low, `0` normal, `1` high, `2` emergency

## Project Structure

```
HueMonitor/
├── app/
│   ├── bridge.py           # Hue Bridge connection
│   ├── sensors.py          # Sensor reading & parsing
│   ├── lights.py           # Light reading & control
│   ├── logger.py           # Organized logging
│   ├── notifications.py    # Pushover alerts & alert manager
│   ├── eventstream.py      # Real-time event stream (SSE)
│   └── web.py              # FastAPI web server & WebSocket
├── static/
│   ├── index.html          # Dashboard (single-page app)
│   └── setup.html          # Setup wizard
├── config/
│   ├── settings.json       # Bridge IP, API key, Pushover creds
│   └── alerts.json         # Alert rules (auto-generated)
├── logs/sensors/            # Sensor data logs by category
├── main.py                 # CLI entry point
├── start.sh                # Service management script (Synology/Linux)
├── requirements.txt
└── README.md
```

## Synology NAS Deployment

Use `start.sh` to manage HueMonitor as a service:

```bash
./start.sh start     # Start in background
./start.sh stop      # Stop the server
./start.sh restart   # Restart
./start.sh status    # Check if running
```

For auto-start on boot: **Control Panel > Task Scheduler > Triggered Task > Boot-up**, set the command to `/path/to/HueMonitor/start.sh start`.

Host and port are read from `config/settings.json`. Override with env vars: `HUE_HOST=0.0.0.0 HUE_PORT=9090 ./start.sh start`.

## Troubleshooting

- **Dashboard won't load** — Check that Python 3 and dependencies are installed. View `huemonitor.log` for errors.
- **No sensor data** — Verify `bridge_ip` and `api_key` in `config/settings.json`. Ensure the device can reach the Hue Bridge.
- **No push notifications** — Verify Pushover keys in Settings tab. Check that alerts are enabled in the dashboard.
- **Setup wizard shows after setup** — The setup wizard appears when `config/settings.json` is missing or incomplete. If config exists, click "Go to Dashboard".

## License

MIT
