#!/bin/bash
# ============================================================================
# HueMonitor → Synology NAS (one-script deploy)
#
# Does everything: sync files, install deps, kill old instance, start app.
# Run from your Mac. Requires SSH access to Synology.
#
# Usage:
#   ./deploy-synology.sh              # Full deploy (sync + start)
#   ./deploy-synology.sh sync         # Quick deploy (sync + restart)
#   ./deploy-synology.sh stop         # Stop the app on Synology
#   ./deploy-synology.sh status       # Check if app is running
#   ./deploy-synology.sh logs         # Tail the app log
#   ./deploy-synology.sh ssh          # Open SSH session to app directory
# ============================================================================

set -e

# ============================================================================
# CONFIGURATION
# ============================================================================
SYNOLOGY_HOST="192.168.200.11"
SYNOLOGY_USER="marc"
SYNOLOGY_PATH="/volume1/scripts/HUEMonitor"
SYNOLOGY_PORT=22
APP_PORT=8008
PYTHON="/usr/local/bin/python3.14"
LOG_FILE="$SYNOLOGY_PATH/huemonitor.log"
PID_FILE="$SYNOLOGY_PATH/huemonitor.pid"

# ============================================================================
# Internals
# ============================================================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH_WRAPPER="/tmp/.huemonitor-ssh-wrapper-$$.sh"

step() { echo -e "${YELLOW}[$1/$2]${NC} $3"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${DIM}$1${NC}"; }

_init_ssh() {
    if ! command -v sshpass > /dev/null 2>&1; then
        fail "sshpass not installed"
        echo "  Install: brew install hudochenkov/sshpass/sshpass"
        exit 1
    fi
    echo -ne "  ${CYAN}Password for ${SYNOLOGY_USER}@${SYNOLOGY_HOST}: ${NC}"
    read -rs SYNOLOGY_PASS
    echo ""
    cat > "$SSH_WRAPPER" <<WRAP
#!/bin/bash
export SSHPASS='${SYNOLOGY_PASS}'
exec sshpass -e ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no -p ${SYNOLOGY_PORT} "\$@"
WRAP
    chmod 700 "$SSH_WRAPPER"
    unset SYNOLOGY_PASS
}

remote() { "$SSH_WRAPPER" ${SYNOLOGY_USER}@${SYNOLOGY_HOST} "$1"; }
cleanup() { rm -f "$SSH_WRAPPER"; }
trap cleanup EXIT

# ============================================================================
# Subcommands
# ============================================================================
case "${1:-deploy}" in
    stop)
        _init_ssh
        echo -e "${CYAN}Stopping HueMonitor on ${SYNOLOGY_HOST}...${NC}"
        remote "
            if [ -f '${PID_FILE}' ]; then
                PID=\$(cat '${PID_FILE}')
                if kill -0 \${PID} 2>/dev/null; then
                    kill \${PID} 2>/dev/null || true
                    sleep 1
                    kill -9 \${PID} 2>/dev/null || true
                    rm -f '${PID_FILE}'
                    echo 'Stopped'
                else
                    rm -f '${PID_FILE}'
                    echo 'PID file stale, cleaned up'
                fi
            else
                PIDS=\$(ps aux 2>/dev/null | grep 'main.py web' | grep -v grep | awk '{print \$2}' || true)
                if [ -n \"\${PIDS}\" ]; then
                    echo \${PIDS} | xargs kill -9 2>/dev/null || true
                    echo 'Stopped (found by process name)'
                else
                    echo 'Not running'
                fi
            fi
        "
        exit 0
        ;;
    status)
        _init_ssh
        echo -e "${CYAN}HueMonitor status on ${SYNOLOGY_HOST}:${NC}"
        remote "
            HTTP_CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost:${APP_PORT}/ 2>/dev/null || echo '000')
            if [ \"\${HTTP_CODE}\" != '000' ]; then
                echo '  Running → http://${SYNOLOGY_HOST}:${APP_PORT}'
            else
                echo '  Not running'
            fi
            if [ -f '${LOG_FILE}' ]; then
                echo ''
                echo '  Last 5 log lines:'
                tail -5 '${LOG_FILE}' 2>/dev/null | sed 's/^/    /'
            fi
        "
        exit 0
        ;;
    logs)
        _init_ssh
        echo -e "${CYAN}Tailing log on ${SYNOLOGY_HOST}...${NC}"
        echo -e "${DIM}(Ctrl+C to stop)${NC}"
        echo ""
        "$SSH_WRAPPER" ${SYNOLOGY_USER}@${SYNOLOGY_HOST} tail -f "${LOG_FILE}"
        exit 0
        ;;
    ssh)
        _init_ssh
        echo -e "${CYAN}Connecting to ${SYNOLOGY_HOST}:${SYNOLOGY_PATH}...${NC}"
        "$SSH_WRAPPER" ${SYNOLOGY_USER}@${SYNOLOGY_HOST} -t "cd '${SYNOLOGY_PATH}' && exec \$SHELL -l"
        exit 0
        ;;
    sync|deploy|"")
        ;;
    --help|-h)
        echo "Usage: $0 [deploy|sync|stop|status|logs|ssh]"
        echo ""
        echo "  deploy   Full deploy: sync + install deps + start (default)"
        echo "  sync     Same as deploy (no build step needed)"
        echo "  stop     Stop the app on Synology"
        echo "  status   Check if running + last log lines"
        echo "  logs     Tail the remote log"
        echo "  ssh      Open SSH session in the app directory"
        exit 0
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo "Run '$0 --help' for usage"
        exit 1
        ;;
