# PlacePulse final report

## Project links

- Repository: <https://github.com/abatamny/place_pulse>
- Demonstration video: add the submitted video link here after recording
- Recording checklist: [demo-script.md](demo-script.md)

## Project summary

PlacePulse is a mobile-friendly location-based community application. A verified user shares browser coordinates, the backend resolves nearby physical places through OpenStreetMap, and the user can interact with content scoped to those places. The implementation follows the course architecture: React and Nginx, one FastAPI backend, one background worker, and PostgreSQL/PostGIS, all run through Docker Compose.

## Implemented features

- Phone-style registration and local development verification, Argon2 password hashing, revocable hashed sessions, login, and logout.
- OpenStreetMap place resolution, stored PostGIS boundaries, expiring presence, completed visits, and VISITOR/BELONG membership.
- KNOCK place-scoped live messages with WebSockets, persistence, nested-place routing, and role-aware AI moderation.
- DIG temporary image/video uploads with validation, moderation, presence access, and 24-hour expiry.
- Explore memories produced from DIG activity, persistent participant access, current-place access, likes, and comments.
- Persistent place forums with moderated posts/comments, public anonymity, voting, and a personal post/score view.
- Private one-to-one messages with user search, saved history, unread state, and WebSocket notifications.
- OpenAI and OpenAI-compatible structured AI adapters, including the configured `qwen3.7-plus` path, plus a fair durable PostgreSQL worker queue.
- Optional single-VM Azure deployment helper using the same Compose architecture.

## Architecture and important decisions

Only Nginx is published to the host. The backend, worker, and PostGIS database remain on the internal Compose network. PostgreSQL stores application data and AI jobs; a named volume stores approved media. This keeps the system understandable and deployable for a course project without adding a broker, cache, API gateway, or orchestration platform.

External OpenStreetMap and AI services are behind small adapters. Tests replace both with deterministic fakes, so CI does not require network access, API credentials, or paid requests. Pre-publication AI decisions fail closed. BELONG KNOCK messages publish immediately and are checked by the background worker afterward.

## Testing and results

The automated suite covers unit behavior, database/API integration, WebSockets, a cross-feature system journey, security boundaries, and modest concurrent load. The complete mapping is in [feature-test-matrix.md](feature-test-matrix.md).

Step 9 verification results:

- Complete backend suite: 62 passed.
- Step 9 system/security/stress selection: 15 passed.
- Frontend TypeScript/Vite production build: passed; dependency audit reported zero vulnerabilities.
- Isolated fresh Docker Compose startup: passed with database, backend, worker, and web services running; public UI, health endpoint, and authenticated Nginx proxy flow verified.
- GitHub Actions: backend tests, frontend build, fresh four-service startup, and gated post-CI Azure VM deployment configured.

The system test performs registration, verification, login, location heartbeat, a live KNOCK, persisted KNOCK history, an anonymous forum post, a direct message between two users, and logout. Stress tests use a bounded concurrent burst suitable for the course deployment rather than claiming production-scale capacity.

## Limitations and future work

The project is designed for one backend process and one VM. Browser geolocation can be spoofed, rate limiting is in memory, direct messages are not end-to-end encrypted, and local volumes are not automatically backed up. Live first-time place resolution depends on public OpenStreetMap availability, while AI-moderated publication depends on the configured provider. These constraints and proportionate production improvements are detailed in [risk-assessment.md](risk-assessment.md).

Azure provisioning remains a manual billable operation. After that one-time setup, the optional GitHub Actions job uses OIDC and Azure VM Run Command to deploy the exact successful `main` commit automatically. The demonstration video is a submission artifact and must be recorded and linked after the final UI walkthrough.
