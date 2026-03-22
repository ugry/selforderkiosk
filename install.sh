#!/usr/bin/env bash
# ============================================================
# Restaurant Kiosk – Full Install Script
# Tested: Debian 11 (Bullseye), 12 (Bookworm), 13 (Trixie)
#         Ubuntu 22.04 / 24.04
# Run as: sudo bash install.sh
# ============================================================
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
LOG="$BASE/install.log"

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*" | tee -a "$LOG"; }
success() { echo -e "${GREEN}[OK]${NC}    $*" | tee -a "$LOG"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}" | tee -a "$LOG"; }

# ── Root check ─────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Please run as root: sudo bash install.sh"
fi

echo "" | tee "$LOG"
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}" | tee -a "$LOG"
echo -e "${BOLD}║   RESTAURANT KIOSK INSTALLER         ║${NC}" | tee -a "$LOG"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}" | tee -a "$LOG"
info "Log file: $LOG"
info "Base dir: $BASE"

# ── Resolve the real (non-root) user ──────────────────────────────────────────
# SUDO_USER is set by sudo; fall back to the owner of the install dir.
REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    REAL_USER="$(stat -c '%U' "$BASE")"
fi
# Final safety: if still root or empty, ask the operator to set it.
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    warn "Could not detect a non-root user. Defaulting service to run as root."
    warn "To change this, edit /etc/systemd/system/restaurant-backend.service"
    REAL_USER="root"
fi
info "Service will run as user: ${REAL_USER}"

# Ensure the service user can traverse into the app directory
chmod o+x "$BASE" "$BASE/backend" 2>/dev/null || true

# ── Detect distro ──────────────────────────────────────────────────────────────
step "Detecting OS"
DISTRO_ID=""
DISTRO_VER=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_VER="${VERSION_ID:-0}"
fi
info "Detected: ${DISTRO_ID} ${DISTRO_VER}"

# ── System packages ────────────────────────────────────────────────────────────
# Notes on removed/renamed packages:
#   python3-pyqt5.qtwidgets  → removed; all widgets are in python3-pyqt5
#   qt5-default              → removed in Debian 11+ / Ubuntu 22.04+
#   libgl1-mesa-glx          → renamed to libgl1 in Debian 12+
step "Installing system packages"
apt-get update -qq 2>&1 | tee -a "$LOG"

BASE_PKGS=(
    python3 python3-pip python3-venv
    postgresql postgresql-contrib libpq-dev
    xorg openbox xinit unclutter
    fonts-liberation curl wget
)

# PyQt5 system package (provides QtWidgets, QtCore, QtGui, etc.)
# NOTE: python3-pyqt5.qtwidgets and qt5-default no longer exist in Debian 11+
PYQT_PKGS=(python3-pyqt5)

# Pillow (PIL) system package + the C libraries it needs.
# Installing python3-pil via apt means we never need to compile Pillow from
# source inside the venv, which avoids the "Failed to build pillow" pip error.
# The build-dep headers below also protect any future pip wheel builds.
PIL_PKGS=(
    python3-pil           # system Pillow — inherited via --system-site-packages
    libjpeg-dev           # JPEG support
    zlib1g-dev            # PNG / zlib compression
    libpng-dev            # PNG support
    libtiff-dev           # TIFF support
    libfreetype6-dev      # font rendering
    liblcms2-dev          # colour management
    libwebp-dev           # WebP support
    python3-dev           # Python C headers (required for any C-extension wheel)
    build-essential       # gcc / make for wheel compilation fallback
    libffi-dev            # cffi used by several packages
)

# Qt5 XCB platform plugin dependencies (required on headless/kiosk Linux)
QT_XCB_PKGS=(
    libxcb-xinerama0
    libxcb-icccm4
    libxcb-image0
    libxcb-keysyms1
    libxcb-randr0
    libxcb-render-util0
    libxcb-xkb1
    libxkbcommon-x11-0
    libxcb-cursor0
)

# libgl1 – renamed from libgl1-mesa-glx in Debian 12+
GL_PKG="libgl1"
if ! apt-cache show libgl1 &>/dev/null 2>&1; then
    GL_PKG="libgl1-mesa-glx"
    warn "libgl1 not found, falling back to libgl1-mesa-glx"
fi

