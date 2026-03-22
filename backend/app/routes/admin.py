"""
Admin web interface (session-protected, HTML responses).
Also exposes admin REST endpoints under /admin/api/
"""
import logging
import os
import secrets
from typing import Optional

logger    = logging.getLogger("app.admin")
auth_log  = logging.getLogger("app.auth")
from uuid import UUID
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    Category, Item, Order, OrderItem, Machine, Setting,
    CustomizationGroup, CustomizationOption, Combo,
    DeliveryIntegration, NavSettings, NavInvoiceSubmission,
)
from app.config import settings as cfg
from app.schemas.schemas import SettingsUpdate
from app.services import nav_invoice as nav_svc

router  = APIRouter(prefix="/admin", tags=["admin"])
tmpl    = Jinja2Templates(directory="app/templates")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def require_admin(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})


# ── Login ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return tmpl.TemplateResponse("admin/login.html", {"request": request})


@router.post("/login")
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    client = request.client.host if request.client else "unknown"
    if username == cfg.ADMIN_USERNAME and password == cfg.ADMIN_PASSWORD:
        request.session["admin_logged_in"] = True
        auth_log.info("ADMIN LOGIN OK  user=%s  ip=%s", username, client)
        return RedirectResponse("/admin/", status_code=302)
    auth_log.warning("ADMIN LOGIN FAIL  user=%s  ip=%s", username, client)
    return tmpl.TemplateResponse("admin/login.html", {"request": request, "error": "Invalid credentials"})


@router.get("/logout")
async def logout(request: Request):
    client = request.client.host if request.client else "unknown"
    auth_log.info("ADMIN LOGOUT  ip=%s", client)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    today = date.today()
    # Today's order count & revenue
    res = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .where(func.date(Order.created_at) == today)
        .where(Order.status != "cancelled")
    )
    today_count, today_revenue = res.one()

    # Total orders
    total_res = await db.execute(select(func.count(Order.id)).where(Order.status != "cancelled"))
    total_orders = total_res.scalar()

    # Recent orders
    recent = await db.execute(
        select(Order).order_by(desc(Order.created_at)).limit(10)
    )
    recent_orders = recent.scalars().all()

    return tmpl.TemplateResponse("admin/dashboard.html", {
        "request":       request,
        "today_count":   today_count,
        "today_revenue": float(today_revenue),
        "total_orders":  total_orders,
        "recent_orders": recent_orders,
    })


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Category).order_by(Category.sort_order))
    cats   = result.scalars().all()
    return tmpl.TemplateResponse("admin/categories.html", {"request": request, "categories": cats})


