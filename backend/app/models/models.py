import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Integer, Numeric, Text,
    ForeignKey, DateTime, Date, Sequence
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Setting(Base):
    __tablename__ = "settings"
    id                = Column(Integer, primary_key=True)
    restaurant_name   = Column(String(255), default="My Restaurant")
    logo_url          = Column(String(500))
    banner_url        = Column(String(500))
    primary_color     = Column(String(7), default="#FF6B00")
    secondary_color   = Column(String(7), default="#1A1A1A")
    background_color  = Column(String(7), default="#FFFFFF")
    text_color        = Column(String(7), default="#222222")
    button_color      = Column(String(7), default="#FF6B00")
    font_family       = Column(String(100), default="Arial")
    font_size_base    = Column(Integer, default=18)
    currency_symbol   = Column(String(5), default="€")
    currency_code     = Column(String(3), default="EUR")
    tax_rate          = Column(Numeric(5, 2), default=0)
    receipt_footer    = Column(Text, default="Thank you for your order!")
    payment_gateway   = Column(String(50), default="none")
    payment_api_key   = Column(Text)
    payment_secret    = Column(Text)
    printer_kitchen_ip   = Column(String(100))
    printer_kitchen_port = Column(Integer, default=9100)
    idle_timeout_sec  = Column(Integer, default=120)
    show_promotions   = Column(Boolean, default=True)
    kiosk_language    = Column(String(5), default="en")
    waiting_video_url = Column(String(500))
    updated_at        = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Machine(Base):
    __tablename__ = "machines"
    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name         = Column(String(100), nullable=False)
    machine_type = Column(String(20), nullable=False)
    api_key      = Column(String(128), unique=True, nullable=False)
    ip_address   = Column(String(50))
    printer_ip   = Column(String(100))
    printer_port = Column(Integer, default=9100)
    is_active    = Column(Boolean, default=True)
    last_seen    = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(100), nullable=False)
    description = Column(Text)
    image_url   = Column(String(500))
    sort_order  = Column(Integer, default=0)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), default=datetime.utcnow)
    items       = relationship("Item", back_populates="category")


class Item(Base):
    __tablename__ = "items"
    id           = Column(Integer, primary_key=True)
    category_id  = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    name         = Column(String(200), nullable=False)
    description  = Column(Text)
    price        = Column(Numeric(10, 2), nullable=False, default=0)
    image_url    = Column(String(500))
    is_available = Column(Boolean, default=True)
    is_promoted  = Column(Boolean, default=False)
    sort_order   = Column(Integer, default=0)
    calories     = Column(Integer)
    allergens    = Column(String(255))
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at   = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    category             = relationship("Category", back_populates="items")
    customization_groups = relationship("CustomizationGroup", back_populates="item", cascade="all, delete-orphan")


class CustomizationGroup(Base):
    __tablename__ = "customization_groups"
    id           = Column(Integer, primary_key=True)
    item_id      = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    name         = Column(String(100), nullable=False)
    is_required  = Column(Boolean, default=False)
    multi_select = Column(Boolean, default=True)
    sort_order   = Column(Integer, default=0)
    item    = relationship("Item", back_populates="customization_groups")
    options = relationship("CustomizationOption", back_populates="group", cascade="all, delete-orphan")


