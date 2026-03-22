#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ── Venv check ─────────────────────────────────────────────────────────────────
if [ ! -f ".venv/bin/python3" ]; then
    echo "ERROR: .venv not found. Run first: sudo bash install_kiosk.sh"
    exit 1
fi

# ── Hide cursor after 5 s of inactivity ───────────────────────────────────────
unclutter -idle 5 2>/dev/null &

# ── Screen saver / power management (suppress missing-extension errors) ────────
xset s off      2>/dev/null || true
xset -dpms      2>/dev/null || true   # DPMS extension may not be present
xset s noblank  2>/dev/null || true

# ── Launch ─────────────────────────────────────────────────────────────────────
exec "$DIR/.venv/bin/python3" "$DIR/kiosk.py"
