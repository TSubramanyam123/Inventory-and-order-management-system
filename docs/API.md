# API guide

External clients and Postman call `http://localhost:8000` directly. Interactive combined documentation is `/api/docs` on the gateway, and the JSON schema is `/api/openapi.json`.

Authentication uses `Authorization: Bearer <access_token>`. Refresh is an HttpOnly cookie set at login, rotated at `POST /auth/refresh`, and revoked by `POST /auth/logout`. Postman should retain cookies. JWT access tokens expire after 15 minutes by default.

## Baseline endpoints

| Service | Endpoints | Access |
| --- | --- | --- |
| Auth | POST `/auth/register`, `/auth/login`, `/auth/refresh`; GET `/auth/me` | Public registration/login; refresh cookie; authenticated me |
| Products | GET/POST `/products`; GET/PUT/DELETE `/products/{id}`; POST `/products/bulk-import` | Reads public; writes staff |
| Inventory | GET `/inventory`, `/inventory/{id}`, `/inventory/{id}/transactions`; PATCH `/inventory/{id}/stock` | Administrator or Inventory Manager |
| Reservations | POST `/inventory/reservations`, `/inventory/reservations/{id}/release` | Internal service secret; direct inventory API |
| Cart | GET `/cart`; POST `/cart/items`; PATCH/DELETE `/cart/items/{id}` | Owner |
| Wishlist | GET `/wishlist`; POST `/wishlist/items`; DELETE `/wishlist/items/{id}` | Owner |
| Orders | POST `/orders`; GET `/orders/my-orders`, `/orders/{id}`; POST `/orders/{id}/cancel` | Owner |
| Order processing | GET `/orders`; PATCH `/orders/{id}/status`; POST `/orders/{id}/admin-cancel` | Administrator |
| Payments | POST `/payments`; GET `/payments/{id}`; POST `/payments/{id}/cancel` | Owner |
| Notifications | GET `/notifications`; PATCH `/notifications/{id}/read` | Owner |
| Reviews | POST `/reviews`; GET `/products/{id}/reviews`; PUT/DELETE `/reviews/{id}` | Public reads; verified owner writes |
| Coupons | POST/GET `/coupons`; PUT `/coupons/{code}`; POST `/coupons/validate` | Administrator management; authenticated validation |
| Returns | POST `/returns`; GET `/returns/my-returns`, `/returns/{id}` | Owner |
| Return processing | GET `/returns`; PATCH `/returns/{id}/status` | Administrator |
| Analytics | GET `/analytics/sales`, `/analytics/orders`, `/analytics/inventory`, `/analytics/top-products`, `/analytics/export` | Administrator |

Extra endpoints include profile/password changes, user/role administration, recent views, comparison, category lists, moderation, admin notification history and PDF invoices. OpenAPI exposes all public API schemas. Internal APIs are deliberately omitted from gateway OpenAPI but remain in individual service schemas.

## Examples

Create a product as staff; amounts are **paise**, so this price is ₹1,499:

```json
{
  "name": "Travel Bottle",
  "description": "Insulated stainless steel travel bottle",
  "category": "Travel",
  "brand": "Fieldwork",
  "price": 149900,
  "specifications": {"Capacity": "750 ml", "Warranty": "1 year"}
}
```

`GET /products?q=travel&category=Travel&min_price=50000&max_price=200000&min_rating=4&in_stock=true&sort=price_asc&page=1&page_size=12`

Sort values: `newest`, `price_asc`, `price_desc`, `name`, `rating`. Search also matches descriptions/brands. Brand filtering is available as `brand=...`. Comparison accepts 2–4 comma-separated product IDs at `/products/compare?ids=id1,id2`.

Stock addition or deduction:

```json
{"delta": 20, "threshold": 5, "reason": "Received supplier shipment"}
```

Add a cart line:

```json
{"product_id": "PRODUCT_ID", "quantity": 2}
```

Checkout must include an `Idempotency-Key` header of 8–100 characters. Reuse it if a request times out:

```json
{"address": "Demo Customer, 123 Example Street, Hyderabad 500001", "coupon": "WELCOME10"}
```

Simulate a payment using its own stable `Idempotency-Key`:

```json
{"order_id": "ORDER_ID", "outcome": "success"}
```

Outcomes are `success`, `failure`, `cancel`. A failed/cancelled attempt closes its order asynchronously; create a new order to retry payment. No card number/CVV fields are accepted. Payment success is recorded immediately; confirmation follows through the event worker. Poll the order until it becomes Confirmed or Cancelled.

Full cancellation:

```json
{"reason": "Customer requested cancellation"}
```

Partial cancellation needs an `Idempotency-Key`:

```json
{"product_id": "PRODUCT_ID", "quantity": 1, "reason": "Ordered too many units"}
```

Return submission also requires an `Idempotency-Key`:

```json
{
  "order_id": "ORDER_ID",
  "reason": "Item arrived with damage",
  "items": [{"product_id": "PRODUCT_ID", "quantity": 1}]
}
```

A return approval payload is `{"status":"Approved","note":"Return label issued"}`. After physical receipt, use `{"status":"Accepted","note":"Item received and inspected"}`. A successful acceptance response reaches `Refunded`; an unavailable dependency leaves a durable Accepted request for retry/recovery.

## CSV import

Upload multipart form field `file` to `/products/bulk-import`. Limit: 2 MB / 1,000 rows. All rows validate before any row is written. Required headers: `name,description,category,brand,price`. Optional: `image,specifications`; specifications is escaped JSON inside a CSV field. See `docs/sample-products.csv`.

## Error and retry behavior

- 400: failed business validation, such as invalid coupon or empty cart.
- 401: missing/expired authentication; refresh and retry where appropriate.
- 403: role/ownership restriction.
- 404: missing resource.
- 409: stock conflict, invalid state transition, duplicate review, reused key with different contents.
- 413: request/import too large.
- 422: invalid schema, quantity, price or value.
- 429: rate limit; wait one minute.
- 503: service/infrastructure unavailable.
- 504: gateway timeout.

Errors include `error.message`, `detail`, and a correlation ID. Field validation returns field/message issues without echoing secret input values. Record the `X-Correlation-ID` response header when reporting a problem. Retry checkout, payment, partial cancellation and returns with the **same** request key and payload after an uncertain response.
