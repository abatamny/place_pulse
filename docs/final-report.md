# PlacePulse final report

## Project links

- Repository: <https://github.com/abatamny/place_pulse>
- Demonstration video: add the submitted video link here after recording
- Recording checklist: [demo-script.md](demo-script.md)

## Project summary

PlacePulse is a mobile-friendly location-based community application. A verified user shares browser coordinates, the backend resolves nearby physical places through a local OpenStreetMap Overpass instance, and the user can interact with content scoped to those places. The implementation follows the course architecture: React and Nginx, one FastAPI backend, one background worker, internal local-AI and Overpass services, and PostgreSQL/PostGIS, all run through Docker Compose.

## Implemented features

- Phone-style registration with optional Twilio SMS delivery and an automatic demo-code fallback when no provider is configured, Argon2 password hashing, revocable hashed sessions, login, and logout.
- OpenStreetMap place/locality resolution, consistent `Primary · Parent, City` labels, stored PostGIS boundaries, expiring presence, completed visits, and VISITOR/BELONG membership.
- KNOCK place-scoped live messages with WebSockets, persistence, nested-place routing, and role-aware AI moderation.
- DIG temporary image/video uploads with validation, moderation, presence access, and 24-hour expiry.
- Explore memories produced from DIG activity, persistent participant access, current-place access, likes, and comments.
- Persistent place forums with moderated posts/comments, public anonymity, voting, and a personal post/score view.
- Private one-to-one messages with user search, saved history, unread state, and WebSocket notifications.
- Local text moderation with `Qwen3Guard-Gen-0.6B`, constrained routing with `Qwen3-0.6B`, image moderation with `image-safety-classifier-s`, and a fair durable PostgreSQL worker queue. External adapters remain optional fallbacks.
- Course-sized jailbreak robustness through normalized prompt-injection screening, instruction/data separation, output screening, and fail-closed decisions; hallucination robustness through strict schemas, allow lists, server-supplied place facts, hierarchy checks, and rejection of invented or contradictory routes.
- Optional single-VM Azure deployment using the same Compose architecture and automatic post-CI updates over SSH.

## Architecture and important decisions

Only Nginx is published to the host. The backend, worker, local-AI service, local Overpass service, and PostGIS database remain on the internal Compose network. PostgreSQL stores application data and AI jobs; named volumes store approved media, downloaded model weights, and the regional Overpass index. This keeps the system understandable and deployable for a course project without adding a broker, cache, API gateway, or orchestration platform.

OpenStreetMap and local inference are behind small adapters. Tests replace both with deterministic fakes or mocked transport, so CI does not require model downloads, API credentials, or paid requests. Pre-publication AI decisions fail closed. Every KNOCK is routed to one allow-listed current scope before publication. VISITOR messages are then moderated before publication; BELONG messages publish after routing and are checked by the background worker afterward.

AI output is never trusted to create application facts or bypass authorization. Security tests exercise direct and obfuscated jailbreak attempts, instruction-like output, unknown moderation categories, invented place IDs, routes that contradict named stored places, low-confidence media routes, malformed results, and timeouts. This is tested error containment rather than a claim that every model-level jailbreak or hallucination is detectable; ongoing adversarial evaluation would be required beyond the course deployment.

## Availability, scalability, security, and failure handling

### Availability

The course deployment favors recoverability on one machine rather than high availability. Docker health checks cover PostgreSQL, the backend, local AI, and Overpass; smoke and deployment checks exercise the public Nginx-to-backend path. Services use restart policies, and PostgreSQL, media, model files, and the Overpass index use persistent volumes. The deployment workflow checks `/api/health` after rebuilding the stack and reports the deployment as failed if the application does not become healthy. These controls recover from ordinary container-process failures and preserve state across restarts, but the VM and database remain single points of failure. There is no automatic backup, replica, failover host, or zero-downtime deployment, so a host failure or VM update can make the whole application unavailable. A production design would add tested backups, managed database availability, redundant application instances, and monitored failover.

### Scalability

