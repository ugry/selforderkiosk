"""
Public API consumed by kiosk and order-monitor machines.
All routes require X-Api-Key header.
"""
import logging
from typing import List, Optional
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Header, Request

logger = logging.getLogger("app.api")
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.database import get_db
from app.models.models import (
    Category, Item, Combo, Order, OrderItem, OrderItemCustomization,
    Machine, Setting, CustomizationGroup, CustomizationOption,
    NavSettings, NavInvoiceSubmission,
)
from app.services import nav_invoice as nav_svc
from app.schemas.schemas import (
    CategoryOut, ItemOut, OrderCreate, OrderOut, OrderStatusUpdate, SettingsOut
)
from app.services.auth import verify_api_key
from app.services.printer import print_kitchen_ticket, print_receipt

router = APIRouter(prefix="/api/v1", tags=["kiosk-api"])


async def auth(request: Request, x_api_key: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    return await verify_api_key(x_api_key=x_api_key, db=db, client_ip=client_ip)


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=SettingsOut)
async def get_settings(machine: Machine = Depends(auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting).limit(1))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(500, "Settings not initialised")
    return s


# ── Menu ──────────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=List[CategoryOut])
async def list_categories(machine: Machine = Depends(auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Category).where(Category.is_active == True).order_by(Category.sort_order)
    )
    return result.scalars().all()


@router.get("/items", response_model=List[ItemOut])
async def list_items(
    category_id: Optional[int] = None,
    machine: Machine = Depends(auth),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    q = (
        select(Item)
        .options(
            selectinload(Item.customization_groups)
            .selectinload(CustomizationGroup.options)
        )
        .where(Item.is_available == True)
        .order_by(Item.sort_order)
    )
    if category_id:
        q = q.where(Item.category_id == category_id)
    result = await db.execute(q)
    return result.scalars().all()


# ── Orders ────────────────────────────────────────────────────────────────────

@router.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(
    body: OrderCreate,
    machine: Machine = Depends(auth),
    db: AsyncSession = Depends(get_db),
):
    # Fetch settings for tax & printer
    s_result = await db.execute(select(Setting).limit(1))
    s = s_result.scalar_one_or_none()
    tax_rate = Decimal(str(s.tax_rate)) if s else Decimal("0")

    order = Order(
        kiosk_machine_id=machine.id,
        note=body.note,
        payment_method=body.payment_method,
        status="pending",
        payment_status="unpaid",
    )
    db.add(order)
    await db.flush()

    subtotal = Decimal("0")
    for line_in in body.lines:
        # Calculate per-line total including customisations
        cust_extra = sum(Decimal(str(c.extra_price)) for c in line_in.customizations)
        unit_price = Decimal(str(line_in.unit_price)) + cust_extra
        line_total = unit_price * line_in.quantity
        subtotal += line_total

        oi = OrderItem(
            order_id=order.id,
            item_id=line_in.item_id,
            combo_id=line_in.combo_id,
            name=line_in.name,
            unit_price=Decimal(str(line_in.unit_price)),
            quantity=line_in.quantity,
            line_total=line_total,
        )
        db.add(oi)
        await db.flush()

        for c in line_in.customizations:
            db.add(OrderItemCustomization(
                order_item_id=oi.id,
                option_id=c.option_id,
                option_name=c.option_name,
                extra_price=c.extra_price,
            ))

    tax_amount = (subtotal * tax_rate / 100).quantize(Decimal("0.01"))
    order.subtotal     = subtotal
    order.tax_amount   = tax_amount
    order.total_amount = subtotal + tax_amount
    await db.flush()

    # Reload with relationships
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.lines)
            .selectinload(OrderItem.customizations)
        )
        .where(Order.id == order.id)
    )
    full_order = result.scalar_one()

    logger.info(
        "NEW ORDER  queue=#%04d  id=%s  machine=%s  total=%s  items=%d",
        full_order.queue_number, full_order.id,
        machine.name, full_order.total_amount, len(full_order.lines),
    )

    # Print to kitchen
    if s and s.printer_kitchen_ip:
        try:
            print_kitchen_ticket(full_order, s.printer_kitchen_ip, s.printer_kitchen_port or 9100)
            full_order.printed_kitchen = True
            logger.info("Kitchen ticket printed  queue=#%04d  printer=%s", full_order.queue_number, s.printer_kitchen_ip)
        except Exception as exc:
            logger.error("Kitchen print FAILED  queue=#%04d  error=%s", full_order.queue_number, exc)

    # Print receipt to kiosk printer if machine has one
    if machine.printer_ip and s:
        try:
            print_receipt(
                full_order,
                s.restaurant_name or "Restaurant",
                s.receipt_footer or "",
                s.currency_symbol or "€",
                machine.printer_ip,
                machine.printer_port or 9100,
            )
            full_order.printed_receipt = True
            logger.info("Receipt printed  queue=#%04d  printer=%s", full_order.queue_number, machine.printer_ip)
        except Exception as exc:
            logger.error("Receipt print FAILED  queue=#%04d  error=%s", full_order.queue_number, exc)

    return full_order


