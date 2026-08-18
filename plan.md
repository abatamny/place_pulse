# PlacePulse - Course Project Plan

## Goal and scope

Build a mobile-first web app where users interact with people and content connected to their current physical place. The project is graded mainly on its backend.

Keep it course-sized: simple, reliable, and runnable through Docker. Finish the core before optional work.

- **Core:** original proposal, long-term place memory, course requirements, and tests.
- **Extra points:** fair job queue, hallucination/jailbreak protection, local LLM, full forum/DM features, and Azure deployment.

## Codex instructions

Repository-wide working rules are in `AGENTS.md`. This file defines the project scope; implement only the user-requested step and stop at its **Complete when** condition.

## Architecture

- **Browser/mobile web app:** requests geolocation, displays the current place, and provides the KNOCK, DIG, Explore, and authentication screens.
- **Public web container:** serves the frontend and proxies `/api` and `/ws` traffic. It is the only container exposed to the client.
- **Backend API container:** owns authentication, users, OSM place resolution, presence, visits, KNOCK WebSockets, DIG uploads, and Explore endpoints.
- **Relational database container:** stores users, OSM-backed places and boundaries, presence/visits, messages, DIG metadata, Explore memories, reactions, and background-job state.
- **Worker container:** processes post-publication moderation and Explore/background jobs from a simple database jobs table.
- **Media volume:** stores uploaded images/videos; the database stores only their metadata and safe file paths.
- **External services:** only the backend contacts OpenStreetMap and the configured AI provider. A local LLM may replace the AI provider later for optional points.

The application database may start empty. Places are created when coordinates are resolved through OpenStreetMap, and users/content are created through the app. Demo/cold-seed data is postponed until the manual flows work.

## Technology stack

Use this stack unless the user explicitly approves a change:

| Area | Technology | Scope note |
|---|---|---|
| Frontend | React + TypeScript + Vite | Mobile-friendly web UI; no Next.js, PWA/offline work, or design system is required. |
| Public web container | Nginx | Serve the built React files and proxy `/api` and `/ws` to the backend. |
| Backend API | Python + FastAPI | One application for REST endpoints and WebSockets. |
| Database access | SQLAlchemy | Keep models and queries direct; initialize the schema automatically without building a migration system. |
| Database | PostgreSQL + PostGIS | One database container; PostGIS stores boundaries and supports geographic checks. |
| Worker | Same Python backend image | Start it with a different command; use the database jobs table instead of a separate queue service. |
| Media | Local Docker volume | Store files on disk and store metadata/safe paths in PostgreSQL. |
| Location services | OpenStreetMap Nominatim + Overpass | Called only by the backend to resolve locations and obtain OSM objects/boundaries; reuse locally stored results. |
| AI | One provider adapter | Use a configured external API for the core; a local LLM is optional later. |
| Local orchestration | Docker Compose | Start the full application with one documented command. |

Do not replace these technologies or add an alternative framework for the same role without a concrete need and user approval.

## Components

### 1. Mobile web frontend

- Register/login and request browser geolocation.
- Show the detected place and presence state.
- Screens for KNOCK messages, the 24-hour DIG feed, and Explore memories.
- Add forum, personal area, notifications, and DMs only if their backend features are implemented.
- Functional design is enough; visual complexity is not graded.

### 2. Backend API and authentication

- One backend application with REST endpoints and WebSockets.
- Users have a phone number, password hash, nickname, and a simple verification-code flow.
- Enforce authentication, authorization, input validation, safe errors, and rate limits.
- Never store plaintext passwords or expose internal services to clients.

### 3. Places and presence

- Resolve browser coordinates to one or more named OpenStreetMap objects.
- Store each discovered place locally with an internal `place_id`, OSM type/ID, name, boundary, and optional parent place.
- Reuse stored boundaries and perform local point/radius checks for later location updates instead of calling OSM on every heartbeat.
- Support nested places such as campus -> faculty -> building.
- Use heartbeats while the app is open and expire stale presence.
- Record visits and promote repeated users from `VISITOR` to `BELONG` using a simple threshold.

### 4. KNOCK live messages

- Send live messages through WebSockets to users in the relevant place only.
- Store accepted messages and provide history.
- Moderate visitor messages before publication; BELONG messages may be checked afterward.
- For nested places, use AI routing to choose the intended place layer.

### 5. DIG and Explore

- Present users can upload a small image or short video to their current place.
- Validate and moderate content before publication.
- Approved DIGs remain in the place feed for 24 hours.
- A background worker uses a simple activity threshold to preserve notable moments in Explore.
- Explore memories persist and support basic comments/reactions.

### 6. Moderation, AI, and jobs

- Use one AI adapter for moderation and nested-place routing.
- Use structured output, basic jailbreak protection, and stored/OpenStreetMap location facts.
- Fail safely when the model times out or returns invalid output.
- For core background work, a simple database jobs table and one worker are enough; no separate queue product is required.
- Fair per-user scheduling and a local LLM are optional extra-point work; the core may use a configured model/API.

### 7. Forum and direct messages (extra)

- Separate forum for each place with posts, optional anonymity, comments, likes/dislikes, and optional media.
- Personal area with the user's posts and reaction totals.
- Private DMs with saved history and live notifications.

### 8. Database and media

- Use one persistent relational database; create its schema automatically when Docker starts.
- Store implemented application data in the database.
- Store media in a persistent Docker volume, with metadata in the database.
- Generate safe filenames, enforce small upload limits, and preserve data across restarts.

### 9. Docker setup

- One Docker Compose setup starts the complete local app.
- Services may include web, backend, database, worker, and an optional local LLM.
- Only the public web service exposes a host port; internal services stay private.
- Include `.env.example` without secrets and one reliable startup command.

## Implementation order

