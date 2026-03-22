#!/usr/bin/env bash
# ============================================================
# Restaurant Kiosk – Kitchen Display Machine Installer
# Installs ONLY the KDS app (no backend, no DB).
# Tested: Debian 13 (Trixie) / Python 3.13
# Run as: sudo bash install_kitchen.sh
# ============================================================
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
LOG="$BASE/install_kitchen.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*" | tee -a "$LOG"; }
success() { echo -e "${GREEN}[OK]${NC}    $*" | tee -a "$LOG"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}" | tee -a "$LOG"; }

[[ $EUID -ne 0 ]] && error "Please run as root: sudo bash install_kitchen.sh"

echo "" | tee "$LOG"
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}" | tee -a "$LOG"
echo -e "${BOLD}║   KITCHEN DISPLAY INSTALLER          ║${NC}" | tee -a "$LOG"
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
    xorg openbox xinit unclutter fonts-liberation
    libxcb-xinerama0 libxcb-icccm4 libxcb-image0
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0
    libxcb-xkb1 libxkbcommon-x11-0 libxcb-cursor0
)

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

# ── Kitchen venv ───────────────────────────────────────────────────────────────
step "Setting up kitchen virtual environment"
python3 -m venv --system-site-packages "$BASE/.venv" >> "$LOG" 2>&1
source "$BASE/.venv/bin/activate"
pip install --upgrade pip >> "$LOG" 2>&1
pip install -r "$BASE/requirements.txt" >> "$LOG" 2>&1 \
    && success "Kitchen packages installed" \
    || error "pip install failed — see $LOG"

python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')" >> "$LOG" 2>&1 \
    && success "PyQt5 import verified" \
    || warn "PyQt5 import failed — run: pip install PyQt5 inside $BASE/.venv"

deactivate

# ── kitchen.ini check ──────────────────────────────────────────────────────────
step "Checking kitchen.ini"
if [ ! -f "$BASE/kitchen.ini" ]; then
    warn "kitchen.ini not found — creating example"
    cat > "$BASE/kitchen.ini" <<INIEOF
[server]
host    = 192.168.1.100
port    = 8000
api_key = PASTE_YOUR_KITCHEN_API_KEY_HERE

[display]
fullscreen    = true
refresh_sec   = 4
font_size     = 22
columns       = 3
show_statuses = pending,confirmed,preparing
INIEOF
    warn "EDIT $BASE/kitchen.ini before starting the kitchen display!"
else
    success "kitchen.ini found"
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
exec ${BASE}/.venv/bin/python3 ${BASE}/kitchen.py
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
echo "║      ✅  KITCHEN DISPLAY INSTALL COMPLETE            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Log:${NC}   $LOG"
echo ""
echo -e "${BOLD}NEXT STEPS:${NC}"
echo "  1. Edit  $BASE/kitchen.ini  (set host + api_key)"
echo "     api_key must belong to a machine of type 'kitchen' in the admin panel"
echo "  2. Start:  cd $BASE && bash start_kitchen.sh"
echo "     OR for autostart:  startx  (uses ~/.xinitrc)"
echo ""
echo -e "${BOLD}Button actions on KDS:${NC}"
echo "  CONFIRM → START → DONE ✓  (bumps order through queue)"
echo "  F5 — manual refresh"
echo "  F11 — toggle fullscreen"
echo ""
[ ${#FAILED[@]} -gt 0 ] && printf "${YELLOW}Skipped packages:${NC} %s\n" "${FAILED[*]}"
