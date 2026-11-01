# Architecture and operational design

## Ownership and persistence

Each application imports shared infrastructure helpers but instantiates a Store for its own service name. SQLite files are never opened by another running service. Administrative provisioning runs explicitly inside the auth service; demo catalog seeding uses HTTP. Each Docker service receives its own named volume mounted at `/data`.

Tables have an ID primary key, a valid JSON document, and creation/update timestamps. Public write contracts are Pydantic models in the owning service module. Functional unique indexes enforce email, refresh hash, customer checkout key, payment order, review owner/product, and reservation order uniqueness. All monetary values are integer paise. Inventory and coupon read-modify-write operations execute under `BEGIN IMMEDIATE`.

This is a compact reference implementation using typed JSON documents in named SQLite tables. It does not use an ORM. Stock invariants are checked inside the same locked transaction that writes quantities, reservations and stock movements. Negative stock, negative reservations and `reserved > quantity` abort the transaction.

## Order and stock workflow

1. The authenticated customer's current cart is fetched through the cart API. Prices come from the catalog, not browser totals.
2. A unique customer/request-key order intent is committed with phase `preparing`. Reusing the key with different address/coupon details returns 409.
3. Coupon redemption uses order ID as its atomic operation key. The inventory service atomically reserves all product lines or rejects all of them.
4. The order records the reservation and authoritative totals and emits `order.created` in the same transaction. This event verifies the reservation boundary and is consumed for event history; the synchronous reservation ensures immediate checkout feedback.
5. Payment stores a single simulated outcome and event atomically. A successful event commits the inventory reservation and confirms the order. Confirmations and cart clearing are idempotent.
6. An unpaid reservation expires after the configured TTL. Inventory emits `reservation.expired`; the order cancels and releases coupon usage. Payment arriving after expiry receives a compensating simulated refund.
7. An interrupted preparing/cancelling order is revisited by a maintenance loop. Outages return a retryable 503; the client must retry with the same request key.

Order status transitions:

`Pending → Confirmed → Processing → Shipped → Delivered`

`Pending / Confirmed / Processing → Cancelled`

Partial cancellation is permitted only after payment and before shipment. It records a durable compensation operation, then restores the cancelled quantity and issues an allocated refund using the same operation ID. Cancelling the remainder waits for previous partial compensation and refunds only the remaining paid value. Invalid status transitions return 409.

## Return workflow

`Requested → Approved → Accepted → Refunded`

`Requested / Approved → Rejected`

Only delivered, uncancelled units inside `RETURN_WINDOW_DAYS` qualify. Requests reserve distinct eligible unit slots across active return requests. This gives deterministic refund rounding even if a prior request is rejected and a later request reuses a unit slot. Approval alone does not change stock. An administrator explicitly accepts physically received, eligible goods. Acceptance commits intent, restores stock and requests a simulated refund with operation ID `return:<id>`. A restart or timeout after either step safely resumes without duplicate stock or refunds. History records actors, notes and timestamps.

## Event delivery

Each SQLite service includes `outbox`, `inbox` and `audit_logs` tables. Business changes and important event creation are transactional. The worker declares the complete durable subscription topology before publishing, preventing startup order from losing messages for a service that has not connected yet.

- Durable fanout exchange: `business`.
- Durable queue per service: `<service>.events`.
- Persistent messages and publisher confirms.
- Publisher marks an outbox row published only after confirmation.
- Consumer prefetch is 1; acknowledgements follow successful handling.
- Inbox IDs are recorded after the handler completes.
- Downstream business operations have their own unique operation IDs.
- Failed handlers retry with exponential delay, up to `EVENT_MAX_ATTEMPTS`.
- Retry republishing is confirmed before acknowledging the original message.
- Exhausted messages are rejected to the durable `dead` exchange and `<service>.dead` queue.
- Reconnection retries every five seconds; unsent outbox rows remain persistent.

Inspect dead-letter queues in RabbitMQ management. Correct the underlying error, then replay the message without changing its event ID. Idempotent consumers and operation keys make replay safe. Do not delete outbox/inbox records during normal operations. A production retention policy should archive old records after the business replay window.

The worker uses at-least-once delivery. Publisher confirms and acknowledgements cover different failure boundaries; duplicates remain possible and are handled at the application level. See [RabbitMQ reliability](https://www.rabbitmq.com/docs/reliability) and [publisher/consumer acknowledgements](https://www.rabbitmq.com/docs/confirms).

## Security and gateway

Passwords use scrypt with a per-password random salt and constant-time comparison. JWTs require issuer/audience/signature/expiry validation. Refresh tokens are random secrets stored only as hashes in SQLite and delivered in HttpOnly SameSite cookies; successful refresh revokes the prior refresh token. Staff permissions are checked against the current auth record on each privileged operation, so role demotion takes effect without waiting for token expiry.

Clients should keep access tokens in memory. A client can exchange the HttpOnly refresh cookie for a new access token when needed. Logout revokes that refresh token; already issued access tokens retain their short lifetime (15 minutes by default). Password changes revoke refresh tokens. Local HTTP uses `COOKIE_SECURE=false`; a real HTTPS deployment must enable Secure cookies.

Internal endpoints require the environment-defined service secret. The gateway never forwards a caller's internal secret and never routes `/internal/*`. Inventory reservation APIs are also service-authenticated and are called directly by the order service. Public gateway calls cannot reserve arbitrary stock.

The gateway validates JWTs for private routes, limits traffic with Redis, strips unneeded forwarded headers, enforces a request-size bound, passes correlation IDs, applies timeouts, and returns 503/504 for unavailable/timed-out services. Services also enforce ownership and roles. Cart, orders, payments, notifications, reviews and returns protect customer records independently of UI behavior.

Login also has IP and account rate limits. Redis uses an atomic Lua INCR/EXPIRE operation. Compose requires Redis and fails closed during its outage. Local development permits a bounded in-memory rate fallback when `REQUIRE_INFRA=false`.

## Cache, analytics and money

Catalog documents are cached in Redis for 15 seconds with a version key invalidated on catalog writes. Live inventory and review summaries are fetched separately so a cached catalog does not make stock decisions. Checkout reservations remain authoritative.

Analytics receives order projections and reconciles report data using source APIs. Sales subtract cancelled quantities and completed return refunds. CSV includes paid totals less cancellations, with an explicit column name; return/refund details are available through return APIs. Date filters select orders by creation time, and return rates count non-rejected return requests for those orders. Reports use UTC day/ISO-week/month buckets.

Tax uses decimal half-up rounding. Checkout assigns the full paid total across product lines proportionally, and return/cancellation refunds allocate units deterministically. Shipping and tax are refundable under this sample policy. This is configurable business-demo logic, not a jurisdiction-specific tax or shipping integration.

## Deployment boundaries

The provided setup intentionally runs one Uvicorn process per service. Orders and returns use process-local saga locks plus durable intents. SQLite locks protect atomic stock and coupon updates. Before horizontal scaling, move saga serialization into database leases/distributed locking, adopt a server database, configure TLS, rotate infrastructure credentials, and define retention/monitoring policies. These are deployment extensions, not claims about the local reference system.

Dockerfiles use a non-root application user and health checks. Ports bind to loopback. RabbitMQ/Redis credentials in Compose are explicitly for local development. The application starts from `services.<name>:app`; compatibility imports are also supplied under `services/<name>_service/main.py`.
