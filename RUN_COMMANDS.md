# Backend run commands

Run all commands from the extracted `inventory-order-system` directory.

## Docker Desktop (recommended)

```powershell
python scripts/setup_env.py
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec auth python scripts/seed.py --users-only
docker compose exec gateway python scripts/seed.py --api-only
Start-Process "http://localhost:8000/api/docs"
docker compose ps
docker compose exec gateway python scripts/health.py
docker compose run --rm --no-deps -e WORKERS_ENABLED=false gateway python -m pytest -v
docker compose down
```

Get generated demo credentials:

```powershell
Get-Content .env | Select-String "^(ADMIN|CUSTOMER|MANAGER)_(EMAIL|PASSWORD)="
```

## Local Python services

```powershell
python scripts/setup_env.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d rabbitmq redis
.\.venv\Scripts\python.exe scripts/migrate.py
.\.venv\Scripts\python.exe scripts/seed.py --users-only
.\.venv\Scripts\python.exe scripts/run.py
```

In a second terminal:

```powershell
.\.venv\Scripts\python.exe scripts/seed.py --api-only
```

Swagger is at `http://localhost:8000/api/docs`. Stop local services with Ctrl+C. Databases are stored in `data/`.

## Automated and live infrastructure tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
docker compose run --rm --no-deps -e RUN_INFRA_TESTS=true -e WORKERS_ENABLED=false gateway python -m pytest tests/test_live_infrastructure.py -v
```

The second command requires running Redis and RabbitMQ containers. The normal test suite uses isolated SQLite databases and an in-process event pump; it does not prove that real broker/network delivery works.

## Postman

Import `postman/Inventory.postman_collection.json` and `postman/Local.postman_environment.json`, select **Northstar Local**, set the admin credentials from `.env`, then run the 63-request collection in order with one iteration and a 500 ms delay. Use a clean database for repeatable runs.

## Troubleshooting

- Docker engine not running: start Docker Desktop and wait for it to become ready.
- Port already in use: check ports 8000–8011, 5672, 6379 and 15672.
- Login temporarily unavailable: inspect `docker compose logs redis gateway auth`.
- Order remains Pending: inspect `docker compose logs orders payments rabbitmq`.
- Database locked: run one process per service; do not run local and Docker stacks against the same data directory.
- Module not found: install `requirements.txt` in the active Python 3.12 environment and run commands from the project root.
- Do not use `docker compose down -v` unless you intend to delete all persistent databases and broker data.
