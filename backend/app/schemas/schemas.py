from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsOut(BaseModel):
    restaurant_name:   str
    logo_url:          Optional[str]
    banner_url:        Optional[str]
    primary_color:     str
    secondary_color:   str
    background_color:  str
    text_color:        str
    button_color:      str
    font_family:       str
    font_size_base:    int
    currency_symbol:   str
    currency_code:     str
    tax_rate:          Decimal
    receipt_footer:    str
    show_promotions:   bool
    payment_gateway:   str
    idle_timeout_sec:  int
    kiosk_language:    str
    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    restaurant_name:   Optional[str]   = None
    logo_url:          Optional[str]   = None
    banner_url:        Optional[str]   = None
    primary_color:     Optional[str]   = None
    secondary_color:   Optional[str]   = None
    background_color:  Optional[str]   = None
    text_color:        Optional[str]   = None
    button_color:      Optional[str]   = None
    font_family:       Optional[str]   = None
    font_size_base:    Optional[int]   = None
    currency_symbol:   Optional[str]   = None
    currency_code:     Optional[str]   = None
    tax_rate:          Optional[Decimal] = None
    receipt_footer:    Optional[str]   = None
    show_promotions:   Optional[bool]  = None
    payment_gateway:   Optional[str]   = None
    payment_api_key:   Optional[str]   = None
    payment_secret:    Optional[str]   = None
    printer_kitchen_ip:  Optional[str] = None
    printer_kitchen_port: Optional[int] = None
    idle_timeout_sec:  Optional[int]   = None


# ── Machines ──────────────────────────────────────────────────────────────────

class MachineOut(BaseModel):
    id:           UUID
    name:         str
    machine_type: str
    api_key:      str
    ip_address:   Optional[str]
    printer_ip:   Optional[str]
    printer_port: int
    is_active:    bool
    last_seen:    Optional[datetime]
    model_config = {"from_attributes": True}


class MachineCreate(BaseModel):
    name:         str
    machine_type: str
    ip_address:   Optional[str] = None
    printer_ip:   Optional[str] = None
    printer_port: int = 9100


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryOut(BaseModel):
    id:          int
    name:        str
    description: Optional[str]
    image_url:   Optional[str]
    sort_order:  int
    is_active:   bool
    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name:        str
    description: Optional[str] = None
    image_url:   Optional[str] = None
    sort_order:  int = 0


# ── Items ─────────────────────────────────────────────────────────────────────

class CustomizationOptionOut(BaseModel):
    id:          int
    name:        str
    extra_price: Decimal
    is_default:  bool
    sort_order:  int
    model_config = {"from_attributes": True}


class CustomizationGroupOut(BaseModel):
    id:           int
    name:         str
    is_required:  bool
    multi_select: bool
    sort_order:   int
    options:      List[CustomizationOptionOut] = []
    model_config = {"from_attributes": True}


class ItemOut(BaseModel):
    id:           int
    category_id:  Optional[int]
    name:         str
    description:  Optional[str]
    price:        Decimal
    image_url:    Optional[str]
    is_available: bool
    is_promoted:  bool
    sort_order:   int
    calories:     Optional[int]
    allergens:    Optional[str]
    customization_groups: List[CustomizationGroupOut] = []
    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    category_id:  Optional[int] = None
    name:         str
    description:  Optional[str] = None
    price:        Decimal
    image_url:    Optional[str] = None
    is_available: bool = True
    is_promoted:  bool = False
    sort_order:   int = 0
    calories:     Optional[int] = None
    allergens:    Optional[str] = None


# ── Orders ────────────────────────────────────────────────────────────────────

class OrderItemCustomizationIn(BaseModel):
    option_id:   int
    option_name: str
    extra_price: Decimal = Decimal("0")


class OrderItemIn(BaseModel):
    item_id:    Optional[int] = None
    combo_id:   Optional[int] = None
    name:       str
    unit_price: Decimal
    quantity:   int = 1
    customizations: List[OrderItemCustomizationIn] = []


class OrderCreate(BaseModel):
    kiosk_machine_id: Optional[UUID] = None
    note:             Optional[str]  = None
    payment_method:   Optional[str]  = "cash"
    lines:            List[OrderItemIn]


class OrderCustomizationOut(BaseModel):
    option_name: str
    extra_price: Decimal
    model_config = {"from_attributes": True}


class OrderItemOut(BaseModel):
    id:         int
    name:       str
    unit_price: Decimal
    quantity:   int
    line_total: Decimal
    customizations: List[OrderCustomizationOut] = []
    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id:                 UUID
    queue_number:       int
    source:             str = "kiosk"
    external_order_id:  Optional[str] = None
    customer_name:      Optional[str] = None
    delivery_notes:     Optional[str] = None
    status:             str
    subtotal:           Decimal
    tax_amount:         Decimal
    total_amount:       Decimal
    payment_method:     Optional[str]
    payment_status:     str
    note:               Optional[str]
    created_at:         datetime
    lines:              List[OrderItemOut] = []
    model_config = {"from_attributes": True}


# ── Delivery Integrations ──────────────────────────────────────────────────────

class DeliveryIntegrationOut(BaseModel):
    id:             int
    platform:       str
    display_name:   Optional[str]
    enabled:        bool
    shop_id:        Optional[str]
    notes:          Optional[str]
    # secrets are NOT exposed via API
    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    status: str


# ── Reports ───────────────────────────────────────────────────────────────────

class SalesReportItem(BaseModel):
    item_name:   str
    total_qty:   int
    total_revenue: Decimal
