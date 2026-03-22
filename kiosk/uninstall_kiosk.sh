#!/usr/bin/env bash
# ============================================================
# Restaurant Kiosk – Kiosk Machine Uninstaller
# Removes: .venv, logs/, install log files, ~/.xinitrc
# Does NOT touch system packages or the source files.
# Run as: sudo bash uninstall_kiosk.sh
#         sudo bash uninstall_kiosk.sh --force
# ============================================================
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
skip()    { echo -e "        ${YELLOW}↳ skip${NC} — $*"; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

[[ $EUID -ne 0 ]] && { echo -e "${RED}Please run as root: sudo bash uninstall_kiosk.sh${NC}"; exit 1; }

REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    REAL_USER="$(stat -c '%U' "$BASE" 2>/dev/null || echo "")"
fi

echo ""
echo -e "${RED}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║        KIOSK MACHINE – UNINSTALL / CLEANUP          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}App directory:${NC}  $BASE"
echo ""
echo -e "${BOLD}Will remove:${NC}"
echo "  • $BASE/.venv/"
echo "  • $BASE/logs/"
echo "  • $BASE/*.log  (install log files)"
echo "  • ~/.xinitrc   (if it references this app)"
echo ""

if ! $FORCE; then
    echo -ne "${YELLOW}${BOLD}Type YES to continue: ${NC}"
    read -r CONFIRM
    [[ "$CONFIRM" != "YES" ]] && { echo "Aborted."; exit 0; }
fi

step "Removing virtual environment"
if [ -d "$BASE/.venv" ]; then
    rm -rf "$BASE/.venv"
    success "Removed $BASE/.venv"
else
    skip ".venv not found"
fi

step "Removing logs"
if [ -d "$BASE/logs" ]; then
    rm -rf "$BASE/logs"
    success "Removed $BASE/logs"
else
    skip "logs/ not found"
fi

step "Removing install log files"
shopt -s nullglob
for f in "$BASE"/*.log; do
    rm -f "$f" && success "Removed $f"
done
shopt -u nullglob

step "Removing ~/.xinitrc (if set by this app)"
_remove_xinitrc() {
    local home
    home=$(getent passwd "$1" 2>/dev/null | cut -d: -f6 || echo "")
    [ -z "$home" ] && return
    local xi="$home/.xinitrc"
    if [ -f "$xi" ] && grep -q "$BASE" "$xi" 2>/dev/null; then
        rm -f "$xi" && success "Removed $xi"
    else
        skip "$xi does not reference this app"
    fi
}
if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
    _remove_xinitrc "$REAL_USER"
else
    for h in /home/*/; do _remove_xinitrc "$(basename "$h")"; done
fi

echo ""
echo -e "${GREEN}${BOLD}✅  Kiosk cleanup complete.${NC}"
echo ""
echo "  Source files kept in: $BASE"
echo "  To also delete source: rm -rf $BASE"
echo ""
