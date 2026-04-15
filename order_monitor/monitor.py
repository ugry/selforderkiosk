#!/usr/bin/env python3
"""
Restaurant Order Monitor
Dedicated screen showing active queue and completed orders.
Config: monitor.ini
Polls backend every N seconds for live updates.
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
    QLabel, QFrame, QGridLayout, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette

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

    # Avoid duplicate handlers if module is re-imported
    already_setup = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers
    )
    if already_setup:
        return

    # logs/monitor.log — INFO and above, 2 MB × 5 files
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "monitor.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # logs/error.log — ERROR and above, 1 MB × 3 files
    eh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "error.log"),
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)
    root.addHandler(eh)

    # Console — INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

_setup_logging()
log = logging.getLogger("monitor")

# ── Config ─────────────────────────────────────────────────────────────────────
_INI = os.path.join(os.path.dirname(__file__), "monitor.ini")
cfg = configparser.ConfigParser()
cfg.read(_INI)
log.info("Config loaded from %s", _INI)

_PRIMARY_HOST   = cfg.get("server", "primary_host",   fallback="localhost")
_PRIMARY_PORT   = cfg.get("server", "primary_port",   fallback="8080")
_SECONDARY_HOST = cfg.get("server", "secondary_host", fallback="")
_SECONDARY_PORT = cfg.get("server", "secondary_port", fallback="8080")
API_KEY         = cfg.get("server", "api_key",        fallback="")
FULLSCREEN      = cfg.getboolean("display", "fullscreen",    fallback=True)
REFRESH_SEC     = cfg.getint("display",    "refresh_sec",    fallback=5)
FONT_SIZE       = cfg.getint("display",    "font_size",      fallback=28)
COLUMNS         = cfg.getint("display",    "columns",        fallback=2)
SHOW_COMPLETED  = cfg.getboolean("display","show_completed", fallback=True)

_urls = [f"http://{_PRIMARY_HOST}:{_PRIMARY_PORT}"]
if _SECONDARY_HOST:
    _urls.append(f"http://{_SECONDARY_HOST}:{_SECONDARY_PORT}")
_active_base_url = _urls[0]

HEADERS = {"X-Api-Key": API_KEY}
log.info("Backend: primary=%s:%s  secondary=%s:%s  refresh: %ds  columns: %d",
         _PRIMARY_HOST, _PRIMARY_PORT, _SECONDARY_HOST, _SECONDARY_PORT,
         REFRESH_SEC, COLUMNS)


def _try_request(path):
    global _active_base_url
    order = [_active_base_url] + [u for u in _urls if u != _active_base_url]
    last_exc = None
    for base in order:
        try:
            resp = requests.get(f"{base}{path}", headers=HEADERS, timeout=6)
            resp.raise_for_status()
            if base != _active_base_url:
                log.warning("Failover: switched active backend %s → %s", _active_base_url, base)
                _active_base_url = base
            return resp.json()
        except Exception as e:
            log.warning("Request to %s%s failed: %s", base, path, e)
            last_exc = e
    raise last_exc

# ── Colors ─────────────────────────────────────────────────────────────────────
C_BG        = "#0D0D0D"
C_PANEL     = "#1A1A1A"
C_ORANGE    = "#FF6B00"
C_WHITE     = "#FFFFFF"
C_GREEN     = "#2ECC71"
C_YELLOW    = "#F39C12"
C_BLUE      = "#3498DB"
C_GRAY      = "#555555"
C_LIGHT     = "#AAAAAA"

STATUS_COLOR = {
    "pending":   C_GRAY,
    "confirmed": C_YELLOW,
    "preparing": C_ORANGE,
    "ready":     C_GREEN,
    "completed": C_GREEN,
}
STATUS_LABEL = {
    "pending":   "⏳ Waiting",
    "confirmed": "✓ Confirmed",
    "preparing": "🍳 Preparing",
    "ready":     "✅ Ready!",
}


# ── Polling thread ─────────────────────────────────────────────────────────────
class Poller(QThread):
    data_ready = pyqtSignal(list, list, dict)
    error      = pyqtSignal(str)

    def run(self):
        try:
            queue     = _try_request("/api/v1/queue")
            completed = _try_request("/api/v1/completed")
            settings  = _try_request("/api/v1/settings")
            log.debug(
                "Poll OK — queue: %d active, %d completed",
                len(queue), len(completed),
            )
            self.data_ready.emit(queue, completed, settings)
        except Exception as exc:
            log.error("Poll failed: %s", exc)
            self.error.emit(str(exc))


# ── Order tile ─────────────────────────────────────────────────────────────────
class OrderTile(QFrame):
    """Displays one active order: queue number, status, and item list."""

    def __init__(self, order: dict, parent=None):
        super().__init__(parent)
        status = order.get("status", "pending")
        queue_number = order.get("queue_number", 0)
        items = order.get("items", [])

        color = STATUS_COLOR.get(status, C_GRAY)
        self.setMinimumSize(200, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C_PANEL};
                border: 3px solid {color};
                border-radius: 16px;
            }}
        """)

        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignTop)
        v.setSpacing(4)
        v.setContentsMargins(12, 10, 12, 10)

        # Queue number
        num = QLabel(f"#{queue_number:04d}")
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet(
            f"font-size:{FONT_SIZE + 4}px;font-weight:900;color:{color};border:none"
        )
        v.addWidget(num)

        # Status label
        label_text = STATUS_LABEL.get(status, status.upper())
        lbl = QLabel(label_text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"font-size:{FONT_SIZE - 10}px;color:{color};font-weight:bold;border:none"
        )
        v.addWidget(lbl)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{C_GRAY};background:{C_GRAY};border:none")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # Item list (truncated to keep tile compact)
        for item in items[:4]:
            qty  = item.get("quantity", 1)
            name = item.get("name", "")
            # Trim long names
            if len(name) > 22:
                name = name[:20] + "…"
            row = QLabel(f"{qty}× {name}")
            row.setAlignment(Qt.AlignLeft)
            row.setStyleSheet(
                f"font-size:{FONT_SIZE - 14}px;color:{C_LIGHT};border:none"
            )
            v.addWidget(row)

        if len(items) > 4:
            more = QLabel(f"+ {len(items) - 4} more…")
            more.setAlignment(Qt.AlignLeft)
            more.setStyleSheet(
                f"font-size:{FONT_SIZE - 16}px;color:{C_GRAY};border:none"
            )
            v.addWidget(more)

        v.addStretch()


