"""
Admin web interface tests using Playwright headless browser.
Requires an accessible backend at BASE_URL with valid ADMIN_USER/ADMIN_PASS.
"""
import pytest
from playwright.sync_api import Page, expect


# ── Login ──────────────────────────────────────────────────────────────────────

def test_login_page_loads(page: Page, base_url):
    page.goto(f"{base_url}/admin/login")
    expect(page.locator("input[name='username']")).to_be_visible()
    expect(page.locator("input[name='password']")).to_be_visible()
    expect(page.locator("button[type='submit']")).to_be_visible()


def test_login_wrong_credentials(page: Page, base_url):
    page.goto(f"{base_url}/admin/login")
    page.fill("input[name='username']", "wrong")
    page.fill("input[name='password']", "wrong")
    page.click("button[type='submit']")
    # Should stay on login page and show error
    assert "/admin/login" in page.url or "login" in page.url
    # "Invalid credentials" message — match case-insensitively via regex locator
    expect(page.locator("text=/invalid/i")).to_be_visible(timeout=5_000)


def test_login_success(admin_page: Page):
    """admin_page fixture already logged in; should land on admin dashboard."""
    assert "/admin/" in admin_page.url or "/admin/dashboard" in admin_page.url


def test_admin_redirects_unauthenticated(page: Page, base_url):
    page.goto(f"{base_url}/admin/")
    # Should redirect to login
    page.wait_for_url("**/login**", timeout=5_000)


# ── Dashboard ──────────────────────────────────────────────────────────────────

def test_dashboard_loads(admin_page: Page):
    admin_page.goto(admin_page.url.split("/admin/")[0] + "/admin/")
    expect(admin_page.locator("body")).to_be_visible()
    # Dashboard should contain navigation links
    expect(admin_page.get_by_role("link", name="Orders",   exact=False)).to_be_visible(timeout=8_000)


# ── Settings page ──────────────────────────────────────────────────────────────

def test_settings_page_loads(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/settings")
    expect(admin_page.locator("input[name='restaurant_name']")).to_be_visible(timeout=8_000)
    expect(admin_page.locator("select[name='payment_gateway']")).to_be_visible()
    expect(admin_page.locator("input[name='tax_rate']")).to_be_visible()


def test_settings_save(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/settings")
    admin_page.wait_for_selector("input[name='restaurant_name']", timeout=8_000)
    # Fill restaurant name with a test value
    admin_page.fill("input[name='restaurant_name']", "Test Restaurant CI")
    admin_page.click("button[type='submit']")
    # After save should stay on settings or redirect to settings
    admin_page.wait_for_load_state("networkidle")
    assert "settings" in admin_page.url or admin_page.url.endswith("/admin/")


def test_settings_currency_preset(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/settings")
    admin_page.wait_for_selector("select#currency_preset", timeout=8_000)
    # Select EUR preset
    admin_page.select_option("select#currency_preset", value="€|EUR")
    expect(admin_page.locator("input#currency_symbol")).to_have_value("€")
    expect(admin_page.locator("input#currency_code")).to_have_value("EUR")


def test_settings_vat_quickselect(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/settings")
    admin_page.wait_for_selector("#vat_btn_20", timeout=8_000)
    admin_page.click("#vat_btn_20")
    expect(admin_page.locator("input#tax_rate")).to_have_value("20")


# ── Categories page ────────────────────────────────────────────────────────────

def test_categories_page_loads(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/categories")
    admin_page.wait_for_load_state("networkidle")
    expect(admin_page.locator("body")).to_be_visible()


# ── Items page ─────────────────────────────────────────────────────────────────

def test_items_page_loads(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/items")
    admin_page.wait_for_load_state("networkidle")
    expect(admin_page.locator("body")).to_be_visible()


# ── Orders page ────────────────────────────────────────────────────────────────

def test_orders_page_loads(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/orders")
    admin_page.wait_for_load_state("networkidle")
    expect(admin_page.locator("body")).to_be_visible()


# ── Machines page ──────────────────────────────────────────────────────────────

def test_machines_page_loads(admin_page: Page, base_url):
    admin_page.goto(f"{base_url}/admin/machines")
    admin_page.wait_for_load_state("networkidle")
    expect(admin_page.locator("body")).to_be_visible()


def test_create_machine(admin_page: Page, base_url):
    import time
    admin_page.goto(f"{base_url}/admin/machines")
    admin_page.wait_for_load_state("networkidle")
    name_input = admin_page.locator("input[name='name']").first
    if not name_input.is_visible():
        pytest.skip("No machine create form found on machines page")
    machine_name = f"CI-Kiosk-{int(time.time())}"
    admin_page.fill("input[name='name']", machine_name)
    admin_page.select_option("select[name='machine_type']", value="kiosk")
    # The add-machine button has the text "+ Add Machine"
    admin_page.get_by_role("button", name="Add Machine").click()
    admin_page.wait_for_load_state("networkidle")
    expect(admin_page.get_by_text(machine_name)).to_be_visible(timeout=8_000)


# ── Full order flow (browser) ──────────────────────────────────────────────────

def test_full_order_flow_via_admin(admin_page: Page, base_url):
    """
    Smoke test: create an order via the API and verify it appears in admin orders.
    Uses admin_page only for the orders view; order creation uses httpx.
    """
    import os, httpx

    api_key = os.environ.get("TEST_API_KEY", "")
    if not api_key:
        pytest.skip("TEST_API_KEY not set — skipping full flow test")

    with httpx.Client(base_url=base_url, headers={"X-Api-Key": api_key}, timeout=15) as client:
        items = client.get("/api/v1/items").json()
        if not items:
            pytest.skip("No items in database")
        item = items[0]
        order = client.post("/api/v1/orders", json={
            "payment_method": "card",
            "note": "browser smoke test",
            "lines": [{
                "item_id": item["id"],
                "name": item["name"],
                "unit_price": str(item["price"]),
                "quantity": 2,
                "customizations": [],
            }],
        }).json()

    queue_num = order["queue_number"]

    admin_page.goto(f"{base_url}/admin/orders")
    admin_page.wait_for_load_state("networkidle")
    # The order's queue number appears as #NNNN in the table
    expect(admin_page.get_by_text(f"#{queue_num:04d}")).to_be_visible(timeout=8_000)
