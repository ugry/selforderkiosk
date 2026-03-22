"""
Kiosk UI translations.
Usage:
    from translations import set_language, T, is_rtl
    set_language("tr")
    label = T["place_order"]   # → "Sipariş Ver"
    if is_rtl(): app.setLayoutDirection(Qt.RightToLeft)
"""

# Each language entry is (strings_dict, rtl_flag)
_LANGS: dict[str, tuple[dict[str, str], bool]] = {

    # ── English ───────────────────────────────────────────────────────────────
    "en": ({
        "window_title":       "Restaurant Kiosk",
        "touch_to_order":     "Touch to order",
        "your_order":         "Your Order",
        "total":              "Total",
        "add_btn":            "+ Add",
        "promo_badge":        "★ PROMO",
        "cancel":             "Cancel",
        "add_to_cart":        "Add to Cart",
        "clear_cart":         "🗑  Clear",
        "place_order":        "✓  Place Order",
        "sending":            "Sending…",
        "retry":              "Retry now",
        "no_connection":      "Cannot reach server",
        "order_confirmed":    "Order Confirmed!",
        "order_placed":       "Order Placed!",
        "your_number":        "Your number",
        "new_order":          "Start New Order",
        "order_failed_title": "Order Failed",
        "order_failed_msg":   "Could not send order. Please try again.",
        "required_suffix":    " *",
        "cart_empty":         "Your cart is empty",
        "customise_title":    "Customise",
        "tax_label":          "incl. tax",
    }, False),

    # ── Turkish ───────────────────────────────────────────────────────────────
    "tr": ({
        "window_title":       "Restoran Kiosk",
        "touch_to_order":     "Sipariş vermek için dokunun",
        "your_order":         "Siparişiniz",
        "total":              "Toplam",
        "add_btn":            "+ Ekle",
        "promo_badge":        "★ PROMOSYON",
        "cancel":             "İptal",
        "add_to_cart":        "Sepete Ekle",
        "clear_cart":         "🗑  Temizle",
        "place_order":        "✓  Sipariş Ver",
        "sending":            "Gönderiliyor…",
        "retry":              "Tekrar dene",
        "no_connection":      "Sunucuya ulaşılamıyor",
        "order_confirmed":    "Sipariş Onaylandı!",
        "order_placed":       "Sipariş Verildi!",
        "your_number":        "Sipariş numaranız",
        "new_order":          "Yeni Sipariş",
        "order_failed_title": "Sipariş Başarısız",
        "order_failed_msg":   "Sipariş gönderilemedi. Lütfen tekrar deneyin.",
        "required_suffix":    " *",
        "cart_empty":         "Sepetiniz boş",
        "customise_title":    "Özelleştir",
        "tax_label":          "KDV dahil",
    }, False),

    # ── German ────────────────────────────────────────────────────────────────
    "de": ({
        "window_title":       "Restaurant Kiosk",
        "touch_to_order":     "Zum Bestellen berühren",
        "your_order":         "Ihre Bestellung",
        "total":              "Gesamt",
        "add_btn":            "+ Hinzufügen",
        "promo_badge":        "★ ANGEBOT",
        "cancel":             "Abbrechen",
        "add_to_cart":        "In den Warenkorb",
        "clear_cart":         "🗑  Leeren",
        "place_order":        "✓  Bestellen",
        "sending":            "Wird gesendet…",
        "retry":              "Erneut versuchen",
        "no_connection":      "Server nicht erreichbar",
        "order_confirmed":    "Bestellung bestätigt!",
        "order_placed":       "Bestellung aufgegeben!",
        "your_number":        "Ihre Nummer",
        "new_order":          "Neue Bestellung",
        "order_failed_title": "Bestellung fehlgeschlagen",
        "order_failed_msg":   "Bestellung konnte nicht gesendet werden. Bitte erneut versuchen.",
        "required_suffix":    " *",
        "cart_empty":         "Ihr Warenkorb ist leer",
        "customise_title":    "Anpassen",
        "tax_label":          "inkl. MwSt.",
    }, False),

    # ── Hungarian ─────────────────────────────────────────────────────────────
    "hu": ({
        "window_title":       "Éttermi Kiosk",
        "touch_to_order":     "Érintse meg a rendeléshez",
        "your_order":         "Rendelése",
        "total":              "Összesen",
        "add_btn":            "+ Hozzáad",
        "promo_badge":        "★ AKCIÓ",
        "cancel":             "Mégse",
        "add_to_cart":        "Kosárba tesz",
        "clear_cart":         "🗑  Törlés",
        "place_order":        "✓  Rendelés leadása",
        "sending":            "Küldés…",
        "retry":              "Újrapróbálkozás",
        "no_connection":      "A szerver nem elérhető",
        "order_confirmed":    "Rendelés megerősítve!",
        "order_placed":       "Rendelés leadva!",
        "your_number":        "Az Ön száma",
        "new_order":          "Új rendelés",
        "order_failed_title": "Rendelés sikertelen",
        "order_failed_msg":   "A rendelés nem küldhető el. Kérjük, próbálja újra.",
        "required_suffix":    " *",
        "cart_empty":         "A kosár üres",
        "customise_title":    "Testreszabás",
        "tax_label":          "ÁFA-val",
    }, False),

    # ── Spanish ───────────────────────────────────────────────────────────────
    "es": ({
        "window_title":       "Kiosco de Restaurante",
        "touch_to_order":     "Toca para pedir",
        "your_order":         "Tu Pedido",
        "total":              "Total",
        "add_btn":            "+ Añadir",
        "promo_badge":        "★ PROMO",
        "cancel":             "Cancelar",
        "add_to_cart":        "Añadir al carrito",
        "clear_cart":         "🗑  Vaciar",
        "place_order":        "✓  Hacer Pedido",
        "sending":            "Enviando…",
        "retry":              "Reintentar",
        "no_connection":      "No se puede conectar al servidor",
        "order_confirmed":    "¡Pedido Confirmado!",
        "order_placed":       "¡Pedido Realizado!",
        "your_number":        "Tu número",
        "new_order":          "Nuevo Pedido",
        "order_failed_title": "Error en el Pedido",
        "order_failed_msg":   "No se pudo enviar el pedido. Por favor, inténtelo de nuevo.",
        "required_suffix":    " *",
        "cart_empty":         "Tu carrito está vacío",
        "customise_title":    "Personalizar",
        "tax_label":          "IVA incluido",
    }, False),

    # ── French ────────────────────────────────────────────────────────────────
    "fr": ({
        "window_title":       "Borne de Commande",
        "touch_to_order":     "Appuyez pour commander",
        "your_order":         "Votre Commande",
        "total":              "Total",
        "add_btn":            "+ Ajouter",
        "promo_badge":        "★ PROMO",
        "cancel":             "Annuler",
        "add_to_cart":        "Ajouter au panier",
        "clear_cart":         "🗑  Vider",
        "place_order":        "✓  Commander",
        "sending":            "Envoi en cours…",
        "retry":              "Réessayer",
        "no_connection":      "Impossible de joindre le serveur",
        "order_confirmed":    "Commande Confirmée !",
        "order_placed":       "Commande Passée !",
        "your_number":        "Votre numéro",
        "new_order":          "Nouvelle Commande",
        "order_failed_title": "Échec de la Commande",
        "order_failed_msg":   "Impossible d'envoyer la commande. Veuillez réessayer.",
        "required_suffix":    " *",
        "cart_empty":         "Votre panier est vide",
        "customise_title":    "Personnaliser",
        "tax_label":          "TVA incluse",
    }, False),

    # ── Russian ───────────────────────────────────────────────────────────────
    "ru": ({
        "window_title":       "Киоск ресторана",
        "touch_to_order":     "Нажмите для заказа",
        "your_order":         "Ваш заказ",
        "total":              "Итого",
        "add_btn":            "+ Добавить",
        "promo_badge":        "★ АКЦИЯ",
        "cancel":             "Отмена",
        "add_to_cart":        "В корзину",
        "clear_cart":         "🗑  Очистить",
        "place_order":        "✓  Заказать",
        "sending":            "Отправка…",
        "retry":              "Повторить",
        "no_connection":      "Сервер недоступен",
        "order_confirmed":    "Заказ подтверждён!",
        "order_placed":       "Заказ оформлен!",
        "your_number":        "Ваш номер",
        "new_order":          "Новый заказ",
        "order_failed_title": "Ошибка заказа",
        "order_failed_msg":   "Не удалось отправить заказ. Пожалуйста, попробуйте снова.",
        "required_suffix":    " *",
        "cart_empty":         "Корзина пуста",
        "customise_title":    "Настроить",
        "tax_label":          "включая НДС",
    }, False),

    # ── Arabic ────────────────────────────────────────────────────────────────
    # RTL language — kiosk.py applies Qt.RightToLeft layout direction when active
    "ar": ({
        "window_title":       "كشك المطعم",
        "touch_to_order":     "المسّ للطلب",
        "your_order":         "طلبك",
        "total":              "المجموع",
        "add_btn":            "أضف +",
        "promo_badge":        "★ عرض",
        "cancel":             "إلغاء",
        "add_to_cart":        "أضف للسلة",
        "clear_cart":         "🗑  إفراغ",
        "place_order":        "✓  تأكيد الطلب",
        "sending":            "جارٍ الإرسال…",
        "retry":              "إعادة المحاولة",
        "no_connection":      "تعذّر الاتصال بالخادم",
        "order_confirmed":    "تم تأكيد الطلب!",
        "order_placed":       "تم تقديم الطلب!",
        "your_number":        "رقمك",
        "new_order":          "طلب جديد",
        "order_failed_title": "فشل الطلب",
        "order_failed_msg":   "تعذّر إرسال الطلب. يرجى المحاولة مرة أخرى.",
        "required_suffix":    " *",
        "cart_empty":         "سلة التسوق فارغة",
        "customise_title":    "تخصيص",
        "tax_label":          "شامل الضريبة",
    }, True),  # ← RTL
}

# Active translation dict — starts as English
T: dict[str, str] = dict(_LANGS["en"][0])
_current_lang = "en"
_current_rtl  = False


def set_language(code: str) -> None:
    """Switch active translation. Falls back to English for unknown codes."""
    global T, _current_lang, _current_rtl
    lang = (code or "en").lower().strip()
    if lang not in _LANGS:
        lang = "en"
    strings, rtl = _LANGS[lang]
    _current_lang = lang
    _current_rtl  = rtl
    T.clear()
    T.update(strings)


def is_rtl() -> bool:
    """Return True when the active language is right-to-left (e.g. Arabic)."""
    return _current_rtl


def current_language() -> str:
    return _current_lang


SUPPORTED: dict[str, str] = {
    "en": "English",
    "tr": "Türkçe",
    "de": "Deutsch",
    "hu": "Magyar",
    "es": "Español",
    "fr": "Français",
    "ru": "Русский",
    "ar": "العربية",
}
