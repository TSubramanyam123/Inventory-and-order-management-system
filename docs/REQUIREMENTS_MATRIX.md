# Backend requirements coverage

The React client has been intentionally excluded from this backend-only submission. The REST APIs are available through the gateway Swagger UI and Postman collection.

| Requirement area | Backend implementation | Verification included |
|---|---|---|
| Independent services and database ownership | 11 business FastAPI services, separate SQLite stores/volumes | Service health and workflow tests |
| Authentication, JWT, refresh, roles, password hashing | `services/auth.py`, `common/security.py`, `common/runtime.py` | Auth, role, token rotation, password and rate-limit tests |
| Product catalog | `services/products.py` | CRUD, filtering, sorting, pagination, CSV and validation tests |
| Inventory | `services/inventory.py` | Atomic stock changes, reservations, expiry, release, concurrency tests |
| Cart and wishlist | `services/cart.py` | Persistence, quantity validation and ownership tests |
| Orders | `services/orders.py` | Checkout, order state, history, cancellation and idempotency tests |
| Payments | `services/payments.py` | Simulated success/failure/cancel, duplicate requests and refund tests |
| Notifications | `services/notifications.py` | Event replay, duplicate suppression and retry tests |
| Reviews | `services/reviews.py` | Verified purchase, owner access and moderation tests |
| Coupons | `services/coupons.py` | Expiry, minimum purchase, redemption limit and repeat-use tests |
| Returns/refunds | `services/returns.py` | Eligibility, partial quantities, acceptance, restock and refund recovery tests |
| Analytics | `services/analytics.py` | Sales/order/inventory/top-products and CSV tests |
| API Gateway | `services/gateway.py` | Auth, routing, correlation IDs, timeout, unavailable service and OpenAPI tests |
| RabbitMQ event processing | `common/events.py` | Outbox/inbox, duplicate handling and retry tests; live broker tests are opt-in |
| Redis cache/rate limiting | Shared runtime/cache implementation | Fail-closed test; live Redis test is opt-in |
| Database initialization | `scripts/migrate.py` and service startup | Idempotent schema initialization |
| Containerization | Per-service Dockerfiles and `docker-compose.yml` | Docker startup must be run on a host with Docker installed |
| Pytest/Postman/Swagger | `tests/`, `postman/`, gateway OpenAPI | Automated tests and 63-request Postman collection |
| Documentation and version control | README, run guide, architecture/API docs, CI workflow, source history bundle | Local repository setup and GitHub push are submitter steps |

Optional real payment-provider integration, email delivery, Kubernetes and cloud deployment are not included. Payments are simulated as permitted by the assignment.
