-- ============================================================
-- RESTAURANT SELF-ORDER KIOSK – PostgreSQL Schema
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- pgcrypto is required for gen_random_bytes() used in machines.api_key default
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Settings (single row) ─────────────────────────────────────────────────────
CREATE TABLE settings (
    id                  SERIAL PRIMARY KEY,
    restaurant_name     VARCHAR(255) DEFAULT 'My Restaurant',
    logo_url            VARCHAR(500),
    banner_url          VARCHAR(500),
    primary_color       VARCHAR(7)   DEFAULT '#FF6B00',
    secondary_color     VARCHAR(7)   DEFAULT '#1A1A1A',
    background_color    VARCHAR(7)   DEFAULT '#FFFFFF',
    text_color          VARCHAR(7)   DEFAULT '#222222',
    button_color        VARCHAR(7)   DEFAULT '#FF6B00',
    font_family         VARCHAR(100) DEFAULT 'Arial',
    font_size_base      INT          DEFAULT 18,
    currency_symbol     VARCHAR(5)   DEFAULT '€',
    currency_code       VARCHAR(3)   DEFAULT 'EUR',
    tax_rate            NUMERIC(5,2) DEFAULT 0.00,
    receipt_footer      TEXT         DEFAULT 'Thank you for your order!',
    payment_gateway     VARCHAR(50)  DEFAULT 'none',
    payment_api_key     TEXT,
    payment_secret      TEXT,
    printer_kitchen_ip  VARCHAR(100),
    printer_kitchen_port INT         DEFAULT 9100,
    idle_timeout_sec    INT          DEFAULT 120,
    show_promotions     BOOLEAN      DEFAULT TRUE,
    kiosk_language      VARCHAR(5)   DEFAULT 'en',
    waiting_video_url   VARCHAR(500),
    updated_at          TIMESTAMPTZ  DEFAULT NOW()
);
INSERT INTO settings DEFAULT VALUES;