PlacePulse is deliberately sized for a course demonstration: one backend process, one worker, one PostGIS database, one local-AI service, and one regional Overpass service. Nginx and the backend bound request sizes, request bursts, concurrent HTTP requests, WebSocket connections, and backlog growth so overload is rejected predictably instead of exhausting the host. AI work that can run after publication is stored durably in PostgreSQL, and fair job selection prevents one user from starving the others. This design can scale vertically to the limits of one VM, but it is not horizontally scalable: WebSocket rooms and rate limits are process-local, uploaded media is on a local volume, and the database, worker, AI, and Overpass services each have a single active instance. Production horizontal scaling would require shared pub/sub and rate-limit state, shared object storage, safe multi-worker job claiming, and independently scalable managed data and inference services. Those additions are intentionally outside the project scope.

### Security

Only Nginx and SSH are exposed publicly on the Azure VM; the backend, worker, database, local AI, and Overpass stay on the internal Compose network. Passwords are Argon2-hashed, session tokens are random and stored only as hashes, protected HTTP and WebSocket operations enforce authentication and authorization, and place-scoped features recheck current presence. Strict request schemas, rate limits, body and WebSocket limits, safe filenames, media validation, upload limits, moderation, and prompt-injection/output checks constrain malicious input. Application secrets remain in ignored `.env` files, while CI deployment uses a dedicated SSH key and pinned host key. Remaining risks include spoofable browser coordinates, unencrypted direct-message content at rest, administrator access to anonymous-post ownership, and the deployment user's effectively root-level Docker access. The [risk assessment](risk-assessment.md) records these limits and proportionate production improvements.

### Failure handling

Expected dependency and input failures produce bounded, explicit outcomes. Invalid requests return `4xx` responses; overload returns `429`, retryable `503`, or WebSocket `1013`. Pre-publication AI failures, timeouts, malformed output, and suspicious prompts fail closed instead of publishing content. If Overpass is importing or unavailable, a location heartbeat returns a temporary-unavailable error without replacing the user's last verified place hierarchy. Failed background AI jobs are stored with a failed status and do not stop the worker loop. Database failure makes `/api/health` return `503`, Compose health dependencies prevent unhealthy services from being treated as ready, and a deployment whose rebuilt application stays unhealthy prints container state and recent logs. Persistent volumes survive normal restarts, but they do not replace backups; permanent VM or volume loss is still unrecoverable without an external export. Automated unit, integration, system, security, stress, and fresh-start checks exercise the important failure paths with deterministic external-service fakes.

## Testing and results

The automated suite covers unit behavior, database/API integration, WebSockets, a cross-feature system journey, security boundaries, and modest concurrent load. The complete mapping is in [feature-test-matrix.md](feature-test-matrix.md).

Step 9 verification results:

- Complete backend suite: 69 passed.
- Step 9 system/security/stress selection: 15 passed.
- Frontend TypeScript/Vite production build: passed; dependency audit reported zero vulnerabilities.
- Isolated fresh Docker Compose startup: passed with database, backend, worker, and web services running; public UI, health endpoint, and authenticated Nginx proxy flow verified.
- GitHub Actions: backend tests, frontend build, fresh four-service startup, and gated post-CI Azure VM deployment configured.

The system test performs registration, verification, login, location heartbeat, a live KNOCK, persisted KNOCK history, an anonymous forum post, a direct message between two users, and logout. Stress tests use a bounded concurrent burst suitable for the course deployment rather than claiming production-scale capacity.

## Limitations and future work

The project is designed for one backend process and one VM. Browser geolocation can be spoofed, rate limiting is in memory, direct messages are not end-to-end encrypted, and local volumes are not automatically backed up. Live place heartbeats depend on one locally imported, static Overpass snapshot, while AI-moderated publication depends on sufficient local inference resources and the image classifier covers only SFW/NSFW/NSFL categories. These constraints and proportionate production improvements are detailed in [risk-assessment.md](risk-assessment.md).

Azure VM creation and initial setup remain manual billable operations. After that one-time setup, the optional GitHub Actions job uses a deployment-only SSH key and pinned host key to deploy the exact successful `main` commit automatically. The demonstration video is a submission artifact and must be recorded and linked after the final UI walkthrough.
