#!/usr/bin/env python3
"""
Restaurant Self-Order Kiosk
Touch-screen PyQt5 application for customer ordering.
Config: kiosk.ini   Logs: logs/
"""
import sys
import os
import json
import logging
import logging.handlers
import configparser
import tempfile
import requests
from datetime import datetime

try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    from PyQt5.QtCore import QUrl
    _QT_MULTIMEDIA = True
except ImportError:
    _QT_MULTIMEDIA = False

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QGridLayout, QFrame,
    QDialog, QCheckBox, QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QPixmap, QColor

from translations import T, set_language, is_rtl

# ── Logging setup ─────────────────────────────────────────────────────────────
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
        os.path.join(_LOG_DIR, "kiosk.log"), maxBytes=5*1024*1024, backupCount=3
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    eh = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "error.log"), maxBytes=2*1024*1024, backupCount=2
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)
    root.addHandler(eh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

_setup_logging()
log = logging.getLogger("kiosk")

# ── Config ────────────────────────────────────────────────────────────────────
cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kiosk.ini"))

_PRIMARY_HOST   = cfg.get("server", "primary_host",   fallback="localhost")
_PRIMARY_PORT   = cfg.get("server", "primary_port",   fallback="8080")
_SECONDARY_HOST = cfg.get("server", "secondary_host", fallback="")
_SECONDARY_PORT = cfg.get("server", "secondary_port", fallback="8080")
API_KEY         = cfg.get("server", "api_key",        fallback="")
FULLSCREEN      = cfg.getboolean("kiosk", "fullscreen",   fallback=True)
IDLE_TIMEOUT    = cfg.getint("kiosk",    "idle_timeout",  fallback=120)
# Initial language from ini — overridden by server setting once loaded
_ini_lang       = cfg.get("kiosk", "language", fallback="en")
set_language(_ini_lang)

_urls = [f"http://{_PRIMARY_HOST}:{_PRIMARY_PORT}"]
if _SECONDARY_HOST:
    _urls.append(f"http://{_SECONDARY_HOST}:{_SECONDARY_PORT}")
_active_base_url = _urls[0]

HEADERS = {"X-Api-Key": API_KEY}

log.info("=" * 60)
log.info("Kiosk starting  primary=%s:%s  secondary=%s:%s  lang=%s",
         _PRIMARY_HOST, _PRIMARY_PORT, _SECONDARY_HOST, _SECONDARY_PORT, _ini_lang)

# ── HTTP helpers with dual-IP failover ────────────────────────────────────────
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
                log.warning("Failover: switched active backend %s → %s", _active_base_url, base)
                _active_base_url = base
            return resp.json()
        except Exception as e:
            log.warning("Request to %s%s failed: %s", base, path, e)
            last_exc = e
    raise last_exc

def api_get(path):
    return _try_request("get", path)

def api_post(path, data):
    return _try_request("post", path, json=data)

# ── Theme constants (defaults; overridden from server settings) ───────────────
PRIMARY    = "#FF6B00"
DARK       = "#1A1A1A"
BG         = "#F9F9F9"
WHITE      = "#FFFFFF"
TEXT       = "#222222"
GRAY       = "#888888"
LIGHT_GRAY = "#EEEEEE"
RED        = "#e74c3c"
GREEN      = "#2ecc71"

def style_button(color=None, text_color=WHITE, radius=12, font_size=15, bold=True):
    c = color or PRIMARY
    weight = "bold" if bold else "normal"
    return f"""
        QPushButton {{
            background-color: {c};
            color: {text_color};
            border: none;
            border-radius: {radius}px;
            font-size: {font_size}px;
            font-weight: {weight};
            padding: 10px 18px;
        }}
        QPushButton:hover   {{ background-color: #CC5500; }}
        QPushButton:pressed {{ background-color: #AA4400; }}
        QPushButton:disabled {{ background-color: #cccccc; color: #888888; }}
    """

# ── Data loader thread ────────────────────────────────────────────────────────
class DataLoader(QThread):
    loaded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self):
        try:
            log.debug("DataLoader: fetching settings/categories/items")
            settings   = api_get("/api/v1/settings")
            categories = api_get("/api/v1/categories")
            items      = api_get("/api/v1/items")
            log.info("DataLoader: loaded %d categories, %d items",
                     len(categories), len(items))
            self.loaded.emit({"settings": settings, "categories": categories, "items": items})
        except Exception as e:
            log.error("DataLoader: failed to load data: %s", e)
            self.failed.emit(str(e))

