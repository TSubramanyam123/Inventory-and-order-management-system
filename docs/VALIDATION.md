# Validation and submission notes

## Evidence already recorded with the source project

The project archive was supplied with a validation record dated 26 October 2026. It reports:

- 30 Pytest tests passed using the actual FastAPI applications, isolated SQLite databases and ASGI HTTP transports.
- 63 Postman requests and 66 assertions passed in the recorded test harness.
- Python source compilation and database schema initialization passed.
- The original React application had a successful production build and browser workflow checks. **The frontend has since been removed from this backend-only package, so those UI checks are not part of this submission.**

These are historical results included with the supplied project, not a claim that this current packaging environment reran them.

## Independent checks performed while preparing the backend-only package

- All Python files passed `python -m compileall -q common services scripts tests`.
- The Postman collection parsed as valid JSON and contains 63 top-level requests.
- The included Git source-history bundle cloned successfully and contains three commits.
- The frontend source and screenshots were removed; the Compose frontend service and frontend launch instructions were removed.

## Checks that remain to be run on the submission machine

This environment did not have the Python dependencies installed and could not reach the package index; Docker was also unavailable. Therefore, the following could not be independently executed during this packaging pass:

- `python -m pytest -v` (first install `requirements.txt`).
- `docker compose config --quiet` and `docker compose up --build -d --wait`.
- Live RabbitMQ and Redis integration tests.
- Running the Postman collection against the actual locally running Docker stack.

Do not state that Docker/RabbitMQ/Redis were verified until those checks pass on the machine used for submission.

## Recommended final evidence

Save terminal output for the test suite, Docker health checks, and Postman collection run. Capture screenshots of Swagger endpoints and successful API responses if the evaluator asks for evidence. The supplied screenshot folder was removed because it showed the frontend, which is outside the requested backend-only scope.