@router.post("/categories")
async def save_category(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    cat_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    if cat_id:
        result = await db.execute(select(Category).where(Category.id == cat_id))
        cat = result.scalar_one_or_none()
        if cat:
            cat.name        = name
            cat.description = description
            cat.sort_order  = sort_order
            cat.is_active   = is_active
    else:
        db.add(Category(name=name, description=description, sort_order=sort_order, is_active=is_active))
    return RedirectResponse("/admin/categories", status_code=302)


@router.post("/categories/{cat_id}/delete")
async def delete_category(cat_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalar_one_or_none()
    if cat:
        await db.delete(cat)
    return RedirectResponse("/admin/categories", status_code=302)


# ── Items ─────────────────────────────────────────────────────────────────────

@router.get("/items", response_class=HTMLResponse)
async def items_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    items = await db.execute(
        select(Item)
        .options(selectinload(Item.customization_groups).selectinload(CustomizationGroup.options))
        .order_by(Item.category_id, Item.sort_order)
    )
    cats = await db.execute(select(Category).where(Category.is_active == True).order_by(Category.sort_order))
    return tmpl.TemplateResponse("admin/items.html", {
        "request":    request,
        "items":      items.scalars().all(),
        "categories": cats.scalars().all(),
    })


@router.post("/items")
async def save_item(
    request: Request,
    item_id:      Optional[int] = Form(None),
    category_id:  Optional[int] = Form(None),
    name:         str    = Form(...),
    description:  str    = Form(""),
    price:        float  = Form(...),
    is_available: bool   = Form(True),
    is_promoted:  bool   = Form(False),
    sort_order:   int    = Form(0),
    calories:     Optional[int] = Form(None),
    allergens:    str    = Form(""),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    image_url = None
    if image and image.filename:
        ext      = os.path.splitext(image.filename)[1]
        fname    = f"{secrets.token_hex(8)}{ext}"
        fpath    = os.path.join(cfg.UPLOAD_DIR, fname)
        os.makedirs(cfg.UPLOAD_DIR, exist_ok=True)
        with open(fpath, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/uploads/{fname}"

    if item_id:
        result = await db.execute(select(Item).where(Item.id == item_id))
        item = result.scalar_one_or_none()
        if item:
            item.category_id  = category_id
            item.name         = name
            item.description  = description
            item.price        = price
            item.is_available = is_available
            item.is_promoted  = is_promoted
            item.sort_order   = sort_order
            item.calories     = calories
            item.allergens    = allergens
            if image_url:
                item.image_url = image_url
    else:
        db.add(Item(
            category_id=category_id, name=name, description=description,
            price=price, image_url=image_url, is_available=is_available,
            is_promoted=is_promoted, sort_order=sort_order,
            calories=calories, allergens=allergens,
        ))
    return RedirectResponse("/admin/items", status_code=302)


@router.post("/items/{item_id}/delete")
async def delete_item(item_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if item:
        await db.delete(item)
    return RedirectResponse("/admin/items", status_code=302)


# ── Customizations ────────────────────────────────────────────────────────────

@router.get("/items/{item_id}/customize", response_class=HTMLResponse)
async def customize_page(item_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(
        select(Item)
        .options(selectinload(Item.customization_groups).selectinload(CustomizationGroup.options))
        .where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    return tmpl.TemplateResponse("admin/customize.html", {"request": request, "item": item})


@router.post("/items/{item_id}/customize/group")
async def add_group(
    item_id: int, request: Request,
    name: str = Form(...), is_required: bool = Form(False), multi_select: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    db.add(CustomizationGroup(item_id=item_id, name=name, is_required=is_required, multi_select=multi_select))
    return RedirectResponse(f"/admin/items/{item_id}/customize", status_code=302)


@router.post("/items/{item_id}/customize/option")
async def add_option(
    item_id: int, request: Request,
    group_id: int = Form(...), name: str = Form(...), extra_price: float = Form(0),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    db.add(CustomizationOption(group_id=group_id, name=name, extra_price=extra_price))
    return RedirectResponse(f"/admin/items/{item_id}/customize", status_code=302)


@router.post("/customize/group/{group_id}/delete")
async def del_group(group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(CustomizationGroup).where(CustomizationGroup.id == group_id))
    g = result.scalar_one_or_none()
    item_id = g.item_id if g else None
    if g:
        await db.delete(g)
    return RedirectResponse(f"/admin/items/{item_id}/customize", status_code=302)


@router.post("/customize/option/{option_id}/delete")
async def del_option(option_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(
        select(CustomizationOption)
        .options(selectinload(CustomizationOption.group))
        .where(CustomizationOption.id == option_id)
    )
    opt = result.scalar_one_or_none()
    item_id = opt.group.item_id if opt else None
    if opt:
        await db.delete(opt)
    return RedirectResponse(f"/admin/items/{item_id}/customize", status_code=302)


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Setting).limit(1))
    s = result.scalar_one_or_none()
    return tmpl.TemplateResponse("admin/settings.html", {"request": request, "s": s})


@router.post("/settings")
async def save_settings(
    request: Request,
    restaurant_name:   str   = Form(""),
    primary_color:     str   = Form("#FF6B00"),
    secondary_color:   str   = Form("#1A1A1A"),
    background_color:  str   = Form("#FFFFFF"),
    text_color:        str   = Form("#222222"),
    button_color:      str   = Form("#FF6B00"),
    font_family:       str   = Form("Arial"),
    font_size_base:    int   = Form(18),
    currency_symbol:   str   = Form("€"),
    currency_code:     str   = Form("EUR"),
    tax_rate:          float = Form(0),
    receipt_footer:    str   = Form(""),
    show_promotions:   bool  = Form(True),
    payment_gateway:   str   = Form("none"),
    payment_api_key:   str   = Form(""),
    payment_secret:    str   = Form(""),
    printer_kitchen_ip: str  = Form(""),
    printer_kitchen_port: int = Form(9100),
    idle_timeout_sec:  int   = Form(120),
    kiosk_language:    str   = Form("en"),
    logo: Optional[UploadFile] = File(None),
    banner: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    result = await db.execute(select(Setting).limit(1))
    s = result.scalar_one_or_none()
    if not s:
        s = Setting()
        db.add(s)

    async def save_file(upload: UploadFile, prefix: str) -> Optional[str]:
        if upload and upload.filename:
            ext   = os.path.splitext(upload.filename)[1]
            fname = f"{prefix}_{secrets.token_hex(6)}{ext}"
            fpath = os.path.join(cfg.UPLOAD_DIR, fname)
            os.makedirs(cfg.UPLOAD_DIR, exist_ok=True)
            with open(fpath, "wb") as f:
                f.write(await upload.read())
            return f"/static/uploads/{fname}"
        return None

    logo_url   = await save_file(logo, "logo")
    banner_url = await save_file(banner, "banner")

    s.restaurant_name    = restaurant_name
    s.primary_color      = primary_color
    s.secondary_color    = secondary_color
    s.background_color   = background_color
    s.text_color         = text_color
    s.button_color       = button_color
    s.font_family        = font_family
    s.font_size_base     = font_size_base
    s.currency_symbol    = currency_symbol
    s.currency_code      = currency_code
    s.tax_rate           = tax_rate
    s.receipt_footer     = receipt_footer
    s.show_promotions    = show_promotions
    s.payment_gateway    = payment_gateway
    s.payment_api_key    = payment_api_key or s.payment_api_key
    s.payment_secret     = payment_secret or s.payment_secret
    s.printer_kitchen_ip = printer_kitchen_ip
    s.printer_kitchen_port = printer_kitchen_port
    s.idle_timeout_sec   = idle_timeout_sec
    s.kiosk_language     = kiosk_language
    if logo_url:   s.logo_url   = logo_url
    if banner_url: s.banner_url = banner_url

    return RedirectResponse("/admin/settings", status_code=302)


# ── Machines ──────────────────────────────────────────────────────────────────

@router.get("/machines", response_class=HTMLResponse)
async def machines_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Machine).order_by(Machine.machine_type, Machine.name))
    return tmpl.TemplateResponse("admin/machines.html", {"request": request, "machines": result.scalars().all()})


@router.post("/machines")
async def add_machine(
    request: Request,
    name: str = Form(...), machine_type: str = Form(...),
    ip_address: str = Form(""), printer_ip: str = Form(""), printer_port: int = Form(9100),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    db.add(Machine(
        name=name, machine_type=machine_type,
        ip_address=ip_address or None,
        printer_ip=printer_ip or None,
        printer_port=printer_port,
        api_key=secrets.token_hex(32),
    ))
    return RedirectResponse("/admin/machines", status_code=302)


@router.post("/machines/{machine_id}/regenerate-key")
async def regen_key(machine_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    m = result.scalar_one_or_none()
    if m:
        m.api_key = secrets.token_hex(32)
    return RedirectResponse("/admin/machines", status_code=302)


@router.post("/machines/{machine_id}/delete")
async def del_machine(machine_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    m = result.scalar_one_or_none()
    if m:
        await db.delete(m)
    return RedirectResponse("/admin/machines", status_code=302)


# ── Orders (admin view) ───────────────────────────────────────────────────────

@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.lines).selectinload(OrderItem.customizations))
        .order_by(desc(Order.created_at)).limit(100)
    )
    return tmpl.TemplateResponse("admin/orders.html", {"request": request, "orders": result.scalars().all()})


@router.post("/orders/{order_id}/status")
async def admin_update_status(
    order_id: UUID, request: Request, status: str = Form(...), db: AsyncSession = Depends(get_db)
):
    require_admin(request)
    from sqlalchemy.orm import selectinload as _sl
    result = await db.execute(
        select(Order)
        .options(_sl(Order.lines).selectinload(OrderItem.customizations))
        .where(Order.id == order_id)
    )
    o = result.scalar_one_or_none()
    if o:
        prev_status = o.status
        o.status = status
        await db.flush()
        # Auto-submit NAV invoice when order transitions to "completed"
        if status == "completed" and prev_status != "completed":
            await _maybe_auto_submit_nav(db, o)
    return RedirectResponse("/admin/orders", status_code=302)


async def _maybe_auto_submit_nav(db: AsyncSession, order):
    """Submit NAV invoice if auto_submit is enabled and no prior submission exists."""
    ns = await _get_nav_settings(db)
    if not (ns.enabled and ns.auto_submit):
        return
    existing = await db.execute(
        select(NavInvoiceSubmission).where(NavInvoiceSubmission.order_id == order.id)
    )
    if existing.scalar_one_or_none():
        return   # already submitted
    try:
        await _do_nav_submit(db, order, ns)
    except Exception:
        logger.exception("NAV auto-submit failed for order %s", order.id)


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    # Top selling items
    rows = await db.execute(
        select(
            OrderItem.name,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.sum(OrderItem.line_total).label("total_revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status != "cancelled")
        .group_by(OrderItem.name)
        .order_by(desc("total_qty"))
        .limit(20)
    )
    top_items = rows.all()

    # Daily revenue last 14 days
    daily = await db.execute(
        select(
            func.date(Order.created_at).label("day"),
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(Order.status != "cancelled")
        .where(Order.created_at >= datetime.utcnow() - timedelta(days=14))
        .group_by("day")
        .order_by("day")
    )
    daily_data = daily.all()

    return tmpl.TemplateResponse("admin/reports.html", {
        "request":    request,
        "top_items":  top_items,
        "daily_data": daily_data,
    })


# ── Admin REST API ────────────────────────────────────────────────────────────
# These can be called remotely with the admin session cookie or
# an Authorization: Bearer <admin_secret> header.

@router.get("/api/orders")
async def api_orders(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(
        select(Order).options(selectinload(Order.lines).selectinload(OrderItem.customizations))
        .order_by(desc(Order.created_at)).limit(200)
    )
    orders = result.scalars().all()
    return [
        {
            "id":           str(o.id),
            "queue_number": o.queue_number,
            "status":       o.status,
            "total_amount": float(o.total_amount),
            "created_at":   o.created_at.isoformat() if o.created_at else None,
            "lines": [
                {"name": l.name, "qty": l.quantity, "total": float(l.line_total)}
                for l in o.lines
            ],
        }
        for o in orders
    ]


@router.get("/api/sales-report")
async def api_sales_report(
    request: Request,
    from_date: Optional[str] = None,
    to_date:   Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    q = (
        select(
            OrderItem.name,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.sum(OrderItem.line_total).label("total_revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status != "cancelled")
        .group_by(OrderItem.name)
        .order_by(desc("total_qty"))
    )
    if from_date:
        q = q.where(Order.created_at >= from_date)
    if to_date:
        q = q.where(Order.created_at <= to_date + " 23:59:59")
    rows = await db.execute(q)
    return [{"item": r.name, "qty": int(r.total_qty), "revenue": float(r.total_revenue)} for r in rows.all()]


# ── Delivery Integrations ──────────────────────────────────────────────────────

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    result = await db.execute(
        select(DeliveryIntegration).order_by(DeliveryIntegration.id)
    )
    integrations = result.scalars().all()
    # Derive base URL from the incoming request
    base_url = str(request.base_url).rstrip("/")
    return tmpl.TemplateResponse("admin/integrations.html", {
        "request":      request,
        "integrations": integrations,
        "base_url":     base_url,
    })


@router.post("/integrations/{platform}")
async def save_integration(
    platform:       str,
    request:        Request,
    enabled:        Optional[str]  = Form(None),
    webhook_secret: str            = Form(""),
    shop_id:        str            = Form(""),
    api_key:        str            = Form(""),
    notes:          str            = Form(""),
    clear_secret:   Optional[str]  = Form(None),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    result = await db.execute(
        select(DeliveryIntegration).where(DeliveryIntegration.platform == platform)
    )
    integ = result.scalar_one_or_none()
    if not integ:
        raise HTTPException(404, f"Platform '{platform}' not found")

    integ.enabled  = enabled == "1"
    integ.shop_id  = shop_id or None
    integ.api_key  = api_key or None
    integ.notes    = notes  or None

    if clear_secret:
        integ.webhook_secret = None
    elif webhook_secret:
        integ.webhook_secret = webhook_secret   # store plaintext (HMAC shared secret)

    logger.info(
        "INTEGRATION UPDATE  platform=%s  enabled=%s  user=%s",
        platform, integ.enabled,
        request.session.get("admin_logged_in", False),
    )
    return RedirectResponse("/admin/integrations", status_code=302)


# ── NAV Online Számla (Hungarian tax invoicing) ────────────────────────────────

async def _get_nav_settings(db: AsyncSession) -> NavSettings:
    result = await db.execute(select(NavSettings).limit(1))
    ns = result.scalar_one_or_none()
    if not ns:
        ns = NavSettings()
        db.add(ns)
        await db.flush()
    return ns


def _nav_creds(ns: NavSettings) -> nav_svc.NAVCredentials:
    return nav_svc.NAVCredentials(
        login         = ns.nav_login or "",
        password_hash = ns.nav_password_hash or "",
        tax_number    = ns.nav_tax_number or "",
        sig_key       = ns.nav_sig_key or "",
        test_mode     = ns.test_mode if ns.test_mode is not None else True,
    )


@router.get("/nav", response_class=HTMLResponse)
async def nav_page(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    ns = await _get_nav_settings(db)
    result = await db.execute(
        select(NavInvoiceSubmission)
        .order_by(desc(NavInvoiceSubmission.submitted_at))
        .limit(100)
    )
    submissions = result.scalars().all()

    # Join order queue_numbers for display
    order_ids = [s.order_id for s in submissions if s.order_id]
    order_map = {}
    if order_ids:
        ores = await db.execute(
            select(Order.id, Order.queue_number).where(Order.id.in_(order_ids))
        )
        order_map = {str(r.id): r.queue_number for r in ores.all()}

    return tmpl.TemplateResponse("admin/nav_invoicing.html", {
        "request":     request,
        "ns":          ns,
        "submissions": submissions,
        "order_map":   order_map,
        "flash":       request.session.pop("nav_flash", None),
    })


@router.post("/nav/settings")
async def save_nav_settings(
    request: Request,
    enabled:                 Optional[str] = Form(None),
    test_mode:               Optional[str] = Form(None),
    nav_login:               str           = Form(""),
    nav_password:            str           = Form(""),
    nav_sig_key:             str           = Form(""),
    nav_tax_number:          str           = Form(""),
    supplier_name:           str           = Form(""),
    supplier_tax_number:     str           = Form(""),
    supplier_country:        str           = Form("HU"),
    supplier_postal_code:    str           = Form(""),
    supplier_city:           str           = Form(""),
    supplier_address_detail: str           = Form(""),
    invoice_prefix:          str           = Form("INV"),
    auto_submit:             Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    require_admin(request)
    ns = await _get_nav_settings(db)

    ns.enabled              = enabled == "1"
    ns.test_mode            = test_mode == "1"
    ns.nav_login            = nav_login or ns.nav_login
    ns.nav_sig_key          = nav_sig_key or ns.nav_sig_key
    ns.nav_tax_number       = nav_tax_number.replace("-", "")[:8] or ns.nav_tax_number
    ns.supplier_name        = supplier_name or ns.supplier_name
    ns.supplier_tax_number  = supplier_tax_number or ns.supplier_tax_number
    ns.supplier_country     = supplier_country or "HU"
    ns.supplier_postal_code = supplier_postal_code or ns.supplier_postal_code
    ns.supplier_city        = supplier_city or ns.supplier_city
    ns.supplier_address_detail = supplier_address_detail or ns.supplier_address_detail
    ns.invoice_prefix       = invoice_prefix or "INV"
    ns.auto_submit          = auto_submit == "1"

    if nav_password:
        ns.nav_password_hash = nav_svc.sha512_upper(nav_password)

    logger.info("NAV settings updated  enabled=%s  test=%s", ns.enabled, ns.test_mode)
    request.session["nav_flash"] = ("success", "NAV settings saved.")
    return RedirectResponse("/admin/nav", status_code=302)


@router.post("/nav/test-connection")
async def nav_test_connection(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    ns = await _get_nav_settings(db)
    if not ns.nav_login or not ns.nav_password_hash or not ns.nav_tax_number or not ns.nav_sig_key:
        request.session["nav_flash"] = ("error", "Incomplete credentials — fill in Login, Password, Tax Number, and Signature Key first.")
        return RedirectResponse("/admin/nav", status_code=302)
    result = await nav_svc.test_connection(_nav_creds(ns))
    if result == "OK":
        request.session["nav_flash"] = (
            "success",
            f"Connection OK ({'test' if ns.test_mode else 'production'} environment)."
        )
    else:
        request.session["nav_flash"] = ("error", f"Connection failed: {result}")
    return RedirectResponse("/admin/nav", status_code=302)


@router.post("/nav/submit/{order_id}")
async def nav_submit_invoice(
    order_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    require_admin(request)
    # Load order with lines
    from sqlalchemy.orm import selectinload as _sl
    ores = await db.execute(
        select(Order)
        .options(_sl(Order.lines).selectinload(OrderItem.customizations))
        .where(Order.id == order_id)
    )
    order = ores.scalar_one_or_none()
    if not order:
        request.session["nav_flash"] = ("error", "Order not found.")
        return RedirectResponse("/admin/nav", status_code=302)

    # Check for existing submission
    existing = await db.execute(
        select(NavInvoiceSubmission).where(NavInvoiceSubmission.order_id == order_id)
    )
    if existing.scalar_one_or_none():
        request.session["nav_flash"] = ("error", f"Invoice already submitted for order #{order.queue_number}.")
        return RedirectResponse("/admin/nav", status_code=302)

    ns = await _get_nav_settings(db)
    if not ns.enabled:
        request.session["nav_flash"] = ("error", "NAV invoicing is disabled. Enable it in settings first.")
        return RedirectResponse("/admin/nav", status_code=302)

    flash = await _do_nav_submit(db, order, ns)
    request.session["nav_flash"] = flash
    return RedirectResponse("/admin/nav", status_code=302)


@router.post("/nav/refresh/{submission_id}")
async def nav_refresh_status(
    submission_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    require_admin(request)
    sres = await db.execute(
        select(NavInvoiceSubmission).where(NavInvoiceSubmission.id == submission_id)
    )
    sub = sres.scalar_one_or_none()
    if not sub or not sub.transaction_id:
        request.session["nav_flash"] = ("error", "Submission not found or missing transaction ID.")
        return RedirectResponse("/admin/nav", status_code=302)

    ns = await _get_nav_settings(db)
    try:
        status = await nav_svc.query_invoice_status(_nav_creds(ns), sub.transaction_id)
        nav_status_map = {"DONE": "done", "ABORTED": "aborted", "RECEIVED": "submitted",
                          "PROCESSING": "submitted", "SAVED": "submitted"}
        sub.status = nav_status_map.get(status, "submitted")
        request.session["nav_flash"] = ("success", f"Invoice {sub.invoice_number}: NAV status = {status}")
    except Exception as e:
        request.session["nav_flash"] = ("error", f"Status query failed: {e}")
    return RedirectResponse("/admin/nav", status_code=302)


async def _do_nav_submit(db: AsyncSession, order, ns: NavSettings):
    """
    Internal helper: generate invoice number, build XML, submit to NAV,
    save NavInvoiceSubmission row. Returns (level, message) flash tuple.
    """
    # Load tax rate
    from sqlalchemy import text as _text
    tax_res  = await db.execute(_text("SELECT tax_rate FROM settings LIMIT 1"))
    tax_row  = tax_res.fetchone()
    tax_rate = Decimal(str(tax_row[0])) if tax_row else Decimal("0")

    # Allocate invoice number (atomic increment)
    inv_number, new_seq, new_year = nav_svc.next_invoice_number(
        ns.invoice_prefix or "INV", ns.invoice_seq or 0, ns.invoice_year
    )
    ns.invoice_seq  = new_seq
    ns.invoice_year = new_year
    await db.flush()

    # Build the invoice request
    invoice_req = nav_svc.order_to_invoice_request(order, inv_number, ns, tax_rate)

    sub = NavInvoiceSubmission(
        order_id       = order.id,
        invoice_number = inv_number,
        status         = "pending",
    )
    db.add(sub)
    await db.flush()

    try:
        transaction_id, invoice_xml, nav_resp = await nav_svc.submit_invoice(
            _nav_creds(ns), invoice_req
        )
        sub.transaction_id = transaction_id
        sub.invoice_xml    = invoice_xml
        sub.nav_response   = nav_resp
        sub.status         = "submitted"
        await db.commit()
        logger.info("NAV invoice submitted  order=%s  invoice=%s  txn=%s",
                    order.id, inv_number, transaction_id)
        return ("success", f"Invoice {inv_number} submitted to NAV. Transaction ID: {transaction_id}")
    except Exception as e:
        sub.error_message = str(e)
        sub.status        = "error"
        await db.commit()
        logger.error("NAV invoice submission failed  order=%s  invoice=%s: %s",
                     order.id, inv_number, e)
        return ("error", f"NAV submission failed for {inv_number}: {e}")
