#!/usr/bin/env sh
# HueMonitor - Synology NAS startup script
# Add this to Task Scheduler: Control Panel > Task Scheduler > Triggered Task > Boot-up

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/huemonitor.log"
PID_FILE="$SCRIPT_DIR/huemonitor.pid"

# Host/port: env var > settings.json > defaults
# When not overridden, main.py reads from settings.json automatically
HOST="${HUE_HOST:-}"
PORT="${HUE_PORT:-}"

case "${1:-start}" in
  start)
    # Stop existing instance if running
    if [ -f "$PID_FILE" ]; then
      OLD_PID=$(cat "$PID_FILE")
      if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing instance (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 2
      fi
      rm -f "$PID_FILE"
    fi

    cd "$SCRIPT_DIR"

    # Install/update dependencies if needed
    python3 -c "import fastapi, uvicorn" 2>/dev/null || {
      echo "Installing dependencies..."
      python3 -m pip install -r requirements.txt --quiet
    }

    # Build command with optional host/port overrides
    CMD="python3 main.py web"
    [ -n "$HOST" ] && CMD="$CMD --host $HOST"
    [ -n "$PORT" ] && CMD="$CMD --port $PORT"

    echo "Starting HueMonitor..."
    $CMD >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Started (PID $(cat "$PID_FILE")). Log: $LOG_FILE"
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping HueMonitor (PID $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Stopped."
      else
        echo "Process not running. Cleaning up PID file."
        rm -f "$PID_FILE"
      fi
    else
      echo "No PID file found. Not running?"
    fi
    ;;

  restart)
    "$0" stop
    sleep 2
    "$0" start
    ;;

  status)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "HueMonitor is running (PID $PID)"
      else
        echo "PID file exists but process is not running"
      fi
    else
      echo "HueMonitor is not running"
    fi
    ;;

  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
