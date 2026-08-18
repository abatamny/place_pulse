# PlacePulse feature-to-test matrix

This list connects each implemented feature to its main automated evidence. External services are replaced with deterministic fakes; the test suite never calls OpenStreetMap or a paid AI provider.

| Feature or safeguard | Main automated coverage | Test level |
|---|---|---|
| Registration, verification, password hashing, login, logout, session revocation | `tests/test_auth.py` | Integration/security |
| Authentication boundary across protected HTTP and WebSocket routes | `tests/test_auth.py`, `tests/test_security.py`, `tests/test_knock.py`, `tests/test_dms.py` | Security |
| Expired sessions and hashed stored tokens | `tests/test_security.py` | Security |
| Authentication and feature rate limits | `tests/test_security.py`, `tests/test_digs.py`, `tests/test_dms.py` | Unit/security |
| Coordinate validation, OSM place resolution, local boundary reuse | `tests/test_places.py` | Integration |
| Presence expiry, saved visits, VISITOR-to-BELONG promotion | `tests/test_places.py` | Integration |
| Structured AI moderation, compatible API format, timeouts, fail-closed behavior | `tests/test_ai.py` | Unit/integration |
| Prompt-injection and invalid AI-output rejection | `tests/test_ai.py`, `tests/test_forum.py` | Security |
| Nested-place routing and hierarchy validation | `tests/test_ai.py`, `tests/test_knock.py` | Unit/integration |
| Fair PostgreSQL AI job scheduling and worker failure handling | `tests/test_jobs.py`, `tests/test_ai.py` | Unit/integration |
| KNOCK live delivery, room isolation, moderation, persistence, reconnect history | `tests/test_knock.py` | Integration/WebSocket |
| DIG media validation, upload limit, moderation, access control, expiry | `tests/test_digs.py` | Integration/security |
| Explore memory creation, participant access, current-place access, likes/comments | `tests/test_explore.py` | Integration |
| Forum posts, anonymous identity hiding, comments, votes, personal totals | `tests/test_forum.py` | Integration/security |
| Private direct messages, search, unread counts, read state, live notification | `tests/test_dms.py` | Integration/WebSocket |
| Complete user journey across auth, presence, KNOCK, forum, DMs, logout | `tests/test_system.py` | System/E2E |
| Concurrent health checks and concurrent DM persistence | `tests/test_stress.py` | Course-sized stress |
| Complete four-service startup, public Nginx route, backend/database health, authenticated proxy flow | `scripts/fresh-start-test.ps1`, `.github/workflows/ci.yml` | Deployment/system |
| Frontend TypeScript production compilation | `npm run build`, `.github/workflows/ci.yml` | Build/static check |

## Test commands

Run every backend test:

```sh
docker compose run --build --rm backend pytest -q
```

Run the final categorized suites individually:

```sh
docker compose run --build --rm backend pytest -q -m system
docker compose run --build --rm backend pytest -q -m security
docker compose run --build --rm backend pytest -q -m stress
```

Run the core unit-focused files:

```sh
docker compose run --build --rm backend pytest -q tests/test_ai.py tests/test_jobs.py
```

Run the feature integration files:

```sh
docker compose run --build --rm backend pytest -q \
  tests/test_auth.py tests/test_places.py tests/test_knock.py \
  tests/test_digs.py tests/test_explore.py tests/test_forum.py tests/test_dms.py
```

Build the frontend:

```sh
docker compose build web
```
