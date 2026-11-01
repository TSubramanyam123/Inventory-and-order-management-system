# Northstar — Inventory and Order Management (Backend Only)

A backend-only Inventory and Order Management System built with **11 independent FastAPI business microservices plus a FastAPI API Gateway**. The React frontend has intentionally been removed from this submission scope. APIs can be exercised through Swagger UI or the included Postman collection.

## Architecture

The gateway is the single public API entry point. Each service owns its own SQLite database and communicates with other services through authenticated HTTP APIs or RabbitMQ events. No service directly reads another service's database.

| Application | Port | Responsibility |
|---|---:|---|
| API Gateway | 8000 | Routing, JWT checks, timeouts, rate limiting, correlation IDs, combined OpenAPI |
| Authentication | 8001 | Registration, login, JWT, refresh-token rotation, roles |
| Product Catalog | 8002 | Product CRUD, search, filters, pagination, CSV import, comparisons |
| Inventory | 8003 | Stock, reservations, stock movements, thresholds |
| Cart & Wishlist | 8004 | Persistent carts, quantities, wishlists |
| Orders | 8005 | Checkout, order lifecycle, idempotency, cancellation, invoices |
| Payments | 8006 | Simulated payments, transaction records, refunds |
| Notifications | 8007 | In-app notifications and event consumers |
| Reviews | 8008 | Verified-purchase ratings, reviews, moderation |
| Coupons | 8009 | Discount rules, validation, redemption limits |
| Returns & Refunds | 8010 | Return requests, inspection, restock/refund coordination |
| Analytics | 8011 | Sales, order, inventory and product reports |

Infrastructure: RabbitMQ for durable asynchronous events, Redis for caching/rate limiting, SQLite with one database file/volume per service. Docker Compose starts the gateway, all services, RabbitMQ and Redis. The gateway is exposed at `http://localhost:8000`.

## Implemented backend capabilities

- JWT access tokens, expiring/rotating refresh tokens, scrypt password hashing and role-based access control.
- Product CRUD, search, sort, pagination, filters, comparisons, recently viewed items and validated CSV import.
- Atomic stock reservations, expiry/release, audit history, low-stock thresholds and overselling protection.
- Persistent carts/wishlists, checkout validation, server-side totals, coupon validation and idempotent order creation.
- Order status transitions, delivery tracking history, full/partial cancellation and PDF invoices.
- Simulated payment success/failure/cancellation, transaction references and idempotent refunds; no card details are stored.
- Asynchronous notifications, event deduplication, retries, dead-letter handling and transactional outbox records.
- Verified-purchase reviews, coupon usage limits, return eligibility, physical acceptance, inventory restoration and refund processing.
- Analytics endpoints and downloadable CSV reports.
- Health endpoints, structured logs, correlation IDs, service timeouts and consistent API errors.

The payment workflow is intentionally simulated. Email delivery, a real payment provider, Kubernetes and cloud hosting are optional extensions and are not configured.

## Prerequisites

- Python 3.12
- Docker Desktop / Docker Engine with Docker Compose V2
- Postman (recommended for the supplied test collection)

## Quick start (Docker — recommended)

Run from the extracted `inventory-order-system` directory:

```bash
python scripts/setup_env.py
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec auth python scripts/seed.py --users-only
docker compose exec gateway python scripts/seed.py --api-only
```

Open API documentation: **http://localhost:8000/api/docs**. Combined OpenAPI JSON: `http://localhost:8000/api/openapi.json`.

Read the generated local demo credentials from `.env`:

```bash
# Windows PowerShell
Get-Content .env | Select-String "^(ADMIN|CUSTOMER|MANAGER)_(EMAIL|PASSWORD)="
# macOS/Linux
grep -E '^(ADMIN|CUSTOMER|MANAGER)_(EMAIL|PASSWORD)=' .env
```

The seeded coupon is `WELCOME10`. Demo credentials are local-only; change them before using the system outside a local evaluation environment.

## Local Python run (without Dockerized services)

