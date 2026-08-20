# PlacePulse final report

## Project links

- Repository: <https://github.com/abatamny/place_pulse>
- Demonstration video: add the submitted video link here after recording

## Project summary

PlacePulse is a mobile-friendly, location-based community application. A verified user shares browser coordinates, the backend resolves nearby physical places through a local OpenStreetMap Overpass instance, and the user interacts with content scoped to those places: live KNOCK messages, temporary DIG media, permanent Explore memories, place forums, and direct messages, all backed by AI moderation. The implementation follows the course architecture: React + Nginx, one FastAPI backend, one background worker, internal local-AI and Overpass services, and PostgreSQL/PostGIS, all run through Docker Compose. Only Nginx is exposed to clients; every other service stays on the internal Compose network.

## Features, and how each was tested

Each row states what the feature does and the automated tests that cover it. External services (OpenStreetMap, Twilio, paid AI) are always replaced with deterministic fakes, so the suite never depends on live network calls.

| Feature | What it does | Tests |
|---|---|---|
| Registration & auth | Phone-style registration with demo-code fallback or Twilio SMS, Argon2 password hashing, revocable hashed sessions, login/logout, expired-session handling | `tests/integration/test_auth.py`, `tests/unit/test_sms.py`, `tests/security/test_security_boundaries.py` |
| Rate limiting & input validation | Per-user/action sliding-window limits (including reconnect-resistant KNOCK limiting), strict request schemas, backend-wide body-size cap | `tests/unit/test_request_protection.py`, `tests/unit/test_schemas.py`, `tests/security/test_security_boundaries.py` |
| Place resolution & presence | OSM/Overpass place and locality resolution, stable place upserts, presence expiry, visit history, VISITOR→BELONG promotion | `tests/unit/test_osm.py`, `tests/integration/test_places.py`, `scripts/smoke-test-overpass.ps1` |
| Local AI adapter | Structured local-model calls, output parsing/validation, timeouts, fail-closed behavior, optional external-API fallback | `backend/tests/unit/test_ai.py`, `local_ai/tests/test_inference.py`, `backend/tests/integration/test_ai_worker.py` |
| Jailbreak robustness | Normalized prompt-injection screening (direct and obfuscated), instruction/data separation, output re-screening, fail-closed decisions | security-marked cases in `tests/unit/test_ai.py` and feature integration tests |
| Hallucination robustness | Strict output schemas and allow-listed categories, rejection of invented/contradictory place IDs, hierarchy checks, confidence-gated routing | `tests/unit/test_ai.py`, `tests/integration/test_ai_worker.py`, `tests/integration/test_knock.py` |
| Fair job queue | Durable PostgreSQL job table; the worker always serves the user waiting longest since their last turn, so one user flooding jobs can't starve another | `tests/integration/test_jobs.py`, `tests/integration/test_ai_worker.py` |
| KNOCK live messages | AI-routed, place-scoped WebSocket messages, room isolation, moderation, persistence, reconnect history | `tests/integration/test_knock.py` |
| DIG temporary media | Upload validation, moderation, 24-hour expiry, presence-gated access | `tests/integration/test_digs.py` |
| Explore memories | Long-term place memory generated from DIG activity, participant/current-place access, likes and comments | `tests/integration/test_explore.py` |
| Place forums | Posts/comments with media, anonymous posting, voting, per-post/comment voter visibility for the author, personal post/score view | `tests/integration/test_forum.py` |
| Direct messages | One-to-one messages with media, search, unread state, live WebSocket notification | `tests/integration/test_dms.py` |
| Full user journey | Registration → verification → login → presence → KNOCK → forum → DM → logout | `tests/system/test_user_journey.py` |
| Overload behavior | Concurrent requests, retryable admission limits, concurrent DM persistence | `tests/stress/test_concurrency.py` |
| Deployment health | Full four-service Compose startup, public route, health checks | `scripts/fresh-start-test.ps1`, `.github/workflows/ci.yml` |
| Frontend build | TypeScript type-checking and production build | `npm run build` in CI |

Run the full backend suite with `docker compose run --build --rm backend pytest -q`, or one category at a time with `pytest -q -m unit|integration|system|security|stress` (see [README.md](../README.md)).

## Risk assessment

### Availability & redundancy

Docker health checks cover PostgreSQL, the backend, local AI, and Overpass; the deployment workflow checks `/api/health` after every rebuild and fails the job if the app doesn't come back healthy. Named volumes persist the database, media, model weights, and the Overpass index across restarts. What's not covered: the VM and database are single points of failure, and there is no automatic backup, replica, or failover host — a host failure makes the whole app unavailable until it's manually recovered.

### Scalability

Nginx and the backend bound request bursts, concurrent HTTP requests, WebSocket connections, and backlog growth, so overload is rejected predictably (`429`/`503`/WebSocket `1013`) instead of exhausting the host. AI work is queued durably in PostgreSQL with fair (longest-waiting-first) job selection, so one user's flood of requests can't starve another user. This scales vertically to the limits of one VM but not horizontally: WebSocket rooms and rate-limit state are process-local, media lives on a local volume, and each of the database/worker/AI/Overpass services runs as a single instance. That's an intentional course-scope tradeoff, not an oversight.

### Spamming requests

Every write endpoint is behind a per-user, per-action sliding-window rate limiter (registration, login, KNOCK, forum posts/comments/votes, DMs, DIG uploads), on top of Nginx's per-IP request/connection limits. Media uploads are capped at 10 MB (15 seconds for video) with allow-listed MIME types and decoded-content validation; the backend also enforces a hard body-size cap independent of any single endpoint. A user hitting these limits gets a `429` with `Retry-After` rather than degrading the service for everyone else.

### Security

Passwords are Argon2-hashed; session tokens are random and stored only as hashes. Only Nginx (and SSH for the Azure VM) is exposed publicly — the backend, worker, database, local AI, and Overpass all stay on the internal Compose network and are unreachable from outside. Every place-scoped feature rechecks current presence server-side before granting access. AI output is never trusted to create facts or bypass authorization: routing can only select backend-supplied place IDs, and invented, contradictory, or low-confidence results are rejected. Known, accepted limitations: browser geolocation can be spoofed, direct messages aren't end-to-end encrypted, and anonymous-post authorship is still visible to whoever can read the database directly.

## Limitations and future work

The project intentionally runs as one backend process on one VM: no replication, no distributed rate limiting, no managed database failover. Azure VM creation is a manual, billable, one-time step; after that, GitHub Actions redeploys the exact tested `main` commit automatically over SSH (see [README.md](../README.md#deploy-to-azure) for the required secrets). The demonstration video is a submission artifact and needs to be recorded and linked above before final submission.