# ── Main Monitor Window ────────────────────────────────────────────────────────
class MonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Order Monitor")
        self.restaurant_name = "Restaurant"
        self._consecutive_errors = 0
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._poll)
        self.refresh_timer.start(REFRESH_SEC * 1000)
        self._poll()

        if FULLSCREEN:
            self.showFullScreen()
        else:
            self.resize(1080, 1920)

        log.info("MonitorWindow started — fullscreen=%s", FULLSCREEN)

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background:{C_BG}")
        main = QVBoxLayout(root)
        main.setSpacing(0)
        main.setContentsMargins(0, 0, 0, 0)

        # ── TOP BAR ───────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(90)
        top.setStyleSheet(f"background:{C_PANEL};border-bottom:2px solid {C_ORANGE}")
        top_h = QHBoxLayout(top)
        top_h.setContentsMargins(24, 0, 24, 0)

        self.name_lbl = QLabel("🍽 ORDER DISPLAY")
        self.name_lbl.setStyleSheet(
            f"font-size:22px;font-weight:900;color:{C_ORANGE};letter-spacing:3px"
        )
        top_h.addWidget(self.name_lbl)
        top_h.addStretch()

        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet(f"font-size:15px;color:{C_LIGHT}")
        top_h.addWidget(self.clock_lbl)
        self._update_clock()

        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start(10000)

        self.conn_lbl = QLabel("● CONNECTING…")
        self.conn_lbl.setStyleSheet(
            f"font-size:12px;color:{C_YELLOW};margin-left:16px"
        )
        top_h.addWidget(self.conn_lbl)

        main.addWidget(top)

        # ── BODY (queue + completed) ──────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        # LEFT: active queue
        queue_section = QWidget()
        queue_section.setStyleSheet(f"background:{C_BG}")
        queue_v = QVBoxLayout(queue_section)
        queue_v.setContentsMargins(20, 16, 10, 16)
        queue_v.setSpacing(12)

        queue_hdr = QLabel("IN QUEUE")
        queue_hdr.setStyleSheet(
            f"font-size:16px;font-weight:bold;color:{C_LIGHT};letter-spacing:2px"
        )
        queue_v.addWidget(queue_hdr)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setStyleSheet("border:none;background:transparent")
        queue_v.addWidget(self.queue_scroll, 1)

        body.addWidget(queue_section, 3)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(f"color:{C_PANEL};background:{C_PANEL};min-width:2px")
        body.addWidget(div)

        # RIGHT: completed orders
        if SHOW_COMPLETED:
            done_section = QWidget()
            done_section.setStyleSheet(f"background:{C_BG}")
            done_v = QVBoxLayout(done_section)
            done_v.setContentsMargins(10, 16, 20, 16)
            done_v.setSpacing(12)

            done_hdr = QLabel("✅ COMPLETED")
            done_hdr.setStyleSheet(
                f"font-size:16px;font-weight:bold;color:{C_GREEN};letter-spacing:2px"
            )
            done_v.addWidget(done_hdr)

            self.done_scroll = QScrollArea()
            self.done_scroll.setWidgetResizable(True)
            self.done_scroll.setStyleSheet("border:none;background:transparent")
            done_v.addWidget(self.done_scroll, 1)

            body.addWidget(done_section, 1)

        main.addLayout(body, 1)

        # ── STATUS BAR ────────────────────────────────────────────────────────
        ticker = QFrame()
        ticker.setFixedHeight(44)
        ticker.setStyleSheet(f"background:{C_PANEL}")
        tick_h = QHBoxLayout(ticker)
        tick_h.setContentsMargins(24, 0, 24, 0)
        self.ticker_lbl = QLabel(
            "Welcome – please collect your order when your number is called"
        )
        self.ticker_lbl.setStyleSheet(f"font-size:14px;color:{C_LIGHT}")
        tick_h.addWidget(self.ticker_lbl)
        tick_h.addStretch()
        self.last_update_lbl = QLabel("")
        self.last_update_lbl.setStyleSheet(f"font-size:12px;color:{C_GRAY}")
        tick_h.addWidget(self.last_update_lbl)
        main.addWidget(ticker)

        self.setCentralWidget(root)

    def _poll(self):
        self.poller = Poller()
        self.poller.data_ready.connect(self._on_data)
        self.poller.error.connect(self._on_error)
        self.poller.start()

    def _on_data(self, queue: list, completed: list, settings: dict):
        self._consecutive_errors = 0
        self.restaurant_name = settings.get("restaurant_name", "Restaurant")
        self.name_lbl.setText(f"🍽 {self.restaurant_name.upper()} – ORDER DISPLAY")
        self.conn_lbl.setText("● LIVE")
        self.conn_lbl.setStyleSheet(f"font-size:12px;color:{C_GREEN};margin-left:16px")
        self.last_update_lbl.setText("Updated: " + datetime.now().strftime("%H:%M:%S"))

        log.info(
            "Display updated — %d active, %d completed",
            len(queue), len(completed),
        )

        # Render queue tiles
        q_container = QWidget()
        q_grid = QGridLayout(q_container)
        q_grid.setSpacing(12)
        q_grid.setContentsMargins(0, 0, 0, 0)
        if queue:
            for idx, order in enumerate(queue):
                tile = OrderTile(order)
                q_grid.addWidget(tile, idx // COLUMNS, idx % COLUMNS)
        else:
            empty = QLabel("No active orders")
            empty.setStyleSheet(f"font-size:18px;color:{C_GRAY};padding:30px")
            empty.setAlignment(Qt.AlignCenter)
            q_grid.addWidget(empty, 0, 0)
        self.queue_scroll.setWidget(q_container)

        # Ready orders — announce in status bar
        ready = [o for o in queue if o["status"] == "ready"]
        if ready:
            nums = ", ".join(f"#{o['queue_number']:04d}" for o in ready)
            self.ticker_lbl.setText(f"🔔 Orders ready for collection: {nums}")
            self.ticker_lbl.setStyleSheet(
                f"font-size:16px;color:{C_GREEN};font-weight:bold"
            )
            log.info("Ready orders: %s", nums)
        else:
            self.ticker_lbl.setText(
                "Welcome – please collect your order when your number is called"
            )
            self.ticker_lbl.setStyleSheet(f"font-size:14px;color:{C_LIGHT}")

        # Render completed list
        if SHOW_COMPLETED and hasattr(self, "done_scroll"):
            d_container = QWidget()
            d_v = QVBoxLayout(d_container)
            d_v.setSpacing(8)
            d_v.setContentsMargins(0, 0, 0, 0)
            for order in completed:
                row = QLabel(f"  ✓  #{order['queue_number']:04d}")
                row.setStyleSheet(
                    f"font-size:{FONT_SIZE - 8}px;color:{C_GREEN};font-weight:bold;"
                    f"background:{C_PANEL};border-radius:8px;padding:8px 16px"
                )
                d_v.addWidget(row)
            d_v.addStretch()
            self.done_scroll.setWidget(d_container)

    def _on_error(self, msg: str):
        self._consecutive_errors += 1
        log.error(
            "Connection error #%d: %s", self._consecutive_errors, msg
        )
        self.conn_lbl.setText("● OFFLINE")
        self.conn_lbl.setStyleSheet(f"font-size:12px;color:#e74c3c;margin-left:16px")
        self.last_update_lbl.setText(
            "Failed: " + datetime.now().strftime("%H:%M:%S")
        )

    def _update_clock(self):
        if hasattr(self, "clock_lbl"):
            self.clock_lbl.setText(datetime.now().strftime("%A  %d %B  %H:%M"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F12:
            log.info("F12 pressed — exiting monitor")
            QApplication.quit()
        elif event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        elif event.key() == Qt.Key_Escape:
            self.showNormal()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Starting Order Monitor")
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    window = MonitorWindow()
    if not FULLSCREEN:
        window.show()

    sys.exit(app.exec_())
