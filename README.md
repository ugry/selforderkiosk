# Restaurant Self-Order Kiosk

A complete self-ordering kiosk system for restaurants — touch-screen customer ordering, kitchen display, cashier station, and order monitor. Runs fully locally (no internet required) with high-availability backend.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Client Machines                        │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Kiosk   │  │ Kitchen  │  │ Cashier  │  │  Monitor   │  │
│  │ (PyQt5)  │  │ (PyQt5)  │  │ (PyQt5)  │  │  (PyQt5)   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
└───────┼─────────────┼─────────────┼───────────────┼─────────┘
        │             │             │               │
        └─────────────┴──────┬──────┴───────────────┘
                             │  HTTP / REST API (port 8080)
                    ┌────────▼────────┐
                    │    HAProxy LB   │   :8080 (API + Admin)
                    │                 │   :8404 (Stats)
                    └───┬─────────┬───┘
                        │         │  Round-robin + health check
              ┌─────────▼─┐   ┌───▼─────────┐
              │ Backend-1  │   │  Backend-2  │   FastAPI :8000
              └─────────┬──┘   └──┬──────────┘
                        │         │
              ┌─────────▼─────────▼──┐
              │     PostgreSQL 15    │
              ├──────────────────────┤
              │       Redis 7        │
              └──────────────────────┘
```

**Stack:** FastAPI 0.115 · Python 3.13 · SQLAlchemy 2.0 async · AsyncPG · PostgreSQL 15 · Redis 7 · HAProxy 2.9 · PyQt5 · Docker

---

## Features

- **Self-order kiosk** — full touch-screen menu, customizations, promotions, idle video
- **Kitchen display** — real-time order queue, status updates (pending → preparing → ready)
- **Cashier station** — unpaid order list, payment processing (cash/card/contactless), receipt printing
- **Order monitor** — customer-facing queue display with ready/completed columns
- **Admin panel** — web UI for menu, orders, machines, settings, VAT, currency, NAV invoicing
- **High availability** — 2 backend instances behind HAProxy; any node can go down without downtime
- **Dual-IP failover** — every client has primary + secondary backend IP; auto-switches on failure
- **Fully offline** — no external services required; runs on a local LAN
- **ESC/POS printing** — raw TCP port 9100 for kitchen tickets and receipts
- **Multilingual kiosk** — EN, TR, DE, HU, ES, FR, RU, AR (RTL supported)
- **Hungarian NAV invoicing** — automatic invoice submission on order completion

---

## Quick Start (Docker — recommended)

### Prerequisites

- Docker 24+ and Docker Compose v2
- 2 GB RAM, 4 GB disk

### 1. Clone and configure

```bash
git clone https://github.com/ugry/selforderkiosk.git
cd selforderkiosk

cp backend/.env.example .env
# Edit .env — at minimum change SECRET_KEY and ADMIN_PASSWORD
nano .env
```

`.env` variables:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(must change)* | Session signing key — use a random 32+ char string |
| `ADMIN_USERNAME` | `admin` | Admin panel login |
| `ADMIN_PASSWORD` | `admin123` | Admin panel password — **change this** |

### 2. Start the backend stack

```bash
docker compose up -d
```

This starts: PostgreSQL, Redis, two FastAPI backends, HAProxy.

| Service | URL |
|---|---|
| Admin panel | http://localhost:8080/admin/ |
| API | http://localhost:8080/api/v1/ |
| HAProxy stats | http://localhost:8080:8404/ |

> **Port conflict?** If 8080 is taken, change `"8080:8080"` to e.g. `"8090:8080"` in `docker-compose.yml`.

### 3. First-time setup in the admin panel

1. Go to **http://\<server-ip\>:8080/admin/**
2. Log in with your `ADMIN_USERNAME` / `ADMIN_PASSWORD`
3. **Settings** → set restaurant name, currency, VAT rate, colors
4. **Categories** → add menu categories (e.g. Burgers, Drinks)
5. **Items** → add menu items with prices and images
6. **Machines** → create entries for each physical device; copy the generated **API key**

---

## Client App Installation (physical machines)

Each client machine (kiosk touchscreen, kitchen monitor, cashier PC, order display) runs a PyQt5 desktop app that connects to the backend over the local network.

### Kiosk

```bash
# On the kiosk machine (Debian/Ubuntu)
git clone https://github.com/ugry/selforderkiosk.git
cd selforderkiosk/kiosk

sudo bash install_kiosk.sh
# Edit kiosk.ini with your server IP and API key
nano kiosk.ini

bash start_kiosk.sh          # start manually
# Or for autostart on boot:
startx                        # uses ~/.xinitrc set by installer
```

**kiosk.ini:**
```ini
[server]
primary_host   = 192.168.1.100   # HAProxy IP (primary)
primary_port   = 8080
secondary_host = 192.168.1.101   # HAProxy IP (secondary / second server)
secondary_port = 8080
api_key        = <paste key from admin panel>

[kiosk]
fullscreen     = true
idle_timeout   = 120             # seconds before idle video plays
language       = en              # en tr de hu es fr ru ar
printer_ip     =                 # optional ESC/POS printer IP
printer_port   = 9100
```

### Kitchen Display

```bash
cd selforderkiosk/kitchen
sudo bash install_kitchen.sh
nano kitchen.ini                 # set server IP + api_key
bash start_kitchen.sh
```

### Cashier Station

```bash
cd selforderkiosk/cashier
pip install -r requirements.txt
nano cashier.ini                 # set server IP + api_key
python3 cashier.py
```

### Order Monitor

```bash
cd selforderkiosk/order_monitor
sudo bash install_monitor.sh
nano monitor.ini                 # set server IP + api_key
bash start_monitor.sh
```

### Dual-IP Failover

All clients support a `secondary_host` for automatic failover. If the primary backend becomes unreachable the client switches to the secondary transparently and logs a warning. Configure both to point at different HAProxy instances (or direct backend IPs) for full redundancy:

```ini
[server]
primary_host   = 192.168.1.10   # HAProxy node 1
primary_port   = 8080
secondary_host = 192.168.1.11   # HAProxy node 2
secondary_port = 8080
```

---

## Running Clients in Docker (headless)

The client apps can also run in Docker containers using Xvfb as a virtual framebuffer — useful for testing or embedded deployments without a display server.

```bash
# Start client containers (uses Docker profiles)
docker compose --profile clients up -d

