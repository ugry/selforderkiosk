#!/usr/bin/env bash
# ============================================================
# Restaurant Kiosk – Client Machine Installer
# Installs ONLY the touch-screen kiosk app (no backend, no DB).
# Tested: Debian 13 (Trixie) / Python 3.13
# Run as: sudo bash install_kiosk.sh
# ============================================================
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
LOG="$BASE/install_kiosk.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*" | tee -a "$LOG"; }
success() { echo -e "${GREEN}[OK]${NC}    $*" | tee -a "$LOG"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}" | tee -a "$LOG"; }

[[ $EUID -ne 0 ]] && error "Please run as root: sudo bash install_kiosk.sh"

echo "" | tee "$LOG"
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}" | tee -a "$LOG"
echo -e "${BOLD}║   KIOSK APP INSTALLER                ║${NC}" | tee -a "$LOG"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}" | tee -a "$LOG"
info "Log: $LOG"
info "Dir: $BASE"

# ── Real user ──────────────────────────────────────────────────────────────────
REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    REAL_USER="$(stat -c '%U' "$BASE")"
fi
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    warn "Could not detect a non-root user — defaulting to root"
    REAL_USER="root"
fi
info "Running as user: ${REAL_USER}"
chmod o+x "$BASE" 2>/dev/null || true

# ── System packages ────────────────────────────────────────────────────────────
step "Installing system packages"
apt-get update -qq 2>&1 | tee -a "$LOG"

PKGS=(
    python3 python3-pip python3-venv
    python3-pyqt5
    python3-pil libjpeg-dev zlib1g-dev libpng-dev
    libfreetype6-dev python3-dev build-essential libffi-dev
    xorg openbox xinit unclutter fonts-liberation
    libxcb-xinerama0 libxcb-icccm4 libxcb-image0
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0
    libxcb-xkb1 libxkbcommon-x11-0 libxcb-cursor0
)

# libgl1 name changed in Debian 12+
if apt-cache show libgl1 &>/dev/null 2>&1; then
    PKGS+=(libgl1)
else
    PKGS+=(libgl1-mesa-glx)
fi

FAILED=()
for pkg in "${PKGS[@]}"; do
    if apt-get install -y "$pkg" >> "$LOG" 2>&1; then
        success "  ✓ $pkg"
    else
        warn "  ✗ $pkg — skipped"
        FAILED+=("$pkg")
    fi
done
[ ${#FAILED[@]} -gt 0 ] && warn "Skipped: ${FAILED[*]}"

# ── Python version ─────────────────────────────────────────────────────────────
step "Checking Python version"
PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
info "Python $PY_VER"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
    || error "Python 3.9+ required"
success "Python version OK"

# ── Verify system PyQt5 ────────────────────────────────────────────────────────
step "Verifying system PyQt5"
if python3 -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
    success "System PyQt5 is importable"
else
    warn "System PyQt5 not importable — pip fallback will be attempted inside venv"
fi

# ── Kiosk venv ─────────────────────────────────────────────────────────────────
step "Setting up kiosk virtual environment"
python3 -m venv --system-site-packages "$BASE/.venv" >> "$LOG" 2>&1
source "$BASE/.venv/bin/activate"
pip install --upgrade pip >> "$LOG" 2>&1
pip install -r "$BASE/requirements.txt" >> "$LOG" 2>&1 \
    && success "Kiosk packages installed" \
    || error "pip install failed — see $LOG"

python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')" >> "$LOG" 2>&1 \
    && success "PyQt5 import verified" \
    || warn "PyQt5 import failed — run: pip install PyQt5 inside $BASE/.venv"

python3 -c "from PIL import Image; print('Pillow OK')" >> "$LOG" 2>&1 \
    && success "Pillow import verified" \
    || warn "Pillow import failed"

deactivate

# ── kiosk.ini check ────────────────────────────────────────────────────────────
step "Checking kiosk.ini"
if [ ! -f "$BASE/kiosk.ini" ]; then
    warn "kiosk.ini not found — creating example"
    cat > "$BASE/kiosk.ini" <<INIEOF
[server]
host     = 192.168.1.100
port     = 8000
api_key  = PASTE_YOUR_API_KEY_HERE

[kiosk]
machine_id   =
fullscreen   = true
idle_timeout = 120
language     = en
printer_ip   =
printer_port = 9100
INIEOF
    warn "EDIT $BASE/kiosk.ini before starting the kiosk!"
else
    success "kiosk.ini found"
fi

# ── Autostart via .xinitrc ─────────────────────────────────────────────────────
step "Configuring autostart"
XINITRC="/home/${REAL_USER}/.xinitrc"
if [ "$REAL_USER" != "root" ]; then
    cat > "$XINITRC" <<XIEOF
#!/bin/sh
xset s off
xset -dpms
xset s noblank
unclutter -idle 1 -root &
exec ${BASE}/.venv/bin/python3 ${BASE}/kiosk.py
XIEOF
    chmod +x "$XINITRC"
    chown "$REAL_USER":"$REAL_USER" "$XINITRC"
    success "Written $XINITRC"
else
    warn "Running as root — skipping .xinitrc (set up manually)"
fi

# ── Final ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║        ✅  KIOSK INSTALL COMPLETE                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Log:${NC}   $LOG"
echo ""
echo -e "${BOLD}NEXT STEPS:${NC}"
echo "  1. Edit  $BASE/kiosk.ini  (set host + api_key)"
echo "  2. Start:  cd $BASE && bash start_kiosk.sh"
echo "     OR for autostart:  startx  (uses ~/.xinitrc)"
echo ""
[ ${#FAILED[@]} -gt 0 ] && printf "${YELLOW}Skipped packages:${NC} %s\n" "${FAILED[*]}"
