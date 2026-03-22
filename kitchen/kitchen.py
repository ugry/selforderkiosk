#!/usr/bin/env python3
"""
Restaurant Kitchen Display System (KDS)
Shows active orders with item details.
Staff can bump orders through statuses: pending → confirmed → preparing → ready.
Config: kitchen.ini
Polls backend every N seconds.
"""
import sys
import os
import configparser
import logging
import logging.handlers
import requests
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QScrollArea, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont

# ── Logging ────────────────────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)


def _setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    already_setup = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers
    )
    if already_setup:
        return

    # logs/kitchen.log — INFO+, 2 MB × 5 files
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "kitchen.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # logs/error.log — ERROR+, 1 MB × 3 files
    eh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "error.log"),
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)
    root.addHandler(eh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


_setup_logging()
log = logging.getLogger("kitchen")

# ── Config ─────────────────────────────────────────────────────────────────────
_INI = os.path.join(os.path.dirname(__file__), "kitchen.ini")
cfg = configparser.ConfigParser()
cfg.read(_INI)
log.info("Config loaded from %s", _INI)

SERVER_HOST   = cfg.get("server",  "host",         fallback="localhost")
SERVER_PORT   = cfg.get("server",  "port",         fallback="8000")
API_KEY       = cfg.get("server",  "api_key",      fallback="")
FULLSCREEN    = cfg.getboolean("display", "fullscreen",   fallback=True)
REFRESH_SEC   = cfg.getint("display",    "refresh_sec",   fallback=4)
FONT_SIZE     = cfg.getint("display",    "font_size",     fallback=22)
COLUMNS       = cfg.getint("display",    "columns",       fallback=3)
_statuses_raw = cfg.get("display", "show_statuses", fallback="pending,confirmed,preparing")
SHOW_STATUSES = [s.strip() for s in _statuses_raw.split(",") if s.strip()]

BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
HEADERS  = {"X-Api-Key": API_KEY}
log.info("Backend: %s  refresh: %ds  statuses: %s", BASE_URL, REFRESH_SEC, SHOW_STATUSES)

# ── Colors ─────────────────────────────────────────────────────────────────────
C_BG     = "#0D0D0D"
C_PANEL  = "#1A1A1A"
C_ORANGE = "#FF6B00"
C_WHITE  = "#FFFFFF"
C_GREEN  = "#2ECC71"
C_YELLOW = "#F39C12"
C_RED    = "#E74C3C"
C_GRAY   = "#555555"
C_LIGHT  = "#AAAAAA"

STATUS_COLOR = {
    "pending":   "#888888",
    "confirmed": C_YELLOW,
    "preparing": C_ORANGE,
    "ready":     C_GREEN,
}
STATUS_LABEL = {
    "pending":   "⏳ New",
    "confirmed": "✓ Confirmed",
    "preparing": "🍳 Preparing",
    "ready":     "✅ Ready",
}

# What pressing the action button does for each status
NEXT_STATUS = {
    "pending":   ("confirmed",  "CONFIRM"),
    "confirmed": ("preparing",  "START"),
    "preparing": ("ready",      "DONE ✓"),
    "ready":     (None,         ""),        # no further action
}

# ── Status updater thread ──────────────────────────────────────────────────────
class StatusUpdater(QThread):
    success = pyqtSignal(str, str)   # order_id, new_status
    error   = pyqtSignal(str, str)   # order_id, error message

    def __init__(self, order_id: str, new_status: str):
        super().__init__()
        self.order_id   = order_id
        self.new_status = new_status

    def run(self):
        try:
            r = requests.patch(
                f"{BASE_URL}/api/v1/orders/{self.order_id}/status",
                json={"status": self.new_status},
                headers=HEADERS,
                timeout=5,
            )
            r.raise_for_status()
            log.info("Status updated  order=%s  → %s", self.order_id, self.new_status)
            self.success.emit(self.order_id, self.new_status)
        except Exception as exc:
            log.error("Status update FAILED  order=%s  error=%s", self.order_id, exc)
            self.error.emit(self.order_id, str(exc))


# ── Polling thread ─────────────────────────────────────────────────────────────
class Poller(QThread):
    data_ready = pyqtSignal(list)
    error      = pyqtSignal(str)

    def run(self):
        try:
            resp = requests.get(
                f"{BASE_URL}/api/v1/queue",
                headers=HEADERS,
                timeout=5,
            )
            resp.raise_for_status()
            orders = resp.json()
            # Filter to only the statuses we care about
            orders = [o for o in orders if o.get("status") in SHOW_STATUSES]
            log.debug("Poll OK — %d orders", len(orders))
            self.data_ready.emit(orders)
        except Exception as exc:
            log.error("Poll failed: %s", exc)
            self.error.emit(str(exc))


# ── Order card ─────────────────────────────────────────────────────────────────
class OrderCard(QFrame):
    """A kitchen ticket card for one order."""

    status_change_requested = pyqtSignal(str, str)  # order_id, new_status

    def __init__(self, order: dict, parent=None):
        super().__init__(parent)
        self.order_id = order["id"]
        self.status   = order.get("status", "pending")
        items         = order.get("items", [])
        queue_number  = order.get("queue_number", 0)
        created_at    = order.get("created_at", "")

        color = STATUS_COLOR.get(self.status, C_GRAY)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C_PANEL};
                border: 3px solid {color};
                border-radius: 14px;
            }}
        """)

        v = QVBoxLayout(self)
        v.setSpacing(6)
        v.setContentsMargins(14, 12, 14, 12)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()

        num_lbl = QLabel(f"#{queue_number:04d}")
        num_lbl.setStyleSheet(
            f"font-size:{FONT_SIZE + 6}px;font-weight:900;color:{color};border:none"
        )
        hdr.addWidget(num_lbl)
        hdr.addStretch()

        status_lbl = QLabel(STATUS_LABEL.get(self.status, self.status.upper()))
        status_lbl.setStyleSheet(
            f"font-size:{FONT_SIZE - 6}px;color:{color};font-weight:bold;border:none"
        )
        hdr.addWidget(status_lbl)

        v.addLayout(hdr)

        # ── Time since order ──────────────────────────────────────────────────
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                elapsed = int((datetime.now().astimezone() - dt).total_seconds() / 60)
                time_str = f"{elapsed}m ago" if elapsed >= 1 else "just now"
            except Exception:
                time_str = ""
            time_lbl = QLabel(time_str)
            time_lbl.setStyleSheet(
                f"font-size:{FONT_SIZE - 10}px;color:{C_LIGHT};border:none"
            )
            v.addWidget(time_lbl)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{C_GRAY};background:{C_GRAY};border:none")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # ── Item list ─────────────────────────────────────────────────────────
        for item in items:
            qty  = item.get("quantity", 1)
            name = item.get("name", "")
            row  = QLabel(f"  {qty}×  {name}")
            row.setStyleSheet(
                f"font-size:{FONT_SIZE}px;color:{C_WHITE};font-weight:bold;border:none"
            )
            row.setWordWrap(True)
            v.addWidget(row)

        if not items:
            placeholder = QLabel("(no items)")
            placeholder.setStyleSheet(
                f"font-size:{FONT_SIZE - 4}px;color:{C_GRAY};border:none"
            )
            v.addWidget(placeholder)

        v.addStretch()

        # ── Action button ─────────────────────────────────────────────────────
        next_status, btn_label = NEXT_STATUS.get(self.status, (None, ""))
        if next_status:
            self.btn = QPushButton(btn_label)
            self.btn.setCursor(Qt.PointingHandCursor)
            self.btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    color: #000000;
                    font-size: {FONT_SIZE - 2}px;
                    font-weight: 900;
                    border: none;
                    border-radius: 10px;
                    padding: 10px 0;
                }}
                QPushButton:hover {{
                    background: {C_WHITE};
                    color: #000000;
                }}
                QPushButton:disabled {{
                    background: {C_GRAY};
                    color: {C_LIGHT};
                }}
            """)
            self.btn.clicked.connect(
                lambda _, ns=next_status: self.status_change_requested.emit(
                    self.order_id, ns
                )
            )
            v.addWidget(self.btn)

    def set_busy(self, busy: bool):
        """Disable button while API call is in flight."""
        if hasattr(self, "btn"):
            self.btn.setEnabled(not busy)
            self.btn.setText("…" if busy else NEXT_STATUS.get(self.status, (None, ""))[1])


