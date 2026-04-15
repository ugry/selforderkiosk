"""
API endpoint tests — require a valid TEST_API_KEY env var.
"""
import pytest
import httpx


# ── Settings ───────────────────────────────────────────────────────────────────

def test_get_settings(api):
    r = api.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()
    assert "restaurant_name" in body
    assert "currency_symbol" in body
    assert "tax_rate" in body


# ── Categories ─────────────────────────────────────────────────────────────────

def test_list_categories_returns_list(api):
    r = api.get("/api/v1/categories")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_categories_fields(api):
    r = api.get("/api/v1/categories")
    cats = r.json()
    if cats:
        c = cats[0]
        assert "id" in c
        assert "name" in c
        assert "is_active" in c


# ── Items ──────────────────────────────────────────────────────────────────────

def test_list_items_returns_list(api):
    r = api.get("/api/v1/items")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_items_fields(api):
    r = api.get("/api/v1/items")
    items = r.json()
    if items:
        item = items[0]
        assert "id" in item
        assert "name" in item
        assert "price" in item
        assert "is_available" in item


def test_items_filter_by_category(api):
    cats = api.get("/api/v1/categories").json()
    if not cats:
        pytest.skip("No categories in database")
    cat_id = cats[0]["id"]
    r = api.get(f"/api/v1/items?category_id={cat_id}")
    assert r.status_code == 200
    items = r.json()
    for item in items:
        assert item["category_id"] == cat_id


# ── Orders ─────────────────────────────────────────────────────────────────────

def _sample_order_payload(api):
    """Helper: build a minimal valid order from available items."""
    items = api.get("/api/v1/items").json()
    if not items:
        pytest.skip("No items in database — cannot create test order")
    item = items[0]
    return {
        "payment_method": "cash",
        "note": "pytest test order",
        "lines": [
            {
                "item_id": item["id"],
                "name": item["name"],
                "unit_price": str(item["price"]),
                "quantity": 1,
                "customizations": [],
            }
        ],
    }


def test_create_order(api):
    payload = _sample_order_payload(api)
    r = api.post("/api/v1/orders", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert "queue_number" in body
    assert body["status"] == "pending"
    assert body["payment_status"] == "unpaid"


def test_list_orders(api):
    r = api.get("/api/v1/orders")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_orders_filter_by_status(api):
    r = api.get("/api/v1/orders?status=pending")
    assert r.status_code == 200
    orders = r.json()
    for o in orders:
        assert o["status"] == "pending"


def test_get_order_by_id(api):
    payload = _sample_order_payload(api)
    order_id = api.post("/api/v1/orders", json=payload).json()["id"]
    r = api.get(f"/api/v1/orders/{order_id}")
    assert r.status_code == 200
    assert r.json()["id"] == order_id


def test_get_order_not_found(api):
    r = api.get("/api/v1/orders/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_update_order_status(api):
    payload = _sample_order_payload(api)
    order_id = api.post("/api/v1/orders", json=payload).json()["id"]
    r = api.patch(f"/api/v1/orders/{order_id}/status", json={"status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"


def test_update_order_status_full_flow(api):
    """Walk an order through the full kitchen lifecycle."""
    payload = _sample_order_payload(api)
    order_id = api.post("/api/v1/orders", json=payload).json()["id"]

    for status in ("confirmed", "preparing", "ready", "completed"):
        r = api.patch(f"/api/v1/orders/{order_id}/status", json={"status": status})
        assert r.status_code == 200
        assert r.json()["status"] == status


def test_update_order_payment(api):
    payload = _sample_order_payload(api)
    order_id = api.post("/api/v1/orders", json=payload).json()["id"]
    r = api.patch(
        f"/api/v1/orders/{order_id}/payment",
        json={"payment_status": "paid", "payment_method": "cash"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["payment_status"] == "paid"
    assert body["payment_method"] == "cash"


def test_update_order_payment_not_found(api):
    r = api.patch(
        "/api/v1/orders/00000000-0000-0000-0000-000000000000/payment",
        json={"payment_status": "paid"},
    )
    assert r.status_code == 404


# ── Queue & completed ──────────────────────────────────────────────────────────

def test_get_queue(api):
    r = api.get("/api/v1/queue")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for entry in data:
        assert "queue_number" in entry
        assert "status" in entry
        assert entry["status"] in ("pending", "confirmed", "preparing", "ready")


def test_get_completed(api):
    r = api.get("/api/v1/completed")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