# ── Order submit thread ───────────────────────────────────────────────────────
class OrderSubmitter(QThread):
    success = pyqtSignal(dict)
    failed  = pyqtSignal(str)

    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.payload = payload

    def run(self):
        try:
            result = api_post("/api/v1/orders", self.payload)
            log.info("Order submitted  queue=#%s  total=%s",
                     result.get("queue_number"), result.get("total_amount"))
            self.success.emit(result)
        except Exception as e:
            log.error("Order submission failed: %s", e)
            self.failed.emit(str(e))

# ── Item card ─────────────────────────────────────────────────────────────────
class ItemCard(QFrame):
    add_clicked = pyqtSignal(dict)

    def __init__(self, item, currency_symbol="€", parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedSize(200, 240)
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background: {WHITE};
                border-radius: 14px;
                border: 2px solid {LIGHT_GRAY};
            }}
            QFrame:hover {{ border-color: {PRIMARY}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        img_label = QLabel()
        img_label.setFixedHeight(110)
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setStyleSheet(f"background:{LIGHT_GRAY};border-radius:10px;font-size:40px")

        if item.get("image_url"):
            try:
                resp = requests.get(f"{_active_base_url}{item['image_url']}", timeout=3)
                pix  = QPixmap()
                pix.loadFromData(resp.content)
                img_label.setPixmap(
                    pix.scaled(180, 110, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                )
            except Exception:
                img_label.setText("🍽")
        else:
            img_label.setText("🍽")

        if item.get("is_promoted"):
            promo = QLabel(T["promo_badge"], img_label)
            promo.setStyleSheet(
                f"background:{PRIMARY};color:white;font-size:10px;"
                f"font-weight:bold;padding:2px 7px;border-radius:4px"
            )
            promo.move(6, 6)

        layout.addWidget(img_label)

        name = QLabel(item["name"])
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"font-size:14px;font-weight:bold;color:{TEXT}")
        layout.addWidget(name)

        price = QLabel(f"{currency_symbol}{float(item['price']):.2f}")
        price.setAlignment(Qt.AlignCenter)
        price.setStyleSheet(f"font-size:16px;font-weight:bold;color:{PRIMARY}")
        layout.addWidget(price)

        add_btn = QPushButton(T["add_btn"])
        add_btn.setStyleSheet(style_button(font_size=13))
        add_btn.clicked.connect(lambda: self.add_clicked.emit(self.item))
        layout.addWidget(add_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.add_clicked.emit(self.item)

# ── Cart row ──────────────────────────────────────────────────────────────────
class CartRow(QFrame):
    remove_clicked = pyqtSignal(int)

    def __init__(self, entry, idx, currency_symbol="€", parent=None):
        super().__init__(parent)
        self.idx = idx
        self.setStyleSheet(f"background:{WHITE};border-radius:8px;margin-bottom:4px")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        info = QVBoxLayout()
        name_label = QLabel(f"<b>{entry['quantity']}×  {entry['name']}</b>")
        name_label.setStyleSheet(f"font-size:13px;color:{TEXT}")
        info.addWidget(name_label)
        if entry.get("customizations"):
            opts = ", ".join(c["option_name"] for c in entry["customizations"])
            opt_label = QLabel(f"  + {opts}")
            opt_label.setStyleSheet(f"font-size:11px;color:{GRAY}")
            info.addWidget(opt_label)
        layout.addLayout(info)

        total = float(entry["unit_price"]) * entry["quantity"]
        price_label = QLabel(f"{currency_symbol}{total:.2f}")
        price_label.setStyleSheet(f"font-size:14px;font-weight:bold;color:{PRIMARY}")
        layout.addWidget(price_label)

        rm = QPushButton("✕")
        rm.setFixedSize(28, 28)
        rm.setStyleSheet("background:#ff4444;color:white;border-radius:14px;font-size:12px")
        rm.clicked.connect(lambda: self.remove_clicked.emit(self.idx))
        layout.addWidget(rm)

# ── Customization dialog ──────────────────────────────────────────────────────
class CustomizeDialog(QDialog):
    def __init__(self, item, currency_symbol="€", parent=None):
        super().__init__(parent)
        self.item   = item
        self.symbol = currency_symbol
        self.setWindowTitle(f"{T['customise_title']}: {item['name']}")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"background:{BG}")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.addWidget(QLabel(f"<b>{item['name']}</b>",
                                styleSheet=f"font-size:18px;color:{TEXT}"))

        self.checkboxes = {}
        for group in item.get("customization_groups", []):
            suffix = T["required_suffix"] if group["is_required"] else ""
            grp_label = QLabel(group["name"] + suffix)
            grp_label.setStyleSheet(
                f"font-size:14px;font-weight:bold;color:{PRIMARY};margin-top:6px"
            )
            layout.addWidget(grp_label)
            self.checkboxes[group["id"]] = []
            for opt in group["options"]:
                text = opt["name"]
                if float(opt["extra_price"]) > 0:
                    text += f"  +{currency_symbol}{float(opt['extra_price']):.2f}"
                cb = QCheckBox(text)
                cb.setChecked(opt.get("is_default", False))
                cb.setStyleSheet(f"font-size:13px;color:{TEXT};padding:4px")
                cb.setProperty("opt", opt)
                self.checkboxes[group["id"]].append(cb)
                layout.addWidget(cb)

        btns = QHBoxLayout()
        cancel_btn = QPushButton(T["cancel"])
        cancel_btn.setStyleSheet(style_button(GRAY, WHITE, font_size=14))
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(T["add_to_cart"])
        ok_btn.setStyleSheet(style_button(font_size=14))
        ok_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def get_customizations(self):
        result = []
        for group_cbs in self.checkboxes.values():
            for cb in group_cbs:
                if cb.isChecked():
                    opt = cb.property("opt")
                    result.append({
                        "option_id":   opt["id"],
                        "option_name": opt["name"],
                        "extra_price": str(opt["extra_price"]),
                    })
        return result

# ── Idle video widget ─────────────────────────────────────────────────────────
class IdleVideoWidget(QWidget):
    """Full-screen looping video shown during idle. Requires python3-pyqt5.qtmultimedia."""

    def __init__(self, video_url, base_url, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:black")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video = QVideoWidget()
        layout.addWidget(self._video)

        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._video)
        self._player.mediaStatusChanged.connect(self._on_status)

        local_path = self._resolve(video_url, base_url)
        if local_path:
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(local_path)))
            self._player.play()
        else:
            log.warning("IdleVideoWidget: no video to play")

    def _resolve(self, url, base_url):
        if not url:
            return None
        full_url = url if url.startswith("http") else f"{base_url}{url}"
        try:
            resp = requests.get(full_url, timeout=30, stream=True)
            resp.raise_for_status()
            suffix = os.path.splitext(url)[-1] or ".mp4"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            for chunk in resp.iter_content(65536):
                tmp.write(chunk)
            tmp.close()
            log.info("IdleVideoWidget: video cached at %s", tmp.name)
            return tmp.name
        except Exception as e:
            log.error("IdleVideoWidget: failed to download video: %s", e)
            return None

    def _on_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def stop(self):
        self._player.stop()


