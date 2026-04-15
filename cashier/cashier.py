#!/usr/bin/env python3
"""
Restaurant Cashier App
PyQt5 desktop application for cashiers: view unpaid orders, accept payment,
print receipts, and mark orders as paid.
Config: cashier.ini   Logs: logs/
"""
import sys
import os
import json
import logging
import logging.handlers
import configparser
import requests
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
    QComboBox, QMessageBox, QSplitter, QTextEdit, QSizePolicy,
    QStatusBar,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPalette

# ── Logging ───────────────────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

def _setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "cashier.log"), maxBytes=5*1024*1024, backupCount=3
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

_setup_logging()
log = logging.getLogger("cashier")

# ── Config ────────────────────────────────────────────────────────────────────
cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cashier.ini"))

_PRIMARY_HOST   = cfg.get("server", "primary_host",   fallback="localhost")
_PRIMARY_PORT   = cfg.get("server", "primary_port",   fallback="8080")
_SECONDARY_HOST = cfg.get("server", "secondary_host", fallback="")
_SECONDARY_PORT = cfg.get("server", "secondary_port", fallback="8080")
API_KEY         = cfg.get("server", "api_key",        fallback="")
REFRESH_SEC     = cfg.getint("display", "refresh_sec", fallback=5)
FULLSCREEN      = cfg.getboolean("display", "fullscreen", fallback=False)
FONT_SIZE       = cfg.getint("display", "font_size", fallback=14)

_urls = [f"http://{_PRIMARY_HOST}:{_PRIMARY_PORT}"]
if _SECONDARY_HOST:
    _urls.append(f"http://{_SECONDARY_HOST}:{_SECONDARY_PORT}")
_active_base_url = _urls[0]

HEADERS = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}


def _try_request(method, path, **kwargs):
    global _active_base_url
    order = [_active_base_url] + [u for u in _urls if u != _active_base_url]
    last_exc = None
    for base in order:
        try:
            resp = getattr(requests, method)(
                f"{base}{path}", headers=HEADERS, timeout=10, **kwargs
            )
            resp.raise_for_status()
            if base != _active_base_url:
                log.warning("Failover: switched active backend %s → %s",
                            _active_base_url, base)
                _active_base_url = base
            return resp.json()
        except Exception as e:
            log.warning("Request to %s%s failed: %s", base, path, e)
            last_exc = e
    raise last_exc


def api_get(path):
    return _try_request("get", path)

def api_patch(path, data):
    return _try_request("patch", path, json=data)


# ── Colors ────────────────────────────────────────────────────────────────────
C_BG       = "#1A1A2E"
C_PANEL    = "#16213E"
C_CARD     = "#0F3460"
C_ACCENT   = "#E94560"
C_GREEN    = "#27AE60"
C_YELLOW   = "#F39C12"
C_TEXT     = "#EAEAEA"
C_SUBTEXT  = "#A0A0B0"
C_PAID     = "#1E8449"
C_UNPAID   = "#922B21"

STATUS_COLORS = {
    "pending":   "#F39C12",
    "confirmed": "#2980B9",
    "preparing": "#8E44AD",
    "ready":     "#27AE60",
    "completed": "#566573",
    "cancelled": "#7F8C8D",
}

PAYMENT_METHODS = ["cash", "card", "contactless", "mobile"]


# ── Background poller ─────────────────────────────────────────────────────────
class OrderPoller(QThread):
    orders_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, interval_sec=5, parent=None):
        super().__init__(parent)
        self._interval = interval_sec
        self._running  = True

    def run(self):
        while self._running:
            try:
                orders = api_get("/api/v1/orders?limit=100")
                unpaid = [o for o in orders if o.get("payment_status") == "unpaid"
                          and o.get("status") != "cancelled"]
                self.orders_fetched.emit(unpaid)
            except Exception as e:
                self.error_occurred.emit(str(e))
            self.msleep(self._interval * 1000)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(3000)