-- ── Machines / API keys ───────────────────────────────────────────────────────
CREATE TABLE machines (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(100) NOT NULL,
    machine_type VARCHAR(20) NOT NULL CHECK (machine_type IN ('kiosk','monitor','admin','kitchen')),
    api_key     VARCHAR(128) UNIQUE NOT NULL DEFAULT encode(gen_random_bytes(32),'hex'),
    ip_address  VARCHAR(50),
    printer_ip  VARCHAR(100),
    printer_port INT DEFAULT 9100,
    is_active   BOOLEAN DEFAULT TRUE,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
-- Default machine entries
INSERT INTO machines (name, machine_type) VALUES
  ('Kiosk-1',   'kiosk'),
  ('Monitor-1', 'monitor'),
  ('Kitchen-1', 'kitchen'),
  ('Admin',     'admin');

-- ── Categories ────────────────────────────────────────────────────────────────
CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    image_url   VARCHAR(500),
    sort_order  INT DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Items ─────────────────────────────────────────────────────────────────────
CREATE TABLE items (
    id              SERIAL PRIMARY KEY,
    category_id     INT REFERENCES categories(id) ON DELETE SET NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    price           NUMERIC(10,2) NOT NULL DEFAULT 0,
    image_url       VARCHAR(500),
    is_available    BOOLEAN DEFAULT TRUE,
    is_promoted     BOOLEAN DEFAULT FALSE,
    sort_order      INT DEFAULT 0,
    calories        INT,
    allergens       VARCHAR(255),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Item customization groups ─────────────────────────────────────────────────
-- e.g. "Sauce", "Size", "Extras"
CREATE TABLE customization_groups (
    id          SERIAL PRIMARY KEY,
    item_id     INT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,      -- e.g. "Choose sauce"
    is_required BOOLEAN DEFAULT FALSE,
    multi_select BOOLEAN DEFAULT TRUE,      -- can pick many options
    sort_order  INT DEFAULT 0
);

-- ── Customization options ─────────────────────────────────────────────────────
-- e.g. "Ketchup", "Jalapeño", "Mayonnaise"
CREATE TABLE customization_options (
    id          SERIAL PRIMARY KEY,
    group_id    INT NOT NULL REFERENCES customization_groups(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    extra_price NUMERIC(8,2) DEFAULT 0,
    is_default  BOOLEAN DEFAULT FALSE,
    sort_order  INT DEFAULT 0
);

-- ── Combos / promotions ───────────────────────────────────────────────────────
CREATE TABLE combos (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    description   TEXT,
    image_url     VARCHAR(500),
    combo_price   NUMERIC(10,2) NOT NULL,
    is_active     BOOLEAN DEFAULT TRUE,
    valid_from    DATE,
    valid_until   DATE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE combo_items (
    combo_id INT REFERENCES combos(id) ON DELETE CASCADE,
    item_id  INT REFERENCES items(id)  ON DELETE CASCADE,
    quantity INT DEFAULT 1,
    PRIMARY KEY (combo_id, item_id)
);

-- ── Delivery platform integrations ───────────────────────────────────────────
CREATE TABLE delivery_integrations (
    id              SERIAL PRIMARY KEY,
    platform        VARCHAR(30)  NOT NULL UNIQUE,  -- wolt, foodpanda, ubereats, justeat, generic
    display_name    VARCHAR(100),
    enabled         BOOLEAN      DEFAULT FALSE,
    webhook_secret  TEXT,          -- HMAC-SHA256 secret for signature verification
    api_key         TEXT,          -- platform-issued API key (if needed)
    api_secret      TEXT,
    shop_id         VARCHAR(100),  -- platform's restaurant/venue ID
    notes           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);
INSERT INTO delivery_integrations (platform, display_name) VALUES
    ('wolt',      'Wolt'),
    ('foodpanda', 'Foodpanda'),
    ('ubereats',  'Uber Eats'),
    ('justeat',   'Just Eat / Takeaway'),
    ('generic',   'Generic Webhook');

-- ── Orders ────────────────────────────────────────────────────────────────────
CREATE SEQUENCE order_queue_seq START 1 MAXVALUE 9999 CYCLE;
CREATE TABLE orders (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    queue_number        INT DEFAULT nextval('order_queue_seq'),
    kiosk_machine_id    UUID REFERENCES machines(id),
    source              VARCHAR(20)  DEFAULT 'kiosk',   -- kiosk, wolt, foodpanda, ubereats, justeat, generic
    external_order_id   VARCHAR(100),                   -- platform's own order ID (prevents duplicates)
    customer_name       VARCHAR(100),
    delivery_notes      TEXT,
    status              VARCHAR(20)  DEFAULT 'pending'
                        CHECK (status IN ('pending','confirmed','preparing','ready','completed','cancelled')),
    subtotal            NUMERIC(10,2) DEFAULT 0,
    tax_amount          NUMERIC(10,2) DEFAULT 0,
    total_amount        NUMERIC(10,2) DEFAULT 0,
    payment_method      VARCHAR(30),
    payment_status      VARCHAR(20)  DEFAULT 'unpaid'
                        CHECK (payment_status IN ('unpaid','paid','refunded')),
    payment_ref         VARCHAR(255),
    note                TEXT,
    printed_kitchen     BOOLEAN DEFAULT FALSE,
    printed_receipt     BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, external_order_id)
);

-- ── Order lines ───────────────────────────────────────────────────────────────
CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id     INT  REFERENCES items(id),
    combo_id    INT  REFERENCES combos(id),
    name        VARCHAR(200) NOT NULL,   -- snapshot at order time
    unit_price  NUMERIC(10,2) NOT NULL,
    quantity    INT NOT NULL DEFAULT 1,
    line_total  NUMERIC(10,2) NOT NULL
);

-- ── Order item customizations ─────────────────────────────────────────────────
CREATE TABLE order_item_customizations (
    id              SERIAL PRIMARY KEY,
    order_item_id   INT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
    option_id       INT REFERENCES customization_options(id),
    option_name     VARCHAR(100) NOT NULL,
    extra_price     NUMERIC(8,2) DEFAULT 0
);

-- ── NAV Online Számla (Hungarian tax authority invoicing) ─────────────────────
-- Single-row configuration table for NAV API credentials and supplier data.
CREATE TABLE nav_settings (
    id                      SERIAL PRIMARY KEY,
    enabled                 BOOLEAN      DEFAULT FALSE,
    test_mode               BOOLEAN      DEFAULT TRUE,   -- use api-test.onlineszamla.nav.gov.hu
    -- Technical user credentials (from NAV Online Számla portal)
    nav_login               VARCHAR(100),
    nav_password_hash       TEXT,        -- SHA-512 of the NAV password (uppercase hex)
    nav_sig_key             TEXT,        -- Signature key (aláírási kulcs)
    nav_tax_number          VARCHAR(8),  -- 8-digit taxpayer ID (adószám első 8 jegy)
    -- Supplier (restaurant) data for invoice XML
    supplier_name           VARCHAR(255),
    supplier_tax_number     VARCHAR(15), -- Full 11-char: 12345678-1-23
    supplier_country        VARCHAR(2)   DEFAULT 'HU',
    supplier_postal_code    VARCHAR(10),
    supplier_city           VARCHAR(100),
    supplier_address_detail VARCHAR(255), -- e.g. "Kossuth Lajos utca 1."
    -- Invoice numbering (auto-reset each year)
    invoice_prefix          VARCHAR(20)  DEFAULT 'INV',
    invoice_seq             INTEGER      DEFAULT 0,
    invoice_year            INTEGER,
    -- Behaviour
    auto_submit             BOOLEAN      DEFAULT FALSE,  -- submit on order completion
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);
INSERT INTO nav_settings DEFAULT VALUES;

-- Invoice submission log — one row per invoice sent (or attempted) to NAV
CREATE TABLE nav_invoice_submissions (
    id               SERIAL PRIMARY KEY,
    order_id         UUID        REFERENCES orders(id) ON DELETE SET NULL,
    invoice_number   VARCHAR(100) UNIQUE NOT NULL,
    transaction_id   VARCHAR(100),        -- NAV transaction ID (from manageInvoice response)
    status           VARCHAR(20)  DEFAULT 'pending'
                     CHECK (status IN ('pending','submitted','done','error','aborted')),
    invoice_xml      TEXT,                -- the InvoiceData XML sent to NAV (for audit)
    nav_response     TEXT,                -- raw XML response from NAV
    error_message    TEXT,
    submitted_at     TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX idx_nav_submissions_order  ON nav_invoice_submissions(order_id);
CREATE INDEX idx_nav_submissions_status ON nav_invoice_submissions(status);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_orders_status     ON orders(status);
CREATE INDEX idx_orders_created    ON orders(created_at DESC);
CREATE INDEX idx_orders_source     ON orders(source);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_items_category    ON items(category_id);

-- ── Auto update updated_at ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_orders_updated       BEFORE UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_items_updated        BEFORE UPDATE ON items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_integrations_updated BEFORE UPDATE ON delivery_integrations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_nav_settings_updated  BEFORE UPDATE ON nav_settings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_nav_invoices_updated  BEFORE UPDATE ON nav_invoice_submissions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Sample data ───────────────────────────────────────────────────────────────
INSERT INTO categories (name, sort_order) VALUES
  ('Burgers', 1), ('Pizza', 2), ('Drinks', 3), ('Desserts', 4), ('Sides', 5);

INSERT INTO items (category_id, name, description, price, is_promoted, sort_order) VALUES
  (1, 'Classic Burger',    'Beef patty, lettuce, tomato, onion',         8.50, TRUE,  1),
  (1, 'Cheese Burger',     'Double beef, cheddar cheese, pickles',       9.90, FALSE, 2),
  (1, 'Veggie Burger',     'Plant-based patty, fresh veggies',           8.00, FALSE, 3),
  (2, 'Margherita Pizza',  'Tomato sauce, mozzarella, basil',            11.00, TRUE, 1),
  (2, 'Pepperoni Pizza',   'Tomato sauce, pepperoni, mozzarella',        12.50, FALSE, 2),
  (3, 'Cola',              'Coca-Cola 330ml',                             2.50, FALSE, 1),
  (3, 'Orange Juice',      'Fresh squeezed orange juice',                3.00, FALSE, 2),
  (3, 'Water',             'Still mineral water 500ml',                  1.50, FALSE, 3),
  (4, 'Chocolate Cake',    'Rich chocolate layer cake',                   4.50, TRUE,  1),
  (5, 'French Fries',      'Crispy salted fries',                        3.50, FALSE, 1);

-- Customization for Classic Burger
INSERT INTO customization_groups (item_id, name, is_required, multi_select) VALUES
  (1, 'Choose Sauce', FALSE, TRUE),
  (1, 'Extras',       FALSE, TRUE);
INSERT INTO customization_options (group_id, name, extra_price) VALUES
  (1, 'Ketchup',     0.00), (1, 'Mayonnaise', 0.00),
  (1, 'Mustard',     0.00), (1, 'Jalapeño',   0.50),
  (2, 'Extra Cheese',0.80), (2, 'Bacon',      1.20),
  (2, 'Avocado',     1.00);