class CustomizationOption(Base):
    __tablename__ = "customization_options"
    id          = Column(Integer, primary_key=True)
    group_id    = Column(Integer, ForeignKey("customization_groups.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(100), nullable=False)
    extra_price = Column(Numeric(8, 2), default=0)
    is_default  = Column(Boolean, default=False)
    sort_order  = Column(Integer, default=0)
    group = relationship("CustomizationGroup", back_populates="options")


class Combo(Base):
    __tablename__ = "combos"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(200), nullable=False)
    description = Column(Text)
    image_url   = Column(String(500))
    combo_price = Column(Numeric(10, 2), nullable=False)
    is_active   = Column(Boolean, default=True)
    valid_from  = Column(Date)
    valid_until = Column(Date)
    created_at  = Column(DateTime(timezone=True), default=datetime.utcnow)


class NavSettings(Base):
    """Single-row table holding NAV Online Számla API credentials and supplier info."""
    __tablename__ = "nav_settings"
    id                      = Column(Integer, primary_key=True)
    enabled                 = Column(Boolean, default=False)
    test_mode               = Column(Boolean, default=True)
    nav_login               = Column(String(100))
    nav_password_hash       = Column(Text)          # SHA-512 uppercase hex
    nav_sig_key             = Column(Text)           # aláírási kulcs
    nav_tax_number          = Column(String(8))      # 8-digit taxpayer ID
    supplier_name           = Column(String(255))
    supplier_tax_number     = Column(String(15))     # full 11-char (e.g. 12345678-1-23)
    supplier_country        = Column(String(2), default="HU")
    supplier_postal_code    = Column(String(10))
    supplier_city           = Column(String(100))
    supplier_address_detail = Column(String(255))    # "Kossuth Lajos utca 1."
    invoice_prefix          = Column(String(20), default="INV")
    invoice_seq             = Column(Integer, default=0)
    invoice_year            = Column(Integer)
    auto_submit             = Column(Boolean, default=False)
    updated_at              = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class NavInvoiceSubmission(Base):
    """One row per invoice submitted (or attempted) to NAV."""
    __tablename__ = "nav_invoice_submissions"
    id              = Column(Integer, primary_key=True)
    order_id        = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"))
    invoice_number  = Column(String(100), unique=True, nullable=False)
    transaction_id  = Column(String(100))
    status          = Column(String(20), default="pending")  # pending/submitted/done/error/aborted
    invoice_xml     = Column(Text)
    nav_response    = Column(Text)
    error_message   = Column(Text)
    submitted_at    = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryIntegration(Base):
    __tablename__ = "delivery_integrations"
    id             = Column(Integer, primary_key=True)
    platform       = Column(String(30), nullable=False, unique=True)
    display_name   = Column(String(100))
    enabled        = Column(Boolean, default=False)
    webhook_secret = Column(Text)
    api_key        = Column(Text)
    api_secret     = Column(Text)
    shop_id        = Column(String(100))
    notes          = Column(Text)
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at     = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


order_queue_seq = Sequence("order_queue_seq", start=1, maxvalue=9999, cycle=True)


class Order(Base):
    __tablename__ = "orders"
    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_number        = Column(Integer, server_default=order_queue_seq.next_value())
    kiosk_machine_id    = Column(UUID(as_uuid=True), ForeignKey("machines.id"))
    source              = Column(String(20), default="kiosk")
    external_order_id   = Column(String(100))
    customer_name       = Column(String(100))
    delivery_notes      = Column(Text)
    status              = Column(String(20), default="pending")
    subtotal            = Column(Numeric(10, 2), default=0)
    tax_amount          = Column(Numeric(10, 2), default=0)
    total_amount        = Column(Numeric(10, 2), default=0)
    payment_method      = Column(String(30))
    payment_status      = Column(String(20), default="unpaid")
    payment_ref         = Column(String(255))
    note                = Column(Text)
    printed_kitchen     = Column(Boolean, default=False)
    printed_receipt     = Column(Boolean, default=False)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at          = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    lines = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id         = Column(Integer, primary_key=True)
    order_id   = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    item_id    = Column(Integer, ForeignKey("items.id"))
    combo_id   = Column(Integer, ForeignKey("combos.id"))
    name       = Column(String(200), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity   = Column(Integer, nullable=False, default=1)
    line_total = Column(Numeric(10, 2), nullable=False)
    order         = relationship("Order", back_populates="lines")
    customizations = relationship("OrderItemCustomization", back_populates="order_item", cascade="all, delete-orphan")


class OrderItemCustomization(Base):
    __tablename__ = "order_item_customizations"
    id            = Column(Integer, primary_key=True)
    order_item_id = Column(Integer, ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False)
    option_id     = Column(Integer, ForeignKey("customization_options.id"))
    option_name   = Column(String(100), nullable=False)
    extra_price   = Column(Numeric(8, 2), default=0)
    order_item = relationship("OrderItem", back_populates="customizations")
