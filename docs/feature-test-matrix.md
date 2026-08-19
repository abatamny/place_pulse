# PlacePulse feature-to-test matrix

This list connects each implemented feature to its main automated evidence. External services are replaced with deterministic fakes; the test suite never calls OpenStreetMap, Twilio, or a paid AI provider.

| Feature or safeguard | Main automated coverage | Test level |
|---|---|---|
| Registration, demo-code fallback, SMS delivery/rollback, password hashing, login, logout, session revocation | `tests/integration/test_auth.py`, `tests/unit/test_sms.py` | Unit/integration/security |
| Authentication boundary across protected HTTP and WebSocket routes | `tests/security/test_security_boundaries.py`, relevant security-marked integration tests | Security |
| Expired sessions and hashed stored tokens | `tests/security/test_security_boundaries.py` | Security |
| Authentication and feature rate limits, including reconnect-resistant KNOCK limiting | `tests/unit/test_request_protection.py`, security-marked feature tests | Unit/security |
| Strict malformed-input handling and backend-wide request-body cap | `tests/unit/test_request_protection.py`, `tests/unit/test_schemas.py`, `tests/security/test_security_boundaries.py` | Unit/security |
| Coordinate validation, per-heartbeat OSM resolution, locality extraction, stable place upserts, later nested-place discovery, canonical labels | `tests/unit/test_osm.py`, `tests/integration/test_places.py`, place-scoped integration tests | Unit/integration |
| Presence expiry, saved visits, VISITOR-to-BELONG promotion | `tests/integration/test_places.py` | Integration |
| Structured local-AI adapter, model-output parsing, safety-category mapping, compatible external API format, timeouts, fail-closed behavior | `backend/tests/unit/test_ai.py`, `local_ai/tests/test_inference.py`, `backend/tests/integration/test_ai_worker.py` | Unit/integration |
| Prompt-injection and invalid AI-output rejection | security-marked tests in `tests/unit/test_ai.py` and feature integration files | Security |
| Nested-place routing and hierarchy validation | `tests/unit/test_ai.py`, `tests/integration/test_knock.py` | Unit/integration |
| Fair PostgreSQL AI job scheduling and worker failure handling | `tests/integration/test_jobs.py`, `tests/integration/test_ai_worker.py` | Integration |
| KNOCK live delivery, room isolation, moderation, persistence, reconnect history | `tests/integration/test_knock.py` | Integration/WebSocket |
| DIG media validation, upload limit, moderation, access control, expiry | `tests/integration/test_digs.py` | Integration/security |
| Explore memory creation, participant access, current-place access, likes/comments | `tests/integration/test_explore.py` | Integration/security |
| Forum posts, anonymous identity hiding, comments, votes, personal totals | `tests/integration/test_forum.py` | Integration/security |
| Private direct messages, search, unread counts, read state, live notification | `tests/integration/test_dms.py` | Integration/WebSocket/security |
| Complete user journey across auth, presence, KNOCK, forum, DMs, logout | `tests/system/test_user_journey.py` | System/API journey |
| Concurrent health checks, concurrent DM persistence, and retryable overload admission | `tests/stress/test_concurrency.py` | Course-sized stress |
| Complete four-service startup, public Nginx route, backend/database health, authenticated proxy flow | `scripts/fresh-start-test.ps1`, `.github/workflows/ci.yml` | Deployment/system |
| Frontend TypeScript production compilation | `npm run build`, `.github/workflows/ci.yml` | Build/static check |

## Test commands

Run every backend test:

```sh
docker compose run --build --rm backend pytest -q
```

Run the categorized suites individually:

```sh
docker compose run --build --rm --no-deps backend pytest -q -m unit
docker compose run --build --rm backend pytest -q -m integration
docker compose run --build --rm backend pytest -q -m system
docker compose run --build --rm backend pytest -q -m security
docker compose run --build --rm backend pytest -q -m stress
```

The system suite is an API-level cross-feature user journey.

Build the frontend:

```sh
docker compose build web
```
