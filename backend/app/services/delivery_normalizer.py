"""
delivery_normalizer.py
======================
Normalizes incoming webhook payloads from food-delivery platforms
(Wolt, Foodpanda, Uber Eats, Just Eat, Generic) into a single
internal NormalizedOrder structure.

Each platform sends a different JSON schema; the adapters here
translate them before the webhooks router persists the order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

log = logging.getLogger("app.integrations")


# ── Internal normalized structures ────────────────────────────────────────────

@dataclass
class NormalizedItem:
    name:       str
    quantity:   int
    unit_price: float           # already in major currency units (e.g. EUR not cents)
    options:    List[str] = field(default_factory=list)   # option names as plain strings


@dataclass
class NormalizedOrder:
    platform:           str
    external_order_id:  str
    customer_name:      str
    items:              List[NormalizedItem]
    subtotal:           float
    delivery_notes:     str = ""
    payment_method:     str = "online"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cents_to_major(amount: Any, divisor: int = 100) -> float:
    """Convert integer cents/minor units to major currency units."""
    try:
        return round(int(amount) / divisor, 2)
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


# ── Wolt ──────────────────────────────────────────────────────────────────────
# Wolt sends amounts in cents (integer).
# Payload reference: https://developer.wolt.com/docs/merchant-api/webhooks
#
# {
#   "type": "order.created",
#   "order": {
#     "id": "...",
#     "items": [{"name":"Burger","count":2,"base_price":{"amount":850,"currency":"EUR"}}],
#     "consumer": {"name": "John Doe"},
#     "delivery": {"comment": "Ring the bell"},
#     "price": {"amount": 1700, "currency": "EUR"}
#   }
# }

def normalize_wolt(payload: Dict) -> NormalizedOrder:
    order = payload.get("order") or payload  # some versions wrap, some don't
    items_raw = order.get("items", [])

    items: List[NormalizedItem] = []
    for it in items_raw:
        price_obj  = it.get("base_price") or it.get("unit_price") or {}
        unit_cents = price_obj.get("amount", 0) if isinstance(price_obj, dict) else 0
        options    = [opt.get("name", "") for opt in it.get("options", [])]
        items.append(NormalizedItem(
            name       = it.get("name", "Unknown item"),
            quantity   = int(it.get("count", it.get("quantity", 1))),
            unit_price = _cents_to_major(unit_cents),
            options    = options,
        ))

    price_obj = order.get("price", {})
    subtotal  = _cents_to_major(price_obj.get("amount", 0)) if isinstance(price_obj, dict) else 0.0
    consumer  = order.get("consumer") or {}
    delivery  = order.get("delivery") or {}

    return NormalizedOrder(
        platform          = "wolt",
        external_order_id = str(order.get("id", "")),
        customer_name     = consumer.get("name", ""),
        items             = items,
        subtotal          = subtotal,
        delivery_notes    = delivery.get("comment", ""),
        payment_method    = "online",
    )


# ── Foodpanda / Delivery Hero ─────────────────────────────────────────────────
# Foodpanda amounts are decimal strings or floats in major units.
#
# {
#   "event": "order.placed",
#   "order": {
#     "id": "...",
#     "customer": {"name": "Jane"},
#     "items": [{"name":"Pizza","quantity":1,"price":"12.50",
#                "variations":[{"name":"Extra cheese","price":"1.00"}]}],
#     "special_instructions": "No onions",
#     "subtotal": "12.50"
#   }
# }

def normalize_foodpanda(payload: Dict) -> NormalizedOrder:
    order = payload.get("order") or payload
    items_raw = order.get("items", order.get("products", []))

    items: List[NormalizedItem] = []
    for it in items_raw:
        options = [v.get("name", "") for v in it.get("variations", it.get("options", []))]
        items.append(NormalizedItem(
            name       = it.get("name", "Unknown item"),
            quantity   = int(it.get("quantity", it.get("count", 1))),
            unit_price = _safe_float(it.get("price", it.get("unit_price", 0))),
            options    = options,
        ))

    customer = order.get("customer") or {}
    subtotal = _safe_float(order.get("subtotal", order.get("total", 0)))
    note     = order.get("special_instructions", order.get("notes", ""))

    return NormalizedOrder(
        platform          = "foodpanda",
        external_order_id = str(order.get("id", order.get("order_id", ""))),
        customer_name     = customer.get("name", customer.get("first_name", "")),
        items             = items,
        subtotal          = subtotal,
        delivery_notes    = note,
        payment_method    = "online",
    )


# ── Uber Eats ─────────────────────────────────────────────────────────────────
# Uber Eats amounts are in cents.
#
# {
#   "event_type": "orders.notification",
#   "order_id": "...",
#   "order": {
#     "id": "...",
#     "items": [{"title":"Wrap","quantity":1,
#                "price":{"unit_price":{"base":950}},
#                "selected_modifier_groups":[
#                    {"modifiers":[{"title":"Sauce","price":{"base":0}}]}
#                ]}],
#     "special_instructions": "Mild sauce",
#     "cart": {"sub_total": {"total_money": {"amount": 950}}}
#   }
# }

def normalize_ubereats(payload: Dict) -> NormalizedOrder:
    order = payload.get("order") or payload
    items_raw = order.get("items", [])

    items: List[NormalizedItem] = []
    for it in items_raw:
        price_obj  = it.get("price", {}) or {}
        unit_obj   = price_obj.get("unit_price", {}) or {}
        unit_cents = unit_obj.get("base", unit_obj.get("amount", 0))

        options: List[str] = []
        for mg in it.get("selected_modifier_groups", []):
            for mod in mg.get("modifiers", []):
                name = mod.get("title") or mod.get("name")
                if name:
                    options.append(name)

        items.append(NormalizedItem(
            name       = it.get("title", it.get("name", "Unknown item")),
            quantity   = int(it.get("quantity", 1)),
            unit_price = _cents_to_major(unit_cents),
            options    = options,
        ))

    # subtotal from cart or top-level
    subtotal = 0.0
    cart = order.get("cart") or {}
    sub  = cart.get("sub_total") or cart.get("subtotal") or {}
    if isinstance(sub, dict):
        money = sub.get("total_money") or sub.get("amount_money") or {}
        subtotal = _cents_to_major(money.get("amount", 0)) if isinstance(money, dict) else _safe_float(sub)
    else:
        subtotal = _safe_float(order.get("price", {}).get("total_charge", 0))

    return NormalizedOrder(
        platform          = "ubereats",
        external_order_id = str(order.get("id", payload.get("order_id", ""))),
        customer_name     = "",   # Uber Eats doesn't share customer name in webhooks
        items             = items,
        subtotal          = subtotal,
        delivery_notes    = order.get("special_instructions", ""),
        payment_method    = "online",
    )


# ── Just Eat / Takeaway ───────────────────────────────────────────────────────
# Just Eat amounts are in major units (floats/decimals).
#
# {
#   "order": {
#     "id": "...",
#     "friendlyOrderReference": "JE123",
#     "customer": {"name": "Bob"},
#     "orderLines": [
#       {"name":"Fish","quantity":1,"unitPrice":8.99,
#        "extras":[{"groupName":"Sauce","name":"Curry","price":0.50}]}
#     ],
#     "notes": "Extra napkins",
#     "total": 9.49
#   }
# }

def normalize_justeat(payload: Dict) -> NormalizedOrder:
    order = payload.get("order") or payload
    items_raw = order.get("orderLines", order.get("items", []))

    items: List[NormalizedItem] = []
    for it in items_raw:
        options = []
        for ex in it.get("extras", it.get("options", [])):
            name = ex.get("name", ex.get("optionName", ""))
            if name:
                options.append(name)
        items.append(NormalizedItem(
            name       = it.get("name", "Unknown item"),
            quantity   = int(it.get("quantity", 1)),
            unit_price = _safe_float(it.get("unitPrice", it.get("unit_price", 0))),
            options    = options,
        ))

    customer = order.get("customer") or {}
    subtotal = _safe_float(order.get("total", order.get("subtotal", 0)))

    return NormalizedOrder(
        platform          = "justeat",
        external_order_id = str(order.get("id", order.get("friendlyOrderReference", ""))),
        customer_name     = customer.get("name", customer.get("firstName", "")),
        items             = items,
        subtotal          = subtotal,
        delivery_notes    = order.get("notes", order.get("comment", "")),
        payment_method    = "online",
    )


# ── Generic webhook ───────────────────────────────────────────────────────────
# Accepts a simple, documented format that any system can POST:
#
# {
#   "order_id":       "custom-123",         (required)
#   "customer_name":  "Alice",              (optional)
#   "items": [                              (required)
#     {"name": "Burger", "quantity": 2, "unit_price": 8.50,
#      "options": ["Extra cheese"]}
#   ],
#   "subtotal":       17.00,               (optional – computed if absent)
#   "notes":          "No pickles",        (optional)
#   "payment_method": "cash"               (optional)
# }

def normalize_generic(payload: Dict) -> NormalizedOrder:
    items_raw = payload.get("items", [])
    items: List[NormalizedItem] = []
    for it in items_raw:
        items.append(NormalizedItem(
            name       = it.get("name", "Unknown item"),
            quantity   = int(it.get("quantity", it.get("qty", 1))),
            unit_price = _safe_float(it.get("unit_price", it.get("price", 0))),
            options    = it.get("options", []),
        ))

    subtotal = _safe_float(payload.get("subtotal", 0))
    if not subtotal:
        subtotal = round(sum(i.unit_price * i.quantity for i in items), 2)

    return NormalizedOrder(
        platform          = "generic",
        external_order_id = str(payload.get("order_id", payload.get("id", ""))),
        customer_name     = payload.get("customer_name", payload.get("customer", "")),
        items             = items,
        subtotal          = subtotal,
        delivery_notes    = payload.get("notes", payload.get("delivery_notes", "")),
        payment_method    = payload.get("payment_method", "online"),
    )


# ── Router ────────────────────────────────────────────────────────────────────

_ADAPTERS = {
    "wolt":      normalize_wolt,
    "foodpanda": normalize_foodpanda,
    "ubereats":  normalize_ubereats,
    "justeat":   normalize_justeat,
    "generic":   normalize_generic,
}


def normalize(platform: str, payload: Dict) -> Optional[NormalizedOrder]:
    """
    Dispatch to the right adapter.  Returns None for unknown platforms.
    """
    fn = _ADAPTERS.get(platform)
    if fn is None:
        log.warning("No adapter for platform '%s'", platform)
        return None
    try:
        return fn(payload)
    except Exception:
        log.exception("Failed to normalize %s payload", platform)
        return None
