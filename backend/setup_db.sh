#!/usr/bin/env bash
set -e
DB="restaurant_db"
USER="kiosk"
PASS="kiosk_pass"

sudo -u postgres psql <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$USER') THEN
    CREATE USER $USER WITH PASSWORD '$PASS';
  END IF;
END \$\$;
CREATE DATABASE $DB OWNER $USER;
GRANT ALL PRIVILEGES ON DATABASE $DB TO $USER;
SQL

sudo -u postgres psql -d "$DB" -f "$(dirname "$0")/../database/schema.sql"

# Grant table-level access to the app user.
# GRANT ALL ON DATABASE covers connect/schema rights only, NOT table rows.
# Tables are owned by postgres (schema.sql runs as postgres), so we must
# explicitly grant SELECT/INSERT/UPDATE/DELETE on every table and sequence.
sudo -u postgres psql -d "$DB" <<SQL
GRANT ALL ON ALL TABLES    IN SCHEMA public TO $USER;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO $USER;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO $USER;
-- Make future tables/sequences created by postgres also accessible
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO $USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $USER;
SQL

# ── Migrations (add columns that may be missing on older installs) ─────────────
sudo -u postgres psql -d "$DB" <<SQL
ALTER TABLE settings ADD COLUMN IF NOT EXISTS kiosk_language VARCHAR(5) DEFAULT 'en';

-- Delivery platform integration columns (v2)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS source            VARCHAR(20)  DEFAULT 'kiosk';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_order_id VARCHAR(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_name     VARCHAR(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_notes    TEXT;

CREATE TABLE IF NOT EXISTS delivery_integrations (
    id              SERIAL PRIMARY KEY,
    platform        VARCHAR(30)  NOT NULL UNIQUE,
    display_name    VARCHAR(100),
    enabled         BOOLEAN      DEFAULT FALSE,
    webhook_secret  TEXT,
    api_key         TEXT,
    api_secret      TEXT,
    shop_id         VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO delivery_integrations (platform, display_name) VALUES
    ('wolt',      'Wolt'),
    ('foodpanda', 'Foodpanda'),
    ('ubereats',  'Uber Eats'),
    ('justeat',   'Just Eat / Takeaway'),
    ('generic',   'Generic Webhook')
ON CONFLICT (platform) DO NOTHING;

GRANT ALL ON TABLE delivery_integrations TO $USER;
GRANT ALL ON SEQUENCE delivery_integrations_id_seq TO $USER;
SQL

# ── NAV Online Számla tables (v3) ──────────────────────────────────────────────
sudo -u postgres psql -d "$DB" <<SQL
CREATE TABLE IF NOT EXISTS nav_settings (
    id                      SERIAL PRIMARY KEY,
    enabled                 BOOLEAN      DEFAULT FALSE,
    test_mode               BOOLEAN      DEFAULT TRUE,
    nav_login               VARCHAR(100),
    nav_password_hash       TEXT,
    nav_sig_key             TEXT,
    nav_tax_number          VARCHAR(8),
    supplier_name           VARCHAR(255),
    supplier_tax_number     VARCHAR(15),
    supplier_country        VARCHAR(2)   DEFAULT 'HU',
    supplier_postal_code    VARCHAR(10),
    supplier_city           VARCHAR(100),
    supplier_address_detail VARCHAR(255),
    invoice_prefix          VARCHAR(20)  DEFAULT 'INV',
    invoice_seq             INTEGER      DEFAULT 0,
    invoice_year            INTEGER,
    auto_submit             BOOLEAN      DEFAULT FALSE,
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);
INSERT INTO nav_settings DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS nav_invoice_submissions (
    id               SERIAL PRIMARY KEY,
    order_id         UUID        REFERENCES orders(id) ON DELETE SET NULL,
    invoice_number   VARCHAR(100) UNIQUE NOT NULL,
    transaction_id   VARCHAR(100),
    status           VARCHAR(20)  DEFAULT 'pending',
    invoice_xml      TEXT,
    nav_response     TEXT,
    error_message    TEXT,
    submitted_at     TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);

GRANT ALL ON TABLE  nav_settings             TO $USER;
GRANT ALL ON TABLE  nav_invoice_submissions  TO $USER;
GRANT ALL ON SEQUENCE nav_settings_id_seq             TO $USER;
GRANT ALL ON SEQUENCE nav_invoice_submissions_id_seq  TO $USER;
SQL

echo "✅ Database '$DB' ready."
