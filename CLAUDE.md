# CLAUDE.md

## Project Overview

HueMonitor is a real-time Philips Hue monitoring dashboard built with FastAPI (backend) and vanilla JavaScript (frontend). It provides sensor tracking, light control, and Pushover push notifications.

## Tech Stack

- **Backend:** Python 3.14, FastAPI, Uvicorn, WebSocket
- **Frontend:** Single-page vanilla HTML/CSS/JS (no build step)
- **Deployment:** Synology NAS via `deploy-synology.sh`

## Key Files

- `main.py` — CLI entry point with subcommands (web, stream, monitor, list, etc.)
- `app/web.py` — FastAPI server, all API routes, WebSocket, password auth
- `app/bridge.py` — Hue Bridge connection
- `app/sensors.py` — Sensor reading & parsing
- `app/lights.py` — Light reading & control
- `app/eventstream.py` — Real-time Hue Event Stream (SSE)
- `app/notifications.py` — Pushover alerts & alert manager
- `app/logger.py` — Sensor data logging
- `static/index.html` — Dashboard UI (single-page app, all JS inline)
- `static/setup.html` — Setup wizard (also single-page, all JS inline)
- `config/settings.json` — Runtime config (bridge IP, API key, Pushover, port)
- `config/alerts.json` — Alert rules per sensor (auto-generated)
- `deploy-synology.sh` — One-command deploy to Synology NAS
- `start.sh` — Service management on the NAS

## Architecture

- FastAPI serves static HTML files and provides REST + WebSocket APIs
- Background thread runs Hue Event Stream for instant motion detection
- Async poller periodically reads all sensors and lights
- WebSocket broadcasts updates to all connected dashboard clients
- No database — state is in-memory, config in JSON files, logs in flat files

## Important Details

- Default port: **8008** (configured in `config/settings.json` and code defaults)
- Dashboard password: defined in `app/web.py` as `DASHBOARD_PASSWORD`
- Password protects all write operations (toggle lights/alerts, save settings, restart)
- The version is maintained in two places: `app/__init__.py` and the header span in `static/index.html`
- Synology deployment uses Python at `/usr/local/bin/python3.14`
- Synology deploy path: `/volume1/scripts/HUEMonitor`

## Running Locally

```bash
pip install -r requirements.txt
python main.py web
```

## Deploying to Synology

```bash
./deploy-synology.sh
```

## Commands

```bash
python main.py web          # Start web dashboard
python main.py stream       # CLI motion stream
python main.py list         # List all sensors
python main.py monitor      # Poll and display
```
