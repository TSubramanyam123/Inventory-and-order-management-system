**1. Project Overview**\
**Project Title:** Inventory and Order Management System\
&#x20;Develop a web application where customers can browse products, manage shopping carts, place orders, track deliveries, apply discounts, and request returns. Administrators should be able to manage products, monitor inventory, process orders, analyze sales, and receive notifications.\
&#x20;The application must use independent microservices, with each service responsible for a specific business function.\
**2. Technology Stack**\
**Frontend:** React.js, HTML5, CSS3, JavaScript\
**Backend:** Python, FastAPI\
**Database:** SQLite\
**API Gateway:** FastAPI-based gateway or equivalent routing layer\
**Authentication:** JWT, secure password hashing, role-based access control\
**Message Broker:** RabbitMQ\
**Caching:** Redis\
**Background Processing:** Celery or RabbitMQ consumers\
**PDF Generation:** ReportLab or an equivalent library\
**API Testing:** Postman\
**Automated Testing:** Pytest\
**Version Control:** Git and GitHub\
**Containerization:** Docker and Docker Compose\
**3. Microservices Architecture**\
The application must contain the following independent services.\
**A. Authentication Service**\
&#x20;Implement customer registration and login.\
&#x20;Generate and validate access tokens.\
&#x20;Implement token expiration and refresh-token handling.\
&#x20;Support Customer, Administrator, and Inventory Manager roles.\
&#x20;Restrict protected APIs based on user permissions.\
&#x20;Store passwords using a secure password-hashing algorithm.\
**B. Product Catalog Service**\
&#x20;Create, update, retrieve, and delete products.\
&#x20;Maintain product names, descriptions, categories, brands, prices, and images.\
&#x20;Implement search, sorting, pagination, and category filtering.\
&#x20;Support filtering by price range, rating, and stock availability.\
&#x20;Provide recently viewed products, product comparisons, and product specifications.\
&#x20;Support bulk product imports using CSV files.\
&#x20;Prevent invalid prices and incomplete product records.\
**C. Inventory Service**\
&#x20;Maintain stock quantities for every product.\
&#x20;Support stock additions, deductions, and manual adjustments.\
&#x20;Implement automatic stock reservation during checkout.\
&#x20;Release reserved stock when a reservation expires or an order is cancelled.\
&#x20;Prevent negative inventory and overselling.\
&#x20;Configure low-stock thresholds.\
&#x20;Generate stock movement and audit reports.\
&#x20;Maintain inventory transaction history, including timestamps, reasons, and responsible users.\
**D. Shopping Cart and Wishlist Service**\
&#x20;Add, update, and remove products from the cart.\
&#x20;Maintain product quantities and calculate cart totals.\
&#x20;Persist cart data across sessions for authenticated users.\
&#x20;Validate product availability before checkout.\
&#x20;Allow customers to save products to a wishlist.\
&#x20;Prevent invalid quantities and unavailable items from being purchased.\
**E. Order Management Service**\
&#x20;Create orders and generate unique order numbers.\
&#x20;Calculate order totals, taxes, discounts, and shipping charges.\
&#x20;Validate inventory availability before confirming orders.\
&#x20;Maintain order statuses: Pending, Confirmed, Processing, Shipped, Delivered, and Cancelled.\
&#x20;Display order history and detailed order information.\
&#x20;Support eligible order cancellations and partial item cancellations.\
&#x20;Prevent duplicate order creation through idempotency controls.\
&#x20;Coordinate inventory updates and order status changes safely.\
**F. Payment Service**\
&#x20;Implement a simulated payment workflow or optional payment gateway integration using a test environment.\
&#x20;Support payment success, failure, and cancellation scenarios.\
&#x20;Maintain payment transaction references and statuses.\
&#x20;Handle duplicate payment requests safely.\
&#x20;Coordinate payment outcomes with order confirmation.\
&#x20;Do not store card numbers, CVVs, or other sensitive payment credentials.\
**G. Notification Service**\
&#x20;Send order confirmation, shipment, delivery, and cancellation notifications.\
&#x20;Provide in-app notifications and optional email notifications.\
&#x20;Notify administrators when stock falls below the configured threshold.\
&#x20;Process notification events asynchronously through RabbitMQ.\
&#x20;Implement retry handling for failed notifications.\
&#x20;Avoid sending duplicate notifications when an event is processed more than once.\
**H. Review and Rating Service**\
&#x20;Allow customers to submit product ratings and reviews.\
&#x20;Restrict reviews to eligible customers who purchased the product.\
&#x20;Display average ratings and review counts.\
&#x20;Allow customers to edit or delete their own reviews.\
&#x20;Provide moderation controls for administrators.\
**I. Coupon and Discount Service**\
&#x20;Create and manage coupon codes.\
&#x20;Support percentage-based and fixed-amount discounts.\
&#x20;Configure coupon expiry dates and usage limits.\
&#x20;Apply minimum purchase requirements.\
&#x20;Prevent expired, invalid, or repeatedly redeemed coupons from being used.\
&#x20;Validate discounts on the backend rather than trusting frontend calculations.\
**J. Return and Refund Service**\
&#x20;Allow customers to submit return requests.\
&#x20;Record return reasons and requested quantities.\
&#x20;Allow authorized administrators to approve or reject requests.\
&#x20;Track return statuses and refund progress.\
&#x20;Restore inventory only when the returned items are eligible and physically accepted.\
&#x20;Maintain a complete history of return and refund actions.\
**K. Analytics and Reporting Service**\
&#x20;Display total orders, sales revenue, and order status summaries.\
&#x20;Generate daily, weekly, and monthly sales reports.\
&#x20;Identify popular products and top-selling categories.\
&#x20;Display low-stock and out-of-stock product reports.\
&#x20;Track order cancellations and return rates.\
&#x20;Support date-range filters and downloadable CSV reports.\
**L. API Gateway**\
&#x20;Provide a centralized entry point for frontend API requests.\
&#x20;Route requests to the appropriate microservice.\
&#x20;Apply request validation, authentication checks, and rate limiting where appropriate.\
&#x20;Return consistent error responses.\
&#x20;Implement service timeouts and suitable handling of unavailable services.\
&#x20;Forward request correlation IDs to support debugging across services.\
**4. Frontend Requirements**\
Develop a responsive interface with separate customer and administrative experiences.\
**Customer Interface**\
&#x20;Registration and login pages.\
&#x20;Product catalog with search, filters, sorting, and pagination.\
&#x20;Product details page with images, specifications, reviews, and ratings.\
&#x20;Shopping cart and wishlist pages.\
&#x20;Checkout page with coupon application and simulated payment.\
&#x20;Order confirmation page.\
&#x20;Order history and delivery tracking timeline.\
&#x20;Return and refund request forms.\
&#x20;Notification center.\
&#x20;User profile and account settings.\
**Administrator Interface**\
&#x20;Dashboard with sales and order statistics.\
&#x20;Product creation and management pages.\
&#x20;Inventory management and stock adjustment screens.\
&#x20;Order processing and cancellation controls.\
&#x20;Coupon and discount management.\
&#x20;Review moderation.\
&#x20;Return and refund management.\
&#x20;Low-stock alerts and notification history.\
&#x20;Sales analytics and downloadable reports.\
&#x20;User and role management.\
&#x20;The frontend must include form validation, loading states, empty states, confirmation dialogs, success messages, and meaningful error messages.\
**5. API Requirements**\
Implement RESTful APIs with appropriate HTTP methods and status codes.\
**Authentication Service**\
&#x20;POST /auth/register\
&#x20;POST /auth/login\
&#x20;POST /auth/refresh\
&#x20;GET /auth/me\
**Product Service**\
&#x20;POST /products\
&#x20;GET /products\
&#x20;GET /products/{product_id}\
&#x20;PUT /products/{product_id}\
&#x20;DELETE /products/{product_id}\
&#x20;POST /products/bulk-import\
**Inventory Service**\
&#x20;GET /inventory\
&#x20;GET /inventory/{product_id}\
&#x20;PATCH /inventory/{product_id}/stock\
&#x20;POST /inventory/reservations\
&#x20;POST /inventory/reservations/{reservation_id}/release\
&#x20;GET /inventory/{product_id}/transactions\
**Cart and Wishlist Service**\
&#x20;GET /cart\
&#x20;POST /cart/items\
&#x20;PATCH /cart/items/{item_id}\
&#x20;DELETE /cart/items/{item_id}\
&#x20;GET /wishlist\
&#x20;POST /wishlist/items\
&#x20;DELETE /wishlist/items/{item_id}\
**Order Service**\
&#x20;POST /orders\
&#x20;GET /orders\
&#x20;GET /orders/my-orders\
&#x20;GET /orders/{order_id}\
&#x20;PATCH /orders/{order_id}/status\
&#x20;POST /orders/{order_id}/cancel\
**Payment Service**\
&#x20;POST /payments\
&#x20;GET /payments/{payment_id}\
&#x20;POST /payments/{payment_id}/cancel\
**Notification Service**\
&#x20;GET /notifications\
&#x20;PATCH /notifications/{notification_id}/read\
**Review Service**\
&#x20;POST /reviews\
&#x20;GET /products/{product_id}/reviews\
&#x20;PUT /reviews/{review_id}\
&#x20;DELETE /reviews/{review_id}\
**Coupon Service**\
&#x20;POST /coupons\
&#x20;GET /coupons\
&#x20;POST /coupons/validate\
**Return and Refund Service**\
&#x20;POST /returns\
&#x20;GET /returns/my-returns\
&#x20;GET /returns/{return_id}\
&#x20;PATCH /returns/{return_id}/status\
**Analytics Service**\
&#x20;GET /analytics/sales\
&#x20;GET /analytics/orders\
&#x20;GET /analytics/inventory\
&#x20;GET /analytics/top-products\
&#x20;These endpoints are the baseline requirements. Additional APIs may be created as required by the application design.\
**6. Database Requirements**\
Create suitable database models and tables for:\
&#x20;Users and refresh tokens\
&#x20;Products and categories\
&#x20;Inventory and inventory transactions\
&#x20;Stock reservations\
&#x20;Shopping carts and cart items\
&#x20;Wishlists\
&#x20;Orders and order items\
&#x20;Payment transactions\
&#x20;Notifications\
&#x20;Product reviews and ratings\
&#x20;Coupons and coupon redemptions\
&#x20;Return requests and refund records\
&#x20;Audit logs\
&#x20;Each microservice must own its data and expose it through its APIs or events. Do not directly access another service's database.\
&#x20;Use appropriate constraints, timestamps, indexes, and validation rules. SQLite may be used for development, with separate database files for each service.\
**7. Inter-Service Communication and Event Processing**\
Use synchronous HTTP requests for operations that require an immediate response and RabbitMQ for asynchronous business events.\
&#x20;Implement event-driven workflows for:\
&#x20;Order created → inventory reservation and notification processing.\
&#x20;Payment succeeded → order confirmation.\
&#x20;Payment failed → order cancellation or pending-payment handling.\
&#x20;Order shipped → customer notification.\
&#x20;Order delivered → delivery notification and review eligibility.\
&#x20;Stock below threshold → administrator notification.\
&#x20;Return accepted → inventory restoration and refund processing.\
&#x20;Use durable messaging, retries, idempotent consumers, and dead-letter handling. Ensure that failures between services do not result in duplicate stock deductions, duplicate refunds, or inconsistent order statuses.\
&#x20;For stronger reliability, implement an outbox pattern or an equivalent mechanism for publishing important business events.\
**8. Security Requirements**\
Use secure password hashing.\
&#x20;Protect endpoints with JWT authentication and role-based authorization.\
&#x20;Validate inputs on both the frontend and backend.\
&#x20;Store credentials and secrets in environment variables.\
&#x20;Configure CORS appropriately.\
&#x20;Implement rate limiting for login and other sensitive endpoints.\
&#x20;Prevent unauthorized access to other customers' orders and notifications.\
&#x20;Protect administrative operations with server-side permission checks.\
&#x20;Record important security and administrative events in audit logs.\
&#x20;Avoid logging passwords, tokens, or sensitive payment data.\
**9. Testing Requirements**\
Write unit tests for business logic.\
&#x20;Write API integration tests for every microservice.\
&#x20;Test authentication, authorization, and invalid inputs.\
&#x20;Test stock availability, reservations, order cancellations, and concurrent order attempts.\
&#x20;Test successful and failed payment scenarios.\
&#x20;Verify coupon expiry and redemption limits.\
&#x20;Test RabbitMQ retry handling and duplicate event processing.\
&#x20;Test service failure scenarios and gateway error responses.\
&#x20;Verify that customers cannot access another customer's private records.\
&#x20;Prepare a Postman collection containing successful and failure test cases.\
**10. Deployment and DevOps Requirements**\
Provide a Dockerfile for each backend service and the frontend.\
&#x20;Use Docker Compose to start the application components.\
&#x20;Configure environment variables using an example environment file.\
&#x20;Add health-check endpoints for the services.\
&#x20;Provide structured application logs and request correlation IDs.\
&#x20;Document database initialization and migration procedures.\
&#x20;Include clear startup, shutdown, and troubleshooting instructions.\
&#x20;Ensure that the application can be run locally using the documented commands.\
&#x20;Kubernetes and cloud deployment are optional extensions, not mandatory requirements.\
**11. Expected Deliverables**\
The final submission must include:\
&#x20;Complete React frontend source code.\
&#x20;Separate FastAPI applications for all required microservices.\
&#x20;API Gateway implementation.\
&#x20;Database models and initialization or migration scripts.\
&#x20;RabbitMQ event-processing implementation.\
&#x20;Redis caching and rate-limiting implementation where applicable.\
&#x20;Authentication and role-based authorization.\
&#x20;Dockerfiles and Docker Compose configuration.\
&#x20;Postman collection with API test cases.\
&#x20;Automated tests using Pytest.\
&#x20;Swagger/OpenAPI documentation.\
&#x20;GitHub repository with organized source code and meaningful commit history.\
&#x20;README containing project architecture, prerequisites, environment variables, setup instructions, and run commands.\
&#x20;Screenshots demonstrating customer workflows, administrative dashboards, and API responses.\
**12. Evaluation Criteria**\
The project will be evaluated based on:\
&#x20;Frontend design and usability.\
&#x20;Backend API functionality and code quality.\
&#x20;Microservices separation and database ownership.\
&#x20;Authentication and authorization.\
&#x20;Inventory accuracy and order consistency.\
&#x20;Reliable inter-service communication.\
&#x20;Event processing and failure recovery.\
&#x20;Security and input validation.\
&#x20;Automated testing and API documentation.\
&#x20;Docker-based execution and project documentation.\
**13. Completion Criteria**\
The application must demonstrate a complete end-to-end workflow: a customer logs in, browses products, adds items to a cart, applies a valid coupon, checks out, completes a simulated payment, receives an order confirmation, tracks the order, and requests a return when eligible.\
&#x20;The administrator must be able to manage products, monitor inventory, process orders and returns, receive low-stock alerts, and review sales analytics.\
&#x20;All critical workflows must be tested, and the application must start successfully using the documented setup instructions.\
&#x20;Please ensure that the implementation follows clean coding practices, maintains data consistency across services, and includes all required source code, tests, and documentation. &#x20;