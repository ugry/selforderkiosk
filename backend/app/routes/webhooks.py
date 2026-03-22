"""
webhooks.py
===========
Inbound webhook endpoints for food-delivery platforms.

Each platform gets its own endpoint so the correct HMAC signature
algorithm can be applied.  If a webhook_secret is configured for the
platform, the request signature is verified before the order is saved.

Endpoints:
  POST /webhooks/wolt
  POST /webhooks/foodpanda
  POST /webhooks/ubereats
  POST /webhooks/justeat
  POST /webhooks/generic     ← documented generic format

All endpoints return HTTP 200 regardless of processing errors so the
platform does not retry indefinitely.  Errors are logged to error.log.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.models import Order, OrderItem, OrderItemCustomization, DeliveryIntegration
from app.services.delivery_normalizer import normalize, NormalizedOrder
from app.services.printer import print_kitchen_ticket

log = logging.getLogger("app.integrations")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _verify_hmac_sha256(secret: str, body: bytes, signature: str) -> bool:
    """
    Verify that `signature` matches HMAC-SHA256(secret, body).
    Accepts signatures with or without a 'sha256=' prefix.
    """
    sig = signature.lstrip("sha256=").lstrip("v1=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()  # type: ignore[attr-defined]
    return hmac.compare_digest(expected, sig)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _get_integration(db: AsyncSession, platform: str) -> Optional[DeliveryIntegration]:
    result = await db.execute(
        select(DeliveryIntegration).where(DeliveryIntegration.platform == platform)
    )
    return result.scalar_one_or_none()


async def _persist_order(db: AsyncSession, norm: NormalizedOrder, tax_rate: float) -> Optional[Order]:
    """
    Insert a NormalizedOrder into the database.
    Returns the created Order, or None if it's a duplicate.
    """
    subtotal     = round(norm.subtotal, 2)
    tax_amount   = round(subtotal * tax_rate / 100, 2)
    total_amount = round(subtotal + tax_amount, 2)

    order = Order(
        source            = norm.platform,
        external_order_id = norm.external_order_id or None,
        customer_name     = norm.customer_name or None,
        delivery_notes    = norm.delivery_notes or None,
        status            = "pending",
        subtotal          = Decimal(str(subtotal)),
        tax_amount        = Decimal(str(tax_amount)),
        total_amount      = Decimal(str(total_amount)),
        payment_method    = norm.payment_method,
        payment_status    = "paid",   # delivery platform orders are pre-paid
        note              = norm.delivery_notes or None,
    )
    db.add(order)
    try:
        await db.flush()   # get the order.id + queue_number without committing
    except IntegrityError:
        await db.rollback()
        log.warning(
            "Duplicate order ignored  platform=%s  external_id=%s",
            norm.platform, norm.external_order_id,
        )
        return None

    for item in norm.items:
        unit_price = Decimal(str(round(item.unit_price, 2)))
        line_total = unit_price * item.quantity
        oi = OrderItem(
            order_id   = order.id,
            name       = item.name,
            unit_price = unit_price,
            quantity   = item.quantity,
            line_total = line_total,
        )
        db.add(oi)
        # Options stored as customization entries (text only, no price lookup)
        await db.flush()
        if item.options:
            from app.models.models import OrderItemCustomization
            for opt_name in item.options:
                db.add(OrderItemCustomization(
                    order_item_id = oi.id,
                    option_name   = opt_name,
                    extra_price   = Decimal("0"),
                ))

    await db.commit()
    await db.refresh(order)
    return order


async def _get_tax_rate(db: AsyncSession) -> float:
    result = await db.execute(text("SELECT tax_rate FROM settings LIMIT 1"))
    row    = result.fetchone()
    return float(row[0]) if row else 0.0


# ── Core handler ─────────────────────────────────────────────────────────────

async def _handle_webhook(
    platform:       str,
    request:        Request,
    sig_header:     Optional[str],
) -> Response:
    body = await request.body()

    # Obtain a DB session manually (not via Depends, we return early on errors)
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        integration = await _get_integration(db, platform)

        if integration is None or not integration.enabled:
            log.info("Webhook received but platform '%s' is disabled – ignored", platform)
            return Response(content='{"status":"ignored"}', media_type="application/json")

        # Signature verification
        if integration.webhook_secret:
            if not sig_header:
                log.warning("WEBHOOK AUTH FAIL  platform=%s  reason=missing_signature", platform)
                return Response(
                    content='{"status":"unauthorized"}',
                    media_type="application/json",
                    status_code=401,
                )
            if not _verify_hmac_sha256(integration.webhook_secret, body, sig_header):
                log.warning("WEBHOOK AUTH FAIL  platform=%s  reason=invalid_signature", platform)
                return Response(
                    content='{"status":"unauthorized"}',
                    media_type="application/json",
                    status_code=401,
                )

        # Parse JSON
        try:
            payload = json.loads(body)
        except Exception:
            log.error("WEBHOOK  platform=%s  bad JSON body", platform)
            return Response(content='{"status":"bad_request"}', media_type="application/json", status_code=400)

        # Normalize
        norm = normalize(platform, payload)
        if norm is None:
            log.error("WEBHOOK  platform=%s  normalization failed", platform)
            return Response(content='{"status":"error"}', media_type="application/json")

        log.info(
            "WEBHOOK IN  platform=%s  external_id=%s  items=%d  total=%.2f",
            platform, norm.external_order_id, len(norm.items), norm.subtotal,
        )

        # Persist
        tax_rate = await _get_tax_rate(db)
        order    = await _persist_order(db, norm, tax_rate)
        if order is None:
            return Response(content='{"status":"duplicate"}', media_type="application/json")

        log.info(
            "WEBHOOK SAVED  platform=%s  order_id=%s  queue=%s",
            platform, order.id, order.queue_number,
        )

        # Print to kitchen — reload order with lines for the printer function
        try:
            settings_row = await db.execute(
                text("SELECT printer_kitchen_ip, printer_kitchen_port FROM settings LIMIT 1")
            )
            s = settings_row.fetchone()
            if s and s[0]:
                from sqlalchemy.orm import selectinload
                loaded = await db.execute(
                    select(Order)
                    .options(selectinload(Order.lines).selectinload(OrderItem.customizations))
                    .where(Order.id == order.id)
                )
                order_for_print = loaded.scalar_one()
                print_kitchen_ticket(
                    order        = order_for_print,
                    printer_ip   = s[0],
                    printer_port = s[1] or 9100,
                )
        except Exception:
            log.exception("Kitchen print failed for webhook order %s", order.id)

    return Response(
        content=f'{{"status":"ok","queue_number":{order.queue_number}}}',
        media_type="application/json",
    )


# ── Per-platform endpoints ────────────────────────────────────────────────────

@router.post("/wolt")
async def webhook_wolt(request: Request):
    sig = request.headers.get("X-Wolt-Signature") or request.headers.get("X-Signature")
    return await _handle_webhook("wolt", request, sig)


@router.post("/foodpanda")
async def webhook_foodpanda(request: Request):
    sig = request.headers.get("X-FP-Signature") or request.headers.get("X-Signature")
    return await _handle_webhook("foodpanda", request, sig)


@router.post("/ubereats")
async def webhook_ubereats(request: Request):
    sig = request.headers.get("X-Uber-Signature") or request.headers.get("X-Signature")
    return await _handle_webhook("ubereats", request, sig)


@router.post("/justeat")
async def webhook_justeat(request: Request):
    sig = request.headers.get("X-Je-Hmac-Sha256") or request.headers.get("X-Signature")
    return await _handle_webhook("justeat", request, sig)


@router.post("/generic")
async def webhook_generic(request: Request):
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get("X-Signature")
    return await _handle_webhook("generic", request, sig)