RabbitMQ and Redis are still required for the full infrastructure workflow. Start them first:

```bash
python scripts/setup_env.py
python -m venv .venv
# Windows: .venv\\Scripts\\python.exe -m pip install -r requirements.txt
# macOS/Linux: .venv/bin/python -m pip install -r requirements.txt
docker compose up -d rabbitmq redis
python scripts/migrate.py
python scripts/seed.py --users-only
python scripts/run.py
```

In a second terminal, seed catalog data:

```bash
python scripts/seed.py --api-only
```

## Testing checklist

### 1. Automated tests

```bash
python -m pip install -r requirements.txt
python -m pytest -v
```

The default suite uses isolated SQLite databases and the real FastAPI service applications via ASGI transports. It covers authentication/authorization, validation, stock concurrency, reservations, checkout/payment idempotency, cancellation/refunds, coupon rules, event replay/retry, return workflows, gateway failures, analytics and PDFs.

For live RabbitMQ/Redis integration tests, start the Compose stack and run:

```bash
docker compose run --rm --no-deps -e RUN_INFRA_TESTS=true -e WORKERS_ENABLED=false gateway python -m pytest tests/test_live_infrastructure.py -v
```

### 2. Service health

```bash
docker compose ps
docker compose exec gateway python scripts/health.py
```

### 3. Postman end-to-end collection

1. Import `postman/Inventory.postman_collection.json`.
2. Import `postman/Local.postman_environment.json` and select **Northstar Local**.
3. Set `admin_email` and `admin_password` using the values in your `.env` file.
4. Run the collection in order, one iteration, with a 500 ms delay. It contains 63 requests covering successful and failure cases.
5. Run it against a fresh database/catalog when possible. The seed operation is intentionally non-destructive; repeated collection runs may encounter existing records or usage limits.

### 4. Manual critical workflow in Swagger

Use `/api/docs` and the seeded credentials to verify:

1. Register/login and obtain an access token; authorize protected endpoints.
2. Browse/filter products and inspect product details.
3. Add an item to cart and validate `WELCOME10`.
4. Create an order using `Idempotency-Key`; verify inventory reservation.
5. Simulate a successful payment; verify order becomes Confirmed and stock is deducted once.
6. Move the order through Processing → Shipped → Delivered using an authorized staff account.
7. Submit a review for the delivered purchase.
8. Submit a return; approve it, then mark it physically accepted. Verify only acceptance restores stock and triggers the refund.
9. Check notifications and analytics reports.
10. Repeat with failed/cancelled payment and invalid/duplicate requests to verify compensation and idempotency.

## Database initialization and migration

`python scripts/migrate.py` initializes the service-owned schemas idempotently. Service startup also initializes only its own database. Docker named volumes persist between restarts. For future schema changes, stop services, back up each SQLite database, add a versioned migration, and test it against a backup before deployment.

## Configuration and security

`python scripts/setup_env.py` creates a local `.env` with random JWT/service secrets and demo passwords without overwriting an existing file. Never commit `.env`. See `.env.example` for supported settings. Configure `CORS_ORIGINS` for any separately hosted client. Set `COOKIE_SECURE=true` behind HTTPS. Prices and amounts are integer paise (₹1 = 100); timestamps are Unix seconds unless otherwise stated.

## Repository contents

- `services/`: independent FastAPI applications and service business logic.
- `common/`: database helpers, security, event/outbox processing and runtime configuration.
- `tests/`: pytest unit/integration/workflow/recovery tests.
- `postman/`: collection and local environment.
- `scripts/`: environment setup, database initialization, seed, launcher and health checks.
- `docs/`: architecture, API reference, requirements matrix, source assignment and validation notes.
- `docker-compose.yml` and per-service Dockerfiles.

## GitHub submission

The ZIP is a local source package; it has not been pushed to a GitHub remote. To publish it, create an empty repository on GitHub, then run:

```bash
git init
git add .
git commit -m "Submit inventory and order management backend"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Do not add `.env`, local databases, secrets or generated virtual environments to Git.