# ── Main Kitchen Window ────────────────────────────────────────────────────────
class KitchenWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kitchen Display")
        self._cards: dict[str, OrderCard] = {}          # order_id → card
        self._updaters: dict[str, StatusUpdater] = {}   # order_id → thread
        self._consecutive_errors = 0
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._poll)
        self.refresh_timer.start(REFRESH_SEC * 1000)
        self._poll()

        if FULLSCREEN:
            self.showFullScreen()
        else:
            self.resize(1280, 800)

        log.info("KitchenWindow started — fullscreen=%s  columns=%d", FULLSCREEN, COLUMNS)

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background:{C_BG}")
        main = QVBoxLayout(root)
        main.setSpacing(0)
        main.setContentsMargins(0, 0, 0, 0)

        # ── TOP BAR ───────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(72)
        top.setStyleSheet(f"background:{C_PANEL};border-bottom:2px solid {C_ORANGE}")
        top_h = QHBoxLayout(top)
        top_h.setContentsMargins(20, 0, 20, 0)

        title = QLabel("🍳  KITCHEN DISPLAY")
        title.setStyleSheet(
            f"font-size:20px;font-weight:900;color:{C_ORANGE};letter-spacing:3px"
        )
        top_h.addWidget(title)
        top_h.addStretch()

        self.order_count_lbl = QLabel("")
        self.order_count_lbl.setStyleSheet(f"font-size:14px;color:{C_LIGHT}")
        top_h.addWidget(self.order_count_lbl)

        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet(f"font-size:14px;color:{C_LIGHT};margin-left:24px")
        top_h.addWidget(self.clock_lbl)
        self._update_clock()
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start(10000)

        self.conn_lbl = QLabel("● CONNECTING…")
        self.conn_lbl.setStyleSheet(
            f"font-size:12px;color:{C_YELLOW};margin-left:20px"
        )
        top_h.addWidget(self.conn_lbl)

        main.addWidget(top)

        # ── GRID scroll area ──────────────────────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border:none;background:transparent")
        main.addWidget(self.scroll, 1)

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(f"background:{C_BG}")
        self.grid = QGridLayout(self.grid_container)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(16, 16, 16, 16)
        self.scroll.setWidget(self.grid_container)

        # ── STATUS BAR ────────────────────────────────────────────────────────
        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background:{C_PANEL}")
        bar_h = QHBoxLayout(bar)
        bar_h.setContentsMargins(20, 0, 20, 0)
        self.status_lbl = QLabel("Starting…")
        self.status_lbl.setStyleSheet(f"font-size:12px;color:{C_GRAY}")
        bar_h.addWidget(self.status_lbl)
        bar_h.addStretch()
        self.last_update_lbl = QLabel("")
        self.last_update_lbl.setStyleSheet(f"font-size:12px;color:{C_GRAY}")
        bar_h.addWidget(self.last_update_lbl)
        main.addWidget(bar)

        self.setCentralWidget(root)

    def _poll(self):
        self.poller = Poller()
        self.poller.data_ready.connect(self._on_data)
        self.poller.error.connect(self._on_error)
        self.poller.start()

    def _on_data(self, orders: list):
        self._consecutive_errors = 0
        self.conn_lbl.setText("● LIVE")
        self.conn_lbl.setStyleSheet(f"font-size:12px;color:{C_GREEN};margin-left:20px")
        self.last_update_lbl.setText("Updated: " + datetime.now().strftime("%H:%M:%S"))
        self.order_count_lbl.setText(f"{len(orders)} order(s) active")

        log.info("Display updated — %d active orders", len(orders))

        # Clear grid but rebuild all cards from fresh data
        # (keeps it simple; tiles are small so full rebuild is fast enough)
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._cards.clear()

        if not orders:
            empty = QLabel("No active orders – all clear! 🎉")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"font-size:28px;color:{C_GRAY};padding:60px")
            self.grid.addWidget(empty, 0, 0, 1, COLUMNS)
            self.status_lbl.setText("Queue empty")
            return

        self.status_lbl.setText(f"Showing: {', '.join(SHOW_STATUSES)}")
        for idx, order in enumerate(orders):
            card = OrderCard(order)
            card.status_change_requested.connect(self._on_status_change)
            self.grid.addWidget(card, idx // COLUMNS, idx % COLUMNS)
            self._cards[order["id"]] = card

    def _on_error(self, msg: str):
        self._consecutive_errors += 1
        log.error("Connection error #%d: %s", self._consecutive_errors, msg)
        self.conn_lbl.setText("● OFFLINE")
        self.conn_lbl.setStyleSheet(f"font-size:12px;color:{C_RED};margin-left:20px")
        self.last_update_lbl.setText("Failed: " + datetime.now().strftime("%H:%M:%S"))
        self.status_lbl.setText(f"Error: {msg}")

    def _on_status_change(self, order_id: str, new_status: str):
        card = self._cards.get(order_id)
        if card:
            card.set_busy(True)

        updater = StatusUpdater(order_id, new_status)
        updater.success.connect(self._on_status_ok)
        updater.error.connect(self._on_status_err)
        self._updaters[order_id] = updater
        updater.start()
        log.info("Requesting status change  order=%s  → %s", order_id, new_status)

    def _on_status_ok(self, order_id: str, new_status: str):
        self._updaters.pop(order_id, None)
        log.info("Status change confirmed  order=%s  → %s", order_id, new_status)
        # Trigger a fresh poll to get updated data
        self._poll()

    def _on_status_err(self, order_id: str, msg: str):
        self._updaters.pop(order_id, None)
        card = self._cards.get(order_id)
        if card:
            card.set_busy(False)
        self.status_lbl.setText(f"Update failed: {msg}")
        log.error("Status change failed  order=%s  error=%s", order_id, msg)

    def _update_clock(self):
        if hasattr(self, "clock_lbl"):
            self.clock_lbl.setText(datetime.now().strftime("%H:%M"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F12:
            log.info("F12 pressed — exiting kitchen display")
            QApplication.quit()
        elif event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        elif event.key() == Qt.Key_Escape:
            self.showNormal()
        elif event.key() == Qt.Key_F5:
            self._poll()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Starting Kitchen Display System")
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    window = KitchenWindow()
    if not FULLSCREEN:
        window.show()

    sys.exit(app.exec_())
