# Backend test organization

Tests have one primary directory and marker:

- `unit/`: isolated business logic; these tests must run without PostgreSQL.
- `integration/`: FastAPI, PostgreSQL/PostGIS, filesystem, worker, and WebSocket integration.
- `security/`: dedicated authentication, authorization, and malformed-input boundaries.
- `system/`: cross-feature API user journeys.
- `stress/`: deterministic course-sized concurrency and overload checks.
- `support/`: shared test-database helpers; it is not collected as a test category.

Security is also a cross-cutting marker. Relevant tests remain beside their unit
or integration feature and use `@pytest.mark.security`, so the security suite
can select them without duplicating scenarios.

The root `conftest.py` configures the test environment but does not connect to
PostgreSQL during collection. Database-backed directories opt into lazy schema
creation and per-test cleanup through their local `conftest.py` files.

Run a category with `pytest -q -m <category>`, or run `pytest -q` for the full
suite.