# Logs
docker logs kiosk-client   -f
docker logs kitchen-client -f
docker logs cashier-client -f
```

The `.ini` files are mounted read-only from the host. Edit them before starting:

```bash
nano kiosk/kiosk.ini
nano kitchen/kitchen.ini
nano cashier/cashier.ini
```

---

## Running the Test Suite

```bash
# 1. Get an API key from the running database
docker exec kiosk-postgres psql -U kiosk -d restaurant_db \
  -t -c "SELECT api_key FROM machines WHERE name='Kiosk-1' LIMIT 1;"

# 2. Run all 37 tests (API + Playwright browser tests)
docker compose --profile test run --rm \
  -e BASE_URL=http://haproxy:8080 \
  -e ADMIN_USER=admin \
  -e ADMIN_PASS=admin123 \
  -e TEST_API_KEY=<key from step 1> \
  tests
```

Test coverage:
- **test_health.py** — health endpoint, authentication rejection
- **test_api.py** — settings, categories, items, full order lifecycle (pending → completed), payment status update
- **test_admin_ui.py** — Playwright headless browser: login, settings, VAT quick-select, currency preset, machine creation, end-to-end order flow

---

## Backend: Manual / Development Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL separately, then:
export DATABASE_URL=postgresql+asyncpg://kiosk:kiosk_pass@localhost:5432/restaurant_db
export SECRET_KEY=dev-secret
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin123

uvicorn app.main:app --reload --port 8000
```

Admin panel: http://localhost:8000/admin/

---

## Existing Database Migration

If upgrading from a pre-HA version:

```bash
psql -U kiosk -d restaurant_db -f database/migrate_v2.sql
```

Adds the `waiting_video_url` column to the settings table.

---

## Directory Structure

```
selforderkiosk/
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── main.py           # App entry point, middleware
│   │   ├── config.py         # Settings via env vars
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── routes/
│   │   │   ├── api.py        # Public REST API (kiosk/kitchen/cashier)
│   │   │   ├── admin.py      # Admin web panel
│   │   │   └── webhooks.py   # Delivery platform webhooks
│   │   ├── services/
│   │   │   ├── printer.py    # ESC/POS over raw TCP
│   │   │   ├── nav_invoice.py# Hungarian NAV invoice API
│   │   │   └── auth.py       # API key authentication
│   │   └── templates/        # Jinja2 admin HTML templates
│   ├── tests/                # pytest + Playwright test suite
│   ├── Dockerfile
│   ├── Dockerfile.test
│   └── requirements.txt
├── kiosk/                    # Customer self-order touchscreen app
│   ├── kiosk.py
│   ├── translations.py       # EN/TR/DE/HU/ES/FR/RU/AR
│   ├── kiosk.ini
│   ├── Dockerfile
│   └── install_kiosk.sh
├── kitchen/                  # Kitchen display app
│   ├── kitchen.py
│   ├── kitchen.ini
│   ├── Dockerfile
│   └── install_kitchen.sh
├── cashier/                  # Cashier payment station app
│   ├── cashier.py
│   ├── cashier.ini
│   └── Dockerfile
├── order_monitor/            # Customer-facing queue display
│   ├── monitor.py
│   ├── monitor.ini
│   └── install_monitor.sh
├── database/
│   ├── schema.sql            # Full PostgreSQL schema
│   └── migrate_v2.sql        # Upgrade script for existing installs
├── haproxy/
│   └── haproxy.cfg           # Load balancer config
└── docker-compose.yml        # Full stack definition
```

---

## API Reference

All API endpoints require an `X-Api-Key` header (from the Machines page in the admin panel).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check (no auth) |
| `GET` | `/api/v1/settings` | Restaurant settings, currency, branding |
| `GET` | `/api/v1/categories` | Active menu categories |
| `GET` | `/api/v1/items` | Menu items (optional `?category_id=N`) |
| `POST` | `/api/v1/orders` | Create a new order |
| `GET` | `/api/v1/orders` | List orders (optional `?status=pending`) |
| `GET` | `/api/v1/orders/{id}` | Get single order |
| `PATCH` | `/api/v1/orders/{id}/status` | Update order status |
| `PATCH` | `/api/v1/orders/{id}/payment` | Mark order as paid (cashier) |
| `GET` | `/api/v1/queue` | Live queue for order monitor |
| `GET` | `/api/v1/completed` | Last 20 completed orders |

**Order statuses:** `pending` → `confirmed` → `preparing` → `ready` → `completed`

**Payment statuses:** `unpaid` → `paid` | `refunded`

---

## Printing

Receipts and kitchen tickets are sent over raw TCP to port 9100 (ESC/POS standard). Compatible with any network-connected thermal printer that supports ESC/POS (Epson TM series, Star, BIXOLON, etc.).

Configure printer IPs:
- **Kitchen printer** — Admin panel → Settings → Kitchen Printer
- **Receipt printer per machine** — Admin panel → Machines → edit machine

---

## License

MIT