# ── Payment dialog ────────────────────────────────────────────────────────────
class PaymentDialog(QDialog):
    def __init__(self, order, currency, parent=None):
        super().__init__(parent)
        self.order    = order
        self.currency = currency
        self.setWindowTitle(f"Process Payment — Order #{order['queue_number']:04d}")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Order summary
        summary = QFrame()
        summary.setStyleSheet(f"background:{C_CARD};border-radius:8px;padding:10px")
        sl = QVBoxLayout(summary)

        queue_lbl = QLabel(f"Order #{self.order['queue_number']:04d}")
        queue_lbl.setStyleSheet(f"color:{C_ACCENT};font-size:22px;font-weight:bold")
        sl.addWidget(queue_lbl)

        time_str = self.order.get("created_at", "")
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                pass
        sl.addWidget(QLabel(f"Time: {time_str}"))

        sl.addWidget(QLabel(""))
        for line in self.order.get("lines", []):
            line_lbl = QLabel(f"  {line['quantity']}x  {line['name']}  "
                              f"({self.currency}{float(line['line_total']):.2f})")
            line_lbl.setStyleSheet(f"color:{C_TEXT};font-size:13px")
            sl.addWidget(line_lbl)
            for cust in line.get("customizations", []):
                c_lbl = QLabel(f"       + {cust['option_name']}")
                c_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px")
                sl.addWidget(c_lbl)

        sl.addWidget(QLabel(""))
        subtotal_lbl = QLabel(f"Subtotal:  {self.currency}{float(self.order['subtotal']):.2f}")
        subtotal_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:13px")
        sl.addWidget(subtotal_lbl)

        tax_lbl = QLabel(f"Tax:       {self.currency}{float(self.order['tax_amount']):.2f}")
        tax_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:13px")
        sl.addWidget(tax_lbl)

        total_lbl = QLabel(f"TOTAL:     {self.currency}{float(self.order['total_amount']):.2f}")
        total_lbl.setStyleSheet(f"color:{C_GREEN};font-size:18px;font-weight:bold")
        sl.addWidget(total_lbl)

        layout.addWidget(summary)

        # Payment method
        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Payment method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(PAYMENT_METHODS)
        cur = self.order.get("payment_method", "cash") or "cash"
        idx = self.method_combo.findText(cur)
        if idx >= 0:
            self.method_combo.setCurrentIndex(idx)
        method_row.addWidget(self.method_combo)
        layout.addLayout(method_row)

        # Buttons
        btns = QDialogButtonBox()
        ok_btn = btns.addButton("Mark as PAID", QDialogButtonBox.AcceptRole)
        ok_btn.setStyleSheet(
            f"background:{C_GREEN};color:white;font-weight:bold;"
            f"padding:8px 20px;border-radius:6px;font-size:14px"
        )
        cancel_btn = btns.addButton("Cancel", QDialogButtonBox.RejectRole)
        cancel_btn.setStyleSheet(
            f"background:#555;color:white;padding:8px 16px;border-radius:6px"
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_method(self):
        return self.method_combo.currentText()


# ── Order detail panel ────────────────────────────────────────────────────────
class OrderDetailPanel(QFrame):
    pay_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_PANEL};border-radius:10px")
        self._order = None
        self._currency = "€"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        self._title = QLabel("Select an order")
        self._title.setStyleSheet(
            f"color:{C_ACCENT};font-size:20px;font-weight:bold"
        )
        layout.addWidget(self._title)

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};font-size:13px;"
            "border:none;border-radius:8px;padding:10px"
        )
        layout.addWidget(self._detail_text)

        self._pay_btn = QPushButton("Process Payment")
        self._pay_btn.setEnabled(False)
        self._pay_btn.setStyleSheet(
            f"background:{C_GREEN};color:white;font-size:16px;font-weight:bold;"
            f"padding:12px;border-radius:8px"
        )
        self._pay_btn.clicked.connect(self._on_pay)
        layout.addWidget(self._pay_btn)

    def set_order(self, order, currency="€"):
        self._order    = order
        self._currency = currency
        q = order['queue_number']
        self._title.setText(f"Order #{q:04d}")

        lines = []
        lines.append(f"Status: {order['status'].upper()}")
        lines.append(f"Payment: {order['payment_method'] or 'not set'}")
        time_str = order.get("created_at", "")
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        lines.append(f"Time: {time_str}")
        if order.get("note"):
            lines.append(f"Note: {order['note']}")
        lines.append("")
        lines.append("─" * 40)
        for l in order.get("lines", []):
            lines.append(f"  {l['quantity']}x  {l['name']}"
                         f"  ({currency}{float(l['line_total']):.2f})")
            for c in l.get("customizations", []):
                lines.append(f"       + {c['option_name']}")
        lines.append("─" * 40)
        lines.append(f"  Subtotal : {currency}{float(order['subtotal']):.2f}")
        lines.append(f"  Tax      : {currency}{float(order['tax_amount']):.2f}")
        lines.append(f"  TOTAL    : {currency}{float(order['total_amount']):.2f}")

        self._detail_text.setPlainText("\n".join(lines))
        self._pay_btn.setEnabled(True)

    def clear(self):
        self._order = None
        self._title.setText("Select an order")
        self._detail_text.clear()
        self._pay_btn.setEnabled(False)

    def _on_pay(self):
        if self._order:
            self.pay_requested.emit(self._order)