esac

# ============================================================================
# DEPLOY
# ============================================================================
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  HueMonitor → Synology Deploy            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

TOTAL_STEPS=5

# --- Step 1: SSH ---
step 1 $TOTAL_STEPS "Testing SSH connection to ${SYNOLOGY_HOST}..."
_init_ssh
if ! "$SSH_WRAPPER" ${SYNOLOGY_USER}@${SYNOLOGY_HOST} "echo ok" > /dev/null 2>&1; then
    fail "Cannot connect to ${SYNOLOGY_USER}@${SYNOLOGY_HOST}:${SYNOLOGY_PORT}"
    exit 1
fi
ok "SSH connection OK"
echo ""

# --- Step 2: Copy files ---
step 2 $TOTAL_STEPS "Copying files to ${SYNOLOGY_HOST}:${SYNOLOGY_PATH}..."
remote "mkdir -p '${SYNOLOGY_PATH}/app' '${SYNOLOGY_PATH}/static' '${SYNOLOGY_PATH}/config'"

tar czf - -C "$SCRIPT_DIR" \
    --exclude='.git' \
    --exclude='.claude' \
    --exclude='*.old' \
    --exclude='.DS_Store' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs' \
    --exclude='huemonitor.log' \
    --exclude='huemonitor.pid' \
    --exclude='deploy-synology.sh' \
    app/ static/ config/ main.py start.sh requirements.txt \
    | "$SSH_WRAPPER" ${SYNOLOGY_USER}@${SYNOLOGY_HOST} "tar xzf - -C '${SYNOLOGY_PATH}'"

ok "Files copied"
echo ""

# --- Step 3: Install dependencies ---
step 3 $TOTAL_STEPS "Installing Python dependencies..."
remote "
    cd '${SYNOLOGY_PATH}'
    echo 'Python version:' && ${PYTHON} --version
    echo 'Installing dependencies...'
    ${PYTHON} -m pip install -r requirements.txt --force-reinstall 2>&1
    echo ''
    echo 'Verifying...'
    ${PYTHON} -c 'from fastapi import FastAPI; import uvicorn; print(\"OK\")' 2>&1
"
ok "Dependencies ready"
echo ""

# --- Step 4: Stop existing instance ---
step 4 $TOTAL_STEPS "Stopping existing instance (if any)..."
remote "
    if [ -f '${PID_FILE}' ]; then
        PID=\$(cat '${PID_FILE}')
        if kill -0 \${PID} 2>/dev/null; then
            kill \${PID} 2>/dev/null || true
            sleep 1
            kill -9 \${PID} 2>/dev/null || true
            echo '  Killed old instance (PID '\${PID}')'
        else
            echo '  No existing instance'
        fi
        rm -f '${PID_FILE}'
    else
        PIDS=\$(ps aux 2>/dev/null | grep 'main.py web' | grep -v grep | awk '{print \$2}' || true)
        if [ -n \"\${PIDS}\" ]; then
            echo \${PIDS} | xargs kill -9 2>/dev/null || true
            echo '  Killed old instance (found by process name)'
        else
            echo '  No existing instance'
        fi
    fi
    sleep 2
"
ok "Clear"
echo ""

# --- Step 5: Start ---
step 5 $TOTAL_STEPS "Starting HueMonitor on port ${APP_PORT}..."
remote "
    cd '${SYNOLOGY_PATH}'
    rm -f '${LOG_FILE}'
    nohup ${PYTHON} main.py web > '${LOG_FILE}' 2>&1 &
    echo \$! > '${PID_FILE}'
    sleep 4

    HTTP_CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost:${APP_PORT}/ 2>/dev/null || echo '000')
    if [ \"\${HTTP_CODE}\" != '000' ]; then
        echo '  Running (HTTP '\${HTTP_CODE}')'
    else
        echo '  ERROR: no HTTP response on port ${APP_PORT}'
        echo '  Log:'
        tail -20 '${LOG_FILE}' 2>/dev/null | sed 's/^/    /'
        exit 1
    fi
"
ok "HueMonitor started"
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Deploy complete!                        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}http://${SYNOLOGY_HOST}:${APP_PORT}${NC}"
echo ""
echo -e "  ${DIM}./deploy-synology.sh status   # Check if running${NC}"
echo -e "  ${DIM}./deploy-synology.sh logs     # Tail remote log${NC}"
echo -e "  ${DIM}./deploy-synology.sh stop     # Stop the app${NC}"
echo -e "  ${DIM}./deploy-synology.sh ssh      # SSH into app dir${NC}"
echo ""