@router.get("/orders", response_model=List[OrderOut])
async def list_orders(
    status: Optional[str] = None,
    limit: int = 50,
    machine: Machine = Depends(auth),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    q = (
        select(Order)
        .options(selectinload(Order.lines).selectinload(OrderItem.customizations))
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    if status:
        q = q.where(Order.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: UUID,
    machine: Machine = Depends(auth),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.lines).selectinload(OrderItem.customizations))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
async def update_order_status(
    order_id: UUID,
    body: OrderStatusUpdate,
    machine: Machine = Depends(auth),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.lines).selectinload(OrderItem.customizations))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    old_status   = order.status
    order.status = body.status
    logger.info(
        "ORDER STATUS  queue=#%04d  %s → %s  machine=%s",
        order.queue_number, old_status, body.status, machine.name,
    )
    await db.flush()
    # Auto-submit NAV invoice when any machine marks the order as completed
    if body.status == "completed" and old_status != "completed":
        await _auto_nav_submit(db, order)
    return order


async def _auto_nav_submit(db: AsyncSession, order):
    """Fire-and-forget NAV invoice submission if auto_submit is enabled."""
    try:
        ns_res = await db.execute(select(NavSettings).limit(1))
        ns = ns_res.scalar_one_or_none()
        if not ns or not ns.enabled or not ns.auto_submit:
            return
        exists = await db.execute(
            select(NavInvoiceSubmission).where(NavInvoiceSubmission.order_id == order.id)
        )
        if exists.scalar_one_or_none():
            return
        from decimal import Decimal as _D
        from sqlalchemy import text as _text
        tax_res  = await db.execute(_text("SELECT tax_rate FROM settings LIMIT 1"))
        tax_row  = tax_res.fetchone()
        tax_rate = _D(str(tax_row[0])) if tax_row else _D("0")
        inv_number, new_seq, new_year = nav_svc.next_invoice_number(
            ns.invoice_prefix or "INV", ns.invoice_seq or 0, ns.invoice_year
        )
        ns.invoice_seq  = new_seq
        ns.invoice_year = new_year
        await db.flush()
        invoice_req = nav_svc.order_to_invoice_request(order, inv_number, ns, tax_rate)
        sub = NavInvoiceSubmission(
            order_id=order.id, invoice_number=inv_number, status="pending"
        )
        db.add(sub)
        await db.flush()
        creds = nav_svc.NAVCredentials(
            login         = ns.nav_login or "",
            password_hash = ns.nav_password_hash or "",
            tax_number    = ns.nav_tax_number or "",
            sig_key       = ns.nav_sig_key or "",
            test_mode     = ns.test_mode if ns.test_mode is not None else True,
        )
        txn_id, inv_xml, nav_resp = await nav_svc.submit_invoice(creds, invoice_req)
        sub.transaction_id = txn_id
        sub.invoice_xml    = inv_xml
        sub.nav_response   = nav_resp
        sub.status         = "submitted"
        await db.commit()
        logger.info("NAV auto-submit OK  order=%s  invoice=%s  txn=%s",
                    order.id, inv_number, txn_id)
    except Exception:
        logger.exception("NAV auto-submit failed  order=%s", order.id)


# ── Queue (for monitor screen) ────────────────────────────────────────────────

@router.get("/queue")
async def get_queue(machine: Machine = Depends(auth), db: AsyncSession = Depends(get_db)):
    """Returns pending/preparing/ready orders for the order monitor, including item names."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.lines))
        .where(Order.status.in_(["pending", "confirmed", "preparing", "ready"]))
        .order_by(Order.queue_number)
    )
    orders = result.scalars().all()
    return [
        {
            "id":           str(o.id),
            "queue_number": o.queue_number,
            "status":       o.status,
            "created_at":   o.created_at.isoformat() if o.created_at else None,
            "items": [
                {"name": l.name, "quantity": l.quantity}
                for l in o.lines
            ],
        }
        for o in orders
    ]


@router.get("/completed")
async def get_completed(machine: Machine = Depends(auth), db: AsyncSession = Depends(get_db)):
    """Returns last 20 completed orders for the monitor."""
    result = await db.execute(
        select(Order.queue_number, Order.status, Order.updated_at)
        .where(Order.status == "completed")
        .order_by(desc(Order.updated_at))
        .limit(20)
    )
    rows = result.all()
    return [
        {"queue_number": r.queue_number, "status": r.status}
        for r in rows
    ]