# ── Main kiosk window ─────────────────────────────────────────────────────────
class KioskWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(T["window_title"])
        self.settings_data  = {}
        self.categories      = []
        self.items           = []
        self.cart            = []
        self.active_cat      = None
        self.currency_symbol = "€"
        self.idle_seconds    = 0
        self._retry_count    = 0

        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._idle_tick)
        self.idle_timer.start(1000)

        self._build_loading_screen("Connecting to server…")
        self._load_data()

        if FULLSCREEN:
            self.showFullScreen()
        else:
            self.resize(540, 960)

    # ── Loading / error screens ───────────────────────────────────────────────
    def _build_loading_screen(self, msg="Loading menu…"):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(20)
        icon = QLabel("🍽")
        icon.setStyleSheet("font-size:72px")
        icon.setAlignment(Qt.AlignCenter)
        lbl = QLabel(msg)
        lbl.setStyleSheet(f"font-size:22px;color:{TEXT}")
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(icon)
        v.addWidget(lbl)
        self.setCentralWidget(w)

    def _build_error_screen(self, msg):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(20)
        lbl = QLabel(f"⚠  {T['no_connection']}\n\n{msg}")
        lbl.setStyleSheet(f"font-size:18px;color:{RED}")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        retry_btn = QPushButton(T["retry"])
        retry_btn.setFixedWidth(200)
        retry_btn.setStyleSheet(style_button(font_size=16))
        retry_btn.clicked.connect(self._load_data)
        v.addWidget(lbl)
        v.addWidget(retry_btn, alignment=Qt.AlignCenter)
        self.setCentralWidget(w)

    # ── Data loading ──────────────────────────────────────────────────────────
    def _load_data(self):
        self._build_loading_screen("Connecting to server…")
        self.loader = DataLoader()
        self.loader.loaded.connect(self._on_data_loaded)
        self.loader.failed.connect(self._on_data_failed)
        self.loader.start()

    def _on_data_loaded(self, data):
        self._retry_count = 0
        self.settings_data  = data["settings"]
        self.categories      = data["categories"]
        self.items           = data["items"]
        self.currency_symbol = self.settings_data.get("currency_symbol", "€")

        # Apply language from server settings (overrides kiosk.ini)
        lang = self.settings_data.get("kiosk_language", "en")
        set_language(lang)
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if is_rtl() else Qt.LeftToRight
        )
        self.setWindowTitle(T["window_title"])
        log.info("Language set to '%s'", lang)
        log.info("UI built: %d categories", len(self.categories))
        self._build_main_ui()

    def _on_data_failed(self, msg):
        self._retry_count += 1
        log.warning("Connection failed (attempt %d): %s", self._retry_count, msg)
        self._build_error_screen(msg)
        delay = min(30, 5 * self._retry_count) * 1000
        QTimer.singleShot(delay, self._load_data)

    # ── Main UI ───────────────────────────────────────────────────────────────
    def _build_main_ui(self):
        s      = self.settings_data
        BG_C   = s.get("background_color", BG)
        PRI    = s.get("primary_color",    PRIMARY)
        FONT_S = int(s.get("font_size_base", 18))
        FONT_F = s.get("font_family", "Arial")

        root = QWidget()
        root.setStyleSheet(f"background:{BG_C};font-family:{FONT_F}")
        main_layout = QVBoxLayout(root)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ── TOP BANNER ────────────────────────────────────────────────────────
        banner = QFrame()
        banner.setFixedHeight(110)
        banner.setStyleSheet(f"background:{DARK}")
        b_layout = QHBoxLayout(banner)
        b_layout.setContentsMargins(20, 0, 20, 0)

        logo_lbl = QLabel()
        if s.get("logo_url"):
            try:
                resp = requests.get(f"{_active_base_url}{s['logo_url']}", timeout=3)
                pix  = QPixmap()
                pix.loadFromData(resp.content)
                logo_lbl.setPixmap(
                    pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            except Exception:
                logo_lbl.setText("🍽")
                logo_lbl.setStyleSheet("font-size:36px")
        else:
            logo_lbl.setText("🍽")
            logo_lbl.setStyleSheet("font-size:36px")
        b_layout.addWidget(logo_lbl)

        name_lbl = QLabel(s.get("restaurant_name", "Restaurant"))
        name_lbl.setStyleSheet(
            f"color:{PRI};font-size:{FONT_S+8}px;font-weight:900;letter-spacing:3px"
        )
        b_layout.addWidget(name_lbl)
        b_layout.addStretch()

        self.conn_dot = QLabel("●")
        self.conn_dot.setStyleSheet(f"color:{GREEN};font-size:18px;margin-right:8px")
        self.conn_dot.setToolTip("Server connection status")
        b_layout.addWidget(self.conn_dot)

        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet("color:white;font-size:14px")
        self._update_clock()
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start(10000)
        b_layout.addWidget(self.clock_lbl)

        main_layout.addWidget(banner)

        # ── BODY ──────────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        cat_frame = QFrame()
        cat_frame.setFixedWidth(160)
        cat_frame.setStyleSheet(f"background:#F0F0F0;border-right:1px solid {LIGHT_GRAY}")
        cat_v = QVBoxLayout(cat_frame)
        cat_v.setContentsMargins(0, 10, 0, 10)
        cat_v.setSpacing(4)

        self.cat_buttons = {}
        for cat in self.categories:
            btn = QPushButton(cat["name"])
            btn.setCheckable(True)
            btn.setFixedHeight(56)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:transparent;border:none;font-size:14px;
                    color:{TEXT};border-left:4px solid transparent;
                    padding:0 10px;text-align:left
                }}
                QPushButton:checked {{
                    background:{PRI}22;border-left-color:{PRI};
                    color:{PRI};font-weight:bold
                }}
                QPushButton:hover {{ background:{PRI}11 }}
            """)
            btn.clicked.connect(lambda _, c=cat: self._select_category(c["id"]))
            self.cat_buttons[cat["id"]] = btn
            cat_v.addWidget(btn)
        cat_v.addStretch()
        body.addWidget(cat_frame)

        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items_scroll.setStyleSheet("border:none")
        body.addWidget(self.items_scroll, 1)

        main_layout.addLayout(body, 1)

        # ── CART BAR ──────────────────────────────────────────────────────────
        self.cart_bar = QFrame()
        self.cart_bar.setFixedHeight(220)
        self.cart_bar.setStyleSheet(f"background:{WHITE};border-top:2px solid {LIGHT_GRAY}")
        cart_main = QVBoxLayout(self.cart_bar)
        cart_main.setContentsMargins(16, 10, 16, 10)
        cart_main.setSpacing(6)

        cart_title = QLabel(T["your_order"])
        cart_title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{TEXT}")
        cart_main.addWidget(cart_title)

        self.cart_scroll = QScrollArea()
        self.cart_scroll.setWidgetResizable(True)
        self.cart_scroll.setFixedHeight(100)
        self.cart_scroll.setStyleSheet("border:none")
        cart_main.addWidget(self.cart_scroll)

        bottom_row = QHBoxLayout()
        self.total_lbl = QLabel(f"{T['total']}: {self.currency_symbol}0.00")
        self.total_lbl.setStyleSheet(f"font-size:18px;font-weight:bold;color:{PRI}")
        bottom_row.addWidget(self.total_lbl)
        bottom_row.addStretch()

        clear_btn = QPushButton(T["clear_cart"])
        clear_btn.setStyleSheet(style_button(GRAY, WHITE, font_size=14))
        clear_btn.clicked.connect(self._clear_cart)
        bottom_row.addWidget(clear_btn)

        self.checkout_btn = QPushButton(T["place_order"])
        self.checkout_btn.setStyleSheet(style_button(font_size=16))
        self.checkout_btn.setEnabled(False)
        self.checkout_btn.clicked.connect(self._place_order)
        bottom_row.addWidget(self.checkout_btn)

        cart_main.addLayout(bottom_row)
        main_layout.addWidget(self.cart_bar)

        self.setCentralWidget(root)

        if self.categories:
            self._select_category(self.categories[0]["id"])

    # ── Category selection ────────────────────────────────────────────────────
    def _select_category(self, cat_id):
        self.active_cat = cat_id
        self._reset_idle()
        log.debug("Category selected: %s", cat_id)
        for cid, btn in self.cat_buttons.items():
            btn.setChecked(cid == cat_id)
        filtered = [i for i in self.items
                    if i.get("category_id") == cat_id and i.get("is_available")]
        self._render_items(filtered)

    def _render_items(self, items):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(14)
        grid.setContentsMargins(14, 14, 14, 14)
        cols = 3
        for idx, item in enumerate(items):
            card = ItemCard(item, self.currency_symbol)
            card.add_clicked.connect(self._add_to_cart)
            grid.addWidget(card, idx // cols, idx % cols)
        if items:
            rem = len(items) % cols
            if rem:
                for i in range(cols - rem):
                    spacer = QWidget()
                    spacer.setFixedSize(200, 240)
                    grid.addWidget(spacer, len(items) // cols, rem + i)
        self.items_scroll.setWidget(container)

    # ── Cart operations ───────────────────────────────────────────────────────
    def _add_to_cart(self, item):
        self._reset_idle()
        customizations = []
        if item.get("customization_groups"):
            dlg = CustomizeDialog(item, self.currency_symbol, self)
            if dlg.exec_() == QDialog.Accepted:
                customizations = dlg.get_customizations()
            else:
                return

        extra = sum(float(c["extra_price"]) for c in customizations)
        entry = {
            "item_id":        item["id"],
            "name":           item["name"],
            "unit_price":     float(item["price"]) + extra,
            "quantity":       1,
            "customizations": customizations,
        }
        key = (item["id"], json.dumps(customizations, sort_keys=True))
        for e in self.cart:
            if (e["item_id"], json.dumps(e["customizations"], sort_keys=True)) == key:
                e["quantity"] += 1
                log.debug("Cart: qty++ %s (total %d)", item["name"], e["quantity"])
                self._refresh_cart()
                return
        self.cart.append(entry)
        log.debug("Cart: added %s", item["name"])
        self._refresh_cart()

    def _remove_from_cart(self, idx):
        self._reset_idle()
        if 0 <= idx < len(self.cart):
            name = self.cart[idx]["name"]
            if self.cart[idx]["quantity"] > 1:
                self.cart[idx]["quantity"] -= 1
            else:
                self.cart.pop(idx)
            log.debug("Cart: removed/decremented %s", name)
        self._refresh_cart()

    def _clear_cart(self):
        log.debug("Cart cleared (%d items)", len(self.cart))
        self.cart.clear()
        self._refresh_cart()

    def _refresh_cart(self):
        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(4)
        v.setContentsMargins(0, 0, 0, 0)
        for idx, entry in enumerate(self.cart):
            row = CartRow(entry, idx, self.currency_symbol)
            row.remove_clicked.connect(self._remove_from_cart)
            v.addWidget(row)
        v.addStretch()
        self.cart_scroll.setWidget(container)
        total = sum(e["unit_price"] * e["quantity"] for e in self.cart)
        self.total_lbl.setText(f"{T['total']}: {self.currency_symbol}{total:.2f}")
        self.checkout_btn.setEnabled(bool(self.cart))

    # ── Order placement ───────────────────────────────────────────────────────
    def _place_order(self):
        self._reset_idle()
        if not self.cart:
            return

        items_summary = ", ".join(
            f"{e['quantity']}×{e['name']}" for e in self.cart
        )
        log.info("Placing order: %s", items_summary)

        self.checkout_btn.setEnabled(False)
        self.checkout_btn.setText(T["sending"])

        payload = {
            "payment_method": "card",
            "lines": [
                {
                    "item_id":        e["item_id"],
                    "name":           e["name"],
                    "unit_price":     str(e["unit_price"]),
                    "quantity":       e["quantity"],
                    "customizations": e["customizations"],
                }
                for e in self.cart
            ],
        }
        self._submitter = OrderSubmitter(payload)
        self._submitter.success.connect(self._on_order_success)
        self._submitter.failed.connect(self._on_order_failed)
        self._submitter.start()

    def _on_order_success(self, result):
        queue_num = result.get("queue_number", "?")
        total     = float(result.get("total_amount", 0))
        log.info("Order confirmed  queue=#%04d  total=%s%.2f",
                 queue_num, self.currency_symbol, total)
        self._clear_cart()
        self.checkout_btn.setText(T["place_order"])
        self.checkout_btn.setEnabled(False)
        self._show_confirmation(queue_num, total)

    def _on_order_failed(self, msg):
        log.error("Order failed: %s", msg)
        self.checkout_btn.setText(T["place_order"])
        self.checkout_btn.setEnabled(True)
        QMessageBox.critical(self, T["order_failed_title"],
                             f"{T['order_failed_msg']}\n\n{msg}")

    def _show_confirmation(self, queue_number, total):
        dlg = QDialog(self)
        dlg.setWindowTitle(T["order_confirmed"])
        dlg.setMinimumSize(380, 340)
        dlg.setStyleSheet(f"background:{WHITE}")
        v = QVBoxLayout(dlg)
        v.setSpacing(16)
        v.setContentsMargins(30, 30, 30, 30)

        v.addWidget(QLabel("✅", alignment=Qt.AlignCenter,
                           styleSheet="font-size:48px"))
        title = QLabel(T["order_placed"])
        title.setStyleSheet(f"font-size:22px;font-weight:bold;color:{PRIMARY}")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        v.addWidget(QLabel(T["your_number"], alignment=Qt.AlignCenter,
                           styleSheet=f"font-size:14px;color:{TEXT}"))
        big = QLabel(f"#{queue_number:04d}")
        big.setAlignment(Qt.AlignCenter)
        big.setStyleSheet(f"font-size:56px;font-weight:900;color:{PRIMARY}")
        v.addWidget(big)

        v.addWidget(QLabel(f"{T['total']}: {self.currency_symbol}{total:.2f}",
                           alignment=Qt.AlignCenter,
                           styleSheet=f"font-size:16px;color:{TEXT}"))

        close_btn = QPushButton(T["new_order"])
        close_btn.setStyleSheet(style_button(font_size=15))
        close_btn.clicked.connect(dlg.accept)
        v.addWidget(close_btn)

        QTimer.singleShot(30000, dlg.accept)  # auto-close after 30s
        dlg.exec_()

    # ── Idle reset ────────────────────────────────────────────────────────────
    def _reset_idle(self):
        self.idle_seconds = 0

    def _idle_tick(self):
        self.idle_seconds += 1
        timeout = self.settings_data.get("idle_timeout_sec", IDLE_TIMEOUT)
        if self.idle_seconds >= timeout:
            if self.cart:
                log.info("Idle timeout — cart cleared")
                self._clear_cart()
            self._show_idle_screen()
            self.idle_seconds = 0

    def _show_idle_screen(self):
        if isinstance(self.centralWidget(), IdleVideoWidget):
            return
        video_url = self.settings_data.get("waiting_video_url")
        if video_url and _QT_MULTIMEDIA:
            widget = IdleVideoWidget(video_url, _active_base_url, self)
            self.setCentralWidget(widget)
            log.info("Idle screen: video started")
        else:
            if not _QT_MULTIMEDIA and video_url:
                log.warning("QtMultimedia unavailable — idle video disabled")
            self._build_loading_screen("Touch screen to order")

    def _hide_idle_screen(self):
        if isinstance(self.centralWidget(), IdleVideoWidget):
            self.centralWidget().stop()
            if self.categories:
                self._build_main_ui()
            else:
                self._load_data()
            log.info("Idle screen dismissed")

    def _update_clock(self):
        if hasattr(self, "clock_lbl"):
            self.clock_lbl.setText(datetime.now().strftime("%d/%m/%Y  %H:%M"))

    def mousePressEvent(self, event):
        self._reset_idle()
        self._hide_idle_screen()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F12:
            log.info("F12 pressed — exiting kiosk")
            QApplication.quit()
        elif event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("QApplication starting")
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    window = KioskWindow()
    if not FULLSCREEN:
        window.show()

    exit_code = app.exec_()
    log.info("Kiosk exiting (code %d)", exit_code)
    sys.exit(exit_code)