# ── Order row card ────────────────────────────────────────────────────────────
class OrderCard(QFrame):
    selected = pyqtSignal(dict)

    def __init__(self, order, currency="€", parent=None):
        super().__init__(parent)
        self.order    = order
        self.currency = currency
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self._highlighted = False
        self._build_ui()
        self._set_style(False)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        # Queue number badge
        q = self.order['queue_number']
        num_lbl = QLabel(f"#{q:04d}")
        num_lbl.setFixedWidth(70)
        num_lbl.setAlignment(Qt.AlignCenter)
        num_lbl.setStyleSheet(
            f"color:{C_ACCENT};font-size:18px;font-weight:bold"
        )
        layout.addWidget(num_lbl)

        # Info column
        info_col = QVBoxLayout()
        status = self.order.get("status", "")
        sc = STATUS_COLORS.get(status, C_SUBTEXT)
        status_lbl = QLabel(status.upper())
        status_lbl.setStyleSheet(f"color:{sc};font-size:11px;font-weight:bold")
        info_col.addWidget(status_lbl)

        items_summary = ", ".join(
            f"{l['quantity']}x {l['name']}"
            for l in self.order.get("lines", [])[:3]
        )
        if len(self.order.get("lines", [])) > 3:
            items_summary += "…"
        items_lbl = QLabel(items_summary)
        items_lbl.setStyleSheet(f"color:{C_TEXT};font-size:12px")
        items_lbl.setWordWrap(True)
        info_col.addWidget(items_lbl)

        time_str = self.order.get("created_at", "")
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            except Exception:
                pass
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px")
        info_col.addWidget(time_lbl)

        layout.addLayout(info_col)
        layout.addStretch()

        # Total
        total = float(self.order.get("total_amount", 0))
        total_lbl = QLabel(f"{self.currency}{total:.2f}")
        total_lbl.setStyleSheet(
            f"color:{C_GREEN};font-size:16px;font-weight:bold"
        )
        layout.addWidget(total_lbl)

    def _set_style(self, highlighted):
        self._highlighted = highlighted
        bg = C_ACCENT if highlighted else C_CARD
        self.setStyleSheet(
            f"QFrame {{background:{bg};border-radius:10px;margin:3px}}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.order)
        super().mousePressEvent(event)

    def set_highlighted(self, val):
        self._set_style(val)


# ── Main window ───────────────────────────────────────────────────────────────
class CashierWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cashier Station")
        self._orders:  list  = []
        self._cards:   dict  = {}      # order_id → OrderCard
        self._currency = "€"
        self._selected_id = None
        self._settings_loaded = False
        self._build_ui()
        self._load_settings()
        self._start_poller()
        if FULLSCREEN:
            self.showFullScreen()
        else:
            self.resize(1100, 700)

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        central.setStyleSheet(f"background:{C_BG}")

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{C_PANEL}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("CASHIER")
        title.setStyleSheet(
            f"color:{C_ACCENT};font-size:22px;font-weight:bold;letter-spacing:3px"
        )
        hl.addWidget(title)

        self._backend_lbl = QLabel(_active_base_url)
        self._backend_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px")
        hl.addStretch()
        hl.addWidget(self._backend_lbl)

        self._conn_dot = QLabel("●")
        self._conn_dot.setStyleSheet(f"color:{C_GREEN};font-size:18px")
        hl.addWidget(self._conn_dot)

        root.addWidget(header)

        # Splitter: order list | detail
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #333; width: 2px; }")

        # LEFT: unpaid order list
        left = QWidget()
        left.setStyleSheet(f"background:{C_BG}")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)

        list_header = QHBoxLayout()
        self._count_lbl = QLabel("Unpaid: 0")
        self._count_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:bold"
        )
        list_header.addWidget(self._count_lbl)
        list_header.addStretch()

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border-radius:6px;padding:4px 10px"
        )
        refresh_btn.clicked.connect(self._manual_refresh)
        list_header.addWidget(refresh_btn)
        ll.addLayout(list_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea {border:none}")
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._list_layout.setSpacing(4)
        scroll.setWidget(self._list_widget)
        ll.addWidget(scroll)

        splitter.addWidget(left)

        # RIGHT: detail + pay button
        self._detail = OrderDetailPanel()
        self._detail.pay_requested.connect(self._on_pay_requested)
        splitter.addWidget(self._detail)

        splitter.setSizes([480, 500])
        root.addWidget(splitter, 1)

        # Status bar
        self.statusBar().setStyleSheet(
            f"background:{C_PANEL};color:{C_SUBTEXT};font-size:11px"
        )
        self.statusBar().showMessage("Starting…")

    # ── Init ───────────────────────────────────────────────────────────────
    def _load_settings(self):
        try:
            s = api_get("/api/v1/settings")
            self._currency = s.get("currency_symbol", "€")
            self._settings_loaded = True
        except Exception as e:
            log.warning("Could not load settings: %s", e)

    def _start_poller(self):
        self._poller = OrderPoller(REFRESH_SEC)
        self._poller.orders_fetched.connect(self._on_orders)
        self._poller.error_occurred.connect(self._on_error)
        self._poller.start()

    def _manual_refresh(self):
        try:
            orders = api_get("/api/v1/orders?limit=100")
            unpaid = [o for o in orders
                      if o.get("payment_status") == "unpaid"
                      and o.get("status") != "cancelled"]
            self._on_orders(unpaid)
        except Exception as e:
            self._on_error(str(e))

    # ── Order list updates ─────────────────────────────────────────────────
    def _on_orders(self, orders):
        self._conn_dot.setStyleSheet(f"color:{C_GREEN};font-size:18px")
        self._backend_lbl.setText(_active_base_url)
        self.statusBar().showMessage(
            f"Last update: {datetime.now().strftime('%H:%M:%S')}  |  "
            f"Unpaid orders: {len(orders)}"
        )
        self._orders = orders
        self._count_lbl.setText(f"Unpaid: {len(orders)}")

        new_ids = {o["id"] for o in orders}

        # Remove cards for orders that are now paid/gone
        for oid in list(self._cards):
            if oid not in new_ids:
                card = self._cards.pop(oid)
                self._list_layout.removeWidget(card)
                card.deleteLater()
                if self._selected_id == oid:
                    self._selected_id = None
                    self._detail.clear()

        # Add new cards
        for order in orders:
            oid = order["id"]
            if oid not in self._cards:
                card = OrderCard(order, self._currency)
                card.selected.connect(self._on_card_selected)
                self._cards[oid] = card
                self._list_layout.addWidget(card)
            else:
                # Update existing card in-place (refresh data)
                self._cards[oid].order = order

        if not self._settings_loaded:
            self._load_settings()

    def _on_error(self, msg):
        self._conn_dot.setStyleSheet(f"color:{C_ACCENT};font-size:18px")
        self.statusBar().showMessage(f"Connection error: {msg}")
        log.error("Backend error: %s", msg)

    # ── Selection ──────────────────────────────────────────────────────────
    def _on_card_selected(self, order):
        # De-highlight previous
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_highlighted(False)
        self._selected_id = order["id"]
        self._cards[order["id"]].set_highlighted(True)
        self._detail.set_order(order, self._currency)

    # ── Payment flow ───────────────────────────────────────────────────────
    def _on_pay_requested(self, order):
        dlg = PaymentDialog(order, self._currency, self)
        dlg.setStyleSheet(
            f"background:{C_BG};color:{C_TEXT};"
            f"QLabel{{color:{C_TEXT}}} QComboBox{{background:{C_CARD};color:{C_TEXT}}}"
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        method = dlg.selected_method()
        order_id = order["id"]
        try:
            api_patch(
                f"/api/v1/orders/{order_id}/payment",
                {"payment_status": "paid", "payment_method": method},
            )
            log.info("Marked order %s as paid via %s", order_id, method)
            QMessageBox.information(
                self, "Payment Recorded",
                f"Order #{order['queue_number']:04d} marked as PAID ({method}).\n"
                "Receipt will be printed if a printer is configured for this machine.",
            )
            # Remove from list immediately
            self._manual_refresh()
        except Exception as e:
            log.error("Payment update failed: %s", e)
            QMessageBox.critical(self, "Error", f"Could not update payment:\n{e}")

    # ── Cleanup ────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._poller.stop()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Cashier")

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(C_BG))
    palette.setColor(QPalette.WindowText,      QColor(C_TEXT))
    palette.setColor(QPalette.Base,            QColor(C_PANEL))
    palette.setColor(QPalette.AlternateBase,   QColor(C_CARD))
    palette.setColor(QPalette.Text,            QColor(C_TEXT))
    palette.setColor(QPalette.Button,          QColor(C_CARD))
    palette.setColor(QPalette.ButtonText,      QColor(C_TEXT))
    palette.setColor(QPalette.Highlight,       QColor(C_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)

    font = QFont("Arial", FONT_SIZE)
    app.setFont(font)

    win = CashierWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