Build the small frontend needed for each feature together with its backend. Do not build the entire frontend first.

### Step 1 - Runnable project foundation

- Create the frontend, backend, and database services in Docker Compose.
- Add automatic database schema creation; application tables may initially be empty.
- Add configuration through `.env`, persistent database/media volumes, and a backend health endpoint.
- Expose only the public application service; keep the database and later worker/queue services internal.
- Add one startup smoke test.

**Complete when:** a fresh clone starts with one documented command, the empty schema is created automatically, the health check succeeds, and newly created data survives a restart.

### Step 2 - Users and authentication

- Implement registration with phone number, nickname, password, and a simple verification-code flow suitable for localhost.
- Hash passwords and implement login, logout, and authentication for protected HTTP/WebSocket operations.
- Add the minimal registration and login screens.
- Add basic tests for successful registration/login, duplicate phone numbers, wrong passwords, and unauthorized access.

**Complete when:** a new user can register, log in, and access a protected endpoint, while unauthenticated users are rejected.

### Step 3 - Places, presence, visits, and rank

- Request browser coordinates while the app is open and send periodic updates to the backend.
- Resolve coordinates through OpenStreetMap when the backend does not already know the containing place.
- Create/update local place records from the returned OSM identifiers, names, boundaries, and containment relationships.
- Use stored boundaries and simple point/radius logic for repeated presence updates.
- Support nested places and show the detected place in the UI.
- Expire stale presence, record completed visits, and promote a user from `VISITOR` to `BELONG` after a simple visit threshold.
- Test coordinate mapping, nested places, stale presence, visit recording, and rank promotion.

**Complete when:** sharing a real browser location discovers and stores the correct OSM-backed place, repeated updates reuse it, and visits/rank persist in the database.

### Step 4 - AI jobs used by the core features

- Create one AI adapter for text moderation and nested-place message routing.
- For decisions required before publication, let the backend await an asynchronous AI call with a timeout.
- Add one worker and a simple database jobs table only for checks that happen after publication or in the background; do not add Redis or another queue service yet.
- Store job status, handle timeouts/invalid output, and fail safely.
- Use a deterministic fake AI implementation in automated tests; use the configured real provider for the demo.
- Add basic validation and prompt-injection checks around model input/output.

**Complete when:** the backend receives a structured pre-publication decision, the worker can store a background result, and model failure does not crash or publish unsafe content.

### Step 5 - KNOCK live messages

- Authenticate WebSocket connections and maintain rooms for the users currently present in each place.
- Send messages only to the place layer chosen by the routing result.
- Moderate `VISITOR` messages before publication; allow `BELONG` messages immediately and check them afterward.
- Store accepted messages and return recent place history.
- Test same-place delivery, cross-place isolation, invalid tokens, moderation rejection, reconnecting, and saved history.

**Complete when:** two logged-in users at the same place exchange a live KNOCK without refresh, while a user elsewhere receives nothing.

### Step 6 - DIG temporary media

- Let a present user upload a small image or short video to the current place.
- Validate authentication, presence, file type, filename, and upload size before storage.
- Save the file in the media volume and its metadata in the database.
- Publish only approved media and give each DIG an `expires_at` time 24 hours after creation.
- Show only active, approved DIGs in the current place feed.
- Test accepted/rejected uploads, wrong types, oversized files, wrong-place access, and expiry using controlled test time.

**Complete when:** approved media appears in the place feed and expired or rejected media does not.

### Step 7 - Explore and long-term place memory

- Run a simple background rule that detects a cluster of DIG activity and preserves selected content as an Explore memory.
- Keep Explore memories permanently even after their original DIGs expire.
- Add basic comments and likes to Explore memories.
- Enforce the proposal's access rule: a participant may access the memory later; other users must currently be at that place.
- Test memory creation, persistence, comments/likes, and access control.

**Complete when:** activity created manually through the app can trigger a permanent Explore memory that remains accessible according to the rule after the DIG feed expires.

### Step 8 - Optional points, only after the core is stable

- Improve the queue to prevent one spammer from starving other users.
- Strengthen hallucination and jailbreak defenses.
- Add the place forum, then DMs/live notifications if time remains.
- Add Azure deployment only after the local version and tests are reliable.

Each optional feature must receive its own essential tests before starting another optional feature.

### Step 9 - Final verification and submission

- Complete the required unit, integration, system/E2E, security, and stress suites.
- Run the project and tests from a fresh Docker environment and fix first-run issues.
- Add GitHub Actions to run the automated test suite.
- Finish the README, feature-to-test list, risk assessment, and final report.

During Steps 1-8, add only the essential unit/integration tests needed to protect completed work. Step 9 completes the cross-feature, edge-case, security, and load coverage; it is not the first time the features are tested.

## Final requirements

### Application

- Core flows work end to end and data persists across restarts.
- Invalid input, spam, oversized uploads, and failed dependencies do not crash the app.
- A grader can clone the repository and start it on the first attempt using the README.

### Tests

- Unit tests for business logic.
- Integration tests for components working together.
- System/E2E tests for main user journeys.
- Security tests for authentication, permissions, rate limits, uploads, malicious input, and basic jailbreaks.
- Stress tests for concurrent users, WebSockets, request bursts, and queue fairness.
- Each implemented feature has a normal-use test and its important edge/failure tests.
- Tests use isolated data, avoid paid/live services, and run with documented commands.

### Repository and submission

- `README.md` with setup, configuration, usage, test, shutdown, and reset instructions.
- `.env.example`, deterministic test fixtures, informative commits from all members, and GitHub Actions tests.
- GitHub repository link and a video demonstrating the app.
- Report explaining features, tests for each feature, and the required risk assessment.
- Azure deployment and automatic deployment after passing CI are optional extra-point work.
