#!/usr/bin/env bash
# ============================================================
# Restaurant Kiosk – Full Uninstall / Cleanup Script
# Removes: systemd service, PostgreSQL database & user,
#          all Python venvs, logs, uploads, .env, .xinitrc
#
# Does NOT remove system packages (postgresql, python3-pyqt5,
# etc.) — those may be shared with other software.
#
# Run as:  sudo bash uninstall.sh          (interactive)
#          sudo bash uninstall.sh --force  (no confirmation)
# ============================================================
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
skip()    { echo -e "        ${YELLOW}↳ skip${NC} — $*"; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

[[ $EUID -ne 0 ]] && { echo -e "${RED}Please run as root: sudo bash uninstall.sh${NC}"; exit 1; }

# ── DB credentials (read from .env if present, else use defaults) ──────────────
ENV_FILE="$BASE/backend/.env"
DB_NAME="restaurant_db"
DB_USER="kiosk"
if [ -f "$ENV_FILE" ]; then
    # Extract DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname
    _URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [[ "$_URL" =~ ://([^:]+):[^@]+@[^/]+/([^?]+) ]]; then
        DB_USER="${BASH_REMATCH[1]}"
        DB_NAME="${BASH_REMATCH[2]}"
    fi
fi

# ── Real user (for .xinitrc removal) ─────────────────────────────────────────
REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    REAL_USER="$(stat -c '%U' "$BASE" 2>/dev/null || echo "")"
fi

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${RED}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║         RESTAURANT KIOSK – FULL UNINSTALL           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}App directory:${NC}  $BASE"
echo -e "  ${BOLD}Database:${NC}       $DB_NAME  (user: $DB_USER)"
echo ""
echo -e "${RED}${BOLD}THIS WILL PERMANENTLY DELETE:${NC}"
echo "  • systemd service  restaurant-backend"
echo "  • PostgreSQL database '$DB_NAME' and user '$DB_USER'"
echo "  • All Python virtual environments (.venv/)"
echo "  • All log directories (*/logs/)"
echo "  • backend/.env"
echo "  • backend/app/static/uploads/"
echo "  • *.log install log files"
echo "  • ~/.xinitrc (if it references this app)"
echo ""

if ! $FORCE; then
    echo -ne "${YELLOW}${BOLD}Type YES to continue, anything else to abort: ${NC}"
    read -r CONFIRM
    if [[ "$CONFIRM" != "YES" ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step "1 / 5 — Stopping and removing systemd service"
# ─────────────────────────────────────────────────────────────────────────────
SERVICE="restaurant-backend"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"

if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    systemctl stop "$SERVICE" && success "Service stopped"
else
    skip "service not running"
fi

if systemctl is-enabled --quiet "$SERVICE" 2>/dev/null; then
    systemctl disable "$SERVICE" && success "Service disabled"
else
    skip "service not enabled"
fi

if [ -f "$SERVICE_FILE" ]; then
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    success "Removed $SERVICE_FILE"
else
    skip "$SERVICE_FILE not found"
fi

# ─────────────────────────────────────────────────────────────────────────────
step "2 / 5 — Dropping PostgreSQL database and user"
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v psql &>/dev/null; then
    skip "psql not found — skipping database removal"
elif ! systemctl is-active --quiet postgresql 2>/dev/null; then
    warn "PostgreSQL is not running — attempting to start it for cleanup"
    systemctl start postgresql 2>/dev/null || warn "Could not start PostgreSQL — DB not removed"
fi

if command -v psql &>/dev/null && systemctl is-active --quiet postgresql 2>/dev/null; then
    # Drop database (terminate active connections first)
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null | grep -q 1; then
        sudo -u postgres psql <<SQL 2>/dev/null
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${DB_NAME}";
SQL
        success "Dropped database '${DB_NAME}'"
    else
        skip "database '${DB_NAME}' does not exist"
    fi

    # Drop user (only if no other databases depend on it)
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" 2>/dev/null | grep -q 1; then
        sudo -u postgres psql -c "DROP OWNED BY \"${DB_USER}\" CASCADE;" 2>/dev/null || true
        sudo -u postgres psql -c "DROP ROLE IF EXISTS \"${DB_USER}\";" 2>/dev/null \
            && success "Dropped user '${DB_USER}'" \
            || warn "Could not drop user '${DB_USER}' — may own other objects"
    else
        skip "user '${DB_USER}' does not exist"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
step "3 / 5 — Removing Python virtual environments"
# ─────────────────────────────────────────────────────────────────────────────
VENVS=(
    "$BASE/backend/.venv"
    "$BASE/kiosk/.venv"
    "$BASE/order_monitor/.venv"
    "$BASE/kitchen/.venv"
)
for venv in "${VENVS[@]}"; do
    if [ -d "$venv" ]; then
        rm -rf "$venv"
        success "Removed $venv"
    else
        skip "$venv not found"
    fi
done

# ─────────────────────────────────────────────────────────────────────────────
step "4 / 5 — Removing generated files (logs, uploads, .env)"
# ─────────────────────────────────────────────────────────────────────────────

# Log directories
LOG_DIRS=(
    "$BASE/backend/logs"
    "$BASE/kiosk/logs"
    "$BASE/order_monitor/logs"
    "$BASE/kitchen/logs"
)
for d in "${LOG_DIRS[@]}"; do
    if [ -d "$d" ]; then
        rm -rf "$d"
        success "Removed $d"
    else
        skip "$d not found"
    fi
done

# Uploaded images / menu photos
UPLOADS="$BASE/backend/app/static/uploads"
if [ -d "$UPLOADS" ]; then
    rm -rf "$UPLOADS"
    success "Removed $UPLOADS"
else
    skip "$UPLOADS not found"
fi

# .env (contains secrets)
if [ -f "$BASE/backend/.env" ]; then
    rm -f "$BASE/backend/.env"
    success "Removed $BASE/backend/.env"
else
    skip ".env not found"
fi

# Install log files at the repo root
for logfile in "$BASE"/*.log "$BASE/backend"/*.log "$BASE/kiosk"/*.log \
               "$BASE/order_monitor"/*.log "$BASE/kitchen"/*.log; do
    [ -f "$logfile" ] && rm -f "$logfile" && success "Removed $logfile" || true
done

# ─────────────────────────────────────────────────────────────────────────────
step "5 / 5 — Removing .xinitrc autostart (if set by this app)"
# ─────────────────────────────────────────────────────────────────────────────
_remove_xinitrc() {
    local user="$1"
    local home
    home=$(getent passwd "$user" 2>/dev/null | cut -d: -f6 || echo "")
    [ -z "$home" ] && return
    local xi="$home/.xinitrc"
    if [ -f "$xi" ] && grep -q "$BASE" "$xi" 2>/dev/null; then
        rm -f "$xi"
        success "Removed $xi (referenced $BASE)"
    else
        skip "$xi does not reference this app"
    fi
}

if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
    _remove_xinitrc "$REAL_USER"
else
    # No SUDO_USER — scan home dirs and remove any .xinitrc referencing this app
    for home_dir in /home/*/; do
        u=$(basename "$home_dir")
        _remove_xinitrc "$u"
    done
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║          ✅  UNINSTALL COMPLETE                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  The application source files in $BASE have been"
echo "  left in place. To also delete them:"
echo ""
echo -e "  ${BOLD}rm -rf $BASE${NC}"
echo ""
echo "  System packages (postgresql, python3-pyqt5, etc.) were"
echo "  NOT removed — uninstall them manually if needed:"
echo ""
echo "    sudo apt-get remove --purge postgresql postgresql-contrib"
echo ""