ALL_PKGS=("${BASE_PKGS[@]}" "${PYQT_PKGS[@]}" "${PIL_PKGS[@]}" "${QT_XCB_PKGS[@]}" "$GL_PKG")

info "Packages to install: ${ALL_PKGS[*]}"

FAILED_PKGS=()
for pkg in "${ALL_PKGS[@]}"; do
    if apt-get install -y "$pkg" >> "$LOG" 2>&1; then
        success "  ✓ $pkg"
    else
        warn "  ✗ $pkg — skipped (may not exist on this distro)"
        FAILED_PKGS+=("$pkg")
    fi
done

if [ ${#FAILED_PKGS[@]} -gt 0 ]; then
    warn "Skipped packages: ${FAILED_PKGS[*]}"
    warn "This may be fine — some are optional display helpers."
fi

# ── Python version check ───────────────────────────────────────────────────────
step "Checking Python version"
PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
info "Python $PY_VER"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
    || error "Python 3.9+ required (found $PY_VER)"
success "Python version OK"

# ── PyQt5 system package verify ────────────────────────────────────────────────
step "Verifying system PyQt5"
if python3 -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
    success "System python3-pyqt5 (QtWidgets) is importable"
else
    warn "System PyQt5 QtWidgets not importable — kiosk/monitor will try pip fallback"
fi

# ── Backend venv ───────────────────────────────────────────────────────────────
step "Setting up backend (FastAPI + PostgreSQL)"
cd "$BASE/backend"

# Isolated venv — backend does NOT need PyQt5
info "Creating backend virtual environment..."
python3 -m venv .venv >> "$LOG" 2>&1
source .venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip >> "$LOG" 2>&1

info "Installing backend Python packages..."
pip install -r requirements.txt >> "$LOG" 2>&1 \
    && success "Backend packages installed" \
    || error "Backend pip install failed — see $LOG"

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        warn "Created .env from .env.example — EDIT before production!"
    else
        warn ".env.example not found — writing minimal .env"
        cat > .env <<ENVEOF
DATABASE_URL=postgresql+asyncpg://kiosk:kiosk_pass@localhost:5432/restaurant_db
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
UPLOAD_DIR=app/static/uploads
HOST=0.0.0.0
PORT=8000
ENVEOF
    fi
fi
deactivate

# ── Database ───────────────────────────────────────────────────────────────────
step "Setting up PostgreSQL database"
if systemctl is-active --quiet postgresql; then
    bash setup_db.sh 2>&1 | tee -a "$LOG" \
        && success "Database ready" \
        || warn "DB setup had issues — check $LOG (may already exist)"
else
    error "PostgreSQL is not running. Start it: sudo systemctl start postgresql"
fi

# ── Kiosk venv ─────────────────────────────────────────────────────────────────
step "Setting up customer kiosk app"
cd "$BASE/kiosk"

# IMPORTANT: --system-site-packages inherits the system python3-pyqt5
# so we do NOT pip-install PyQt5 (it isn't in requirements.txt for this venv)
info "Creating kiosk virtual environment (with system-site-packages for PyQt5)..."
python3 -m venv --system-site-packages .venv >> "$LOG" 2>&1
source .venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip >> "$LOG" 2>&1

info "Installing kiosk Python packages..."
pip install -r requirements.txt >> "$LOG" 2>&1 \
    && success "Kiosk packages installed" \
    || error "Kiosk pip install failed — see $LOG"

# Verify PyQt5 is reachable inside the venv
python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')" >> "$LOG" 2>&1 \
    && success "Kiosk PyQt5 import verified" \
    || warn "PyQt5 import failed in kiosk venv — run: pip install PyQt5 inside $BASE/kiosk/.venv"

python3 -c "from PIL import Image; print('Pillow OK')" >> "$LOG" 2>&1 \
    && success "Kiosk Pillow import verified" \
    || warn "Pillow import failed in kiosk venv — run: pip install Pillow inside $BASE/kiosk/.venv"

deactivate

# ── Monitor venv ───────────────────────────────────────────────────────────────
step "Setting up order monitor app"
cd "$BASE/order_monitor"

info "Creating monitor virtual environment (with system-site-packages for PyQt5)..."
python3 -m venv --system-site-packages .venv >> "$LOG" 2>&1
source .venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip >> "$LOG" 2>&1

info "Installing monitor Python packages..."
pip install -r requirements.txt >> "$LOG" 2>&1 \
    && success "Monitor packages installed" \
    || error "Monitor pip install failed — see $LOG"

python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')" >> "$LOG" 2>&1 \
    && success "Monitor PyQt5 import verified" \
    || warn "PyQt5 import failed in monitor venv — run: pip install PyQt5 inside $BASE/order_monitor/.venv"

deactivate

# ── systemd service for backend ────────────────────────────────────────────────
step "Installing systemd service (backend)"
cat > /etc/systemd/system/restaurant-backend.service <<EOF
[Unit]
Description=Restaurant Kiosk Backend (FastAPI)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=${REAL_USER}
WorkingDirectory=${BASE}/backend
# The leading '-' makes EnvironmentFile optional — service still starts without .env
EnvironmentFile=-${BASE}/backend/.env
ExecStart=${BASE}/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
info "Service file written — User=${REAL_USER}  WorkingDirectory=${BASE}/backend"

mkdir -p "$BASE/backend/logs"
chown "$REAL_USER":"$REAL_USER" "$BASE/backend/logs"

systemctl daemon-reload
systemctl enable restaurant-backend >> "$LOG" 2>&1
systemctl restart restaurant-backend >> "$LOG" 2>&1 \
    && success "Backend service started" \
    || warn "Backend service failed to start — check: journalctl -u restaurant-backend"

# ── Port 8000 listen check ──────────────────────────────────────────────────
step "Checking port 8000"
PORT_OK=false
for i in 1 2 3 4 5; do
    if ss -tlnp 2>/dev/null | grep -q ':8000 ' || \
       nc -z 127.0.0.1 8000 2>/dev/null; then
        PORT_OK=true
        break
    fi
    info "  Waiting for port 8000 … attempt $i/5"
    sleep 2
done

if $PORT_OK; then
    success "Port 8000 is LISTENING ✓"
    info "Health endpoint: http://127.0.0.1:8000/health"
    # Quick health-check via curl if available
    if command -v curl &>/dev/null; then
        HEALTH=$(curl -s --max-time 3 http://127.0.0.1:8000/health 2>/dev/null)
        if [ -n "$HEALTH" ]; then
            success "Health response: $HEALTH"
        fi
    fi
else
    warn "Port 8000 is NOT listening after 10 s"
    warn "Last 30 journal lines for restaurant-backend:"
    echo "──────────────────────────────────────────────────" | tee -a "$LOG"
    journalctl -u restaurant-backend -n 30 --no-pager 2>/dev/null | tee -a "$LOG" \
        || warn "journalctl unavailable"
    echo "──────────────────────────────────────────────────" | tee -a "$LOG"
    warn "Service file written with: User=${REAL_USER}  WorkingDirectory=${BASE}/backend"
    warn "To fix manually run:  sudo systemctl status restaurant-backend"
fi
info "Application logs: $BASE/backend/logs/"
info "  app.log    — all activity"
info "  error.log  — errors only"
info "  health.log — /health endpoint calls"

# ── Final summary ──────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║              ✅  INSTALLATION COMPLETE               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Backend API:${NC}    http://${SERVER_IP}:8000"
echo -e "  ${BOLD}Admin Panel:${NC}    http://${SERVER_IP}:8000/admin/"
echo -e "  ${BOLD}API Docs:${NC}       http://${SERVER_IP}:8000/docs"
echo -e "  ${BOLD}Install log:${NC}    $LOG"
echo ""
echo -e "${BOLD}NEXT STEPS:${NC}"
echo "  1. Edit  $BASE/backend/.env  (set SECRET_KEY etc.)"
echo "  2. Open admin panel → Machines → copy API key for each machine"
echo "  3. Edit kiosk/kiosk.ini          → set host + api_key"
echo "  4. Edit order_monitor/monitor.ini → set host + api_key"
echo ""
echo -e "${BOLD}Start kiosk (on kiosk machine):${NC}"
echo "   cd $BASE/kiosk && bash start_kiosk.sh"
echo ""
echo -e "${BOLD}Start monitor (on monitor machine):${NC}"
echo "   cd $BASE/order_monitor && bash start_monitor.sh"
echo ""
if [ ${#FAILED_PKGS[@]} -gt 0 ]; then
    echo -e "${YELLOW}Skipped apt packages (may need manual install):${NC}"
    printf '   %s\n' "${FAILED_PKGS[@]}"
    echo ""
fi
