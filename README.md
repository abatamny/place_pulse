# PlacePulse

[![CI](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml)

Repository: <https://github.com/abatamny/place_pulse>

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place. The project currently includes authentication, place/presence tracking, AI-backed moderation, live place-scoped KNOCK messages, temporary DIG media, permanent Explore memories, place forums, and private direct messages.

## Requirements

- Docker Desktop, or Docker Engine with Docker Compose v2
- Several GB of free disk and memory for the three local models

No local Node.js, Python, PostgreSQL, or PostGIS installation is required.

## Start the application

From the repository root, run:

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. The backend health endpoint is available through the public web service at <http://localhost:8080/api/health>.

This one command builds the React frontend, FastAPI backend, and local AI service; starts PostGIS; creates the application schema automatically; starts the background worker; and starts Nginx. The first start downloads the configured Hugging Face model weights into the persistent `ai_models` volume, so local moderation may take several minutes to become ready. Only Nginx is exposed on the host; the backend, worker, database, and local AI service remain on the internal Compose network.

## Configuration

The defaults work without creating an `.env` file. To change them, copy `.env.example` to `.env` and edit:

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8080` | Public application port |
| `APP_ENV` | `development` | Runtime environment label |
| `VERIFICATION_SECRET` | local development value | Hashes temporary verification codes; change it outside localhost |
| `SMS_PROVIDER` | empty | Leave empty to show a demo code, or set to `twilio` to send SMS |
| `TWILIO_ACCOUNT_SID` | empty | Twilio account identifier, required when `SMS_PROVIDER=twilio` |
| `TWILIO_AUTH_TOKEN` | empty | Twilio API credential, required when `SMS_PROVIDER=twilio` |
| `TWILIO_FROM_NUMBER` | empty | Message-capable Twilio sender number in international format |
| `SMS_TIMEOUT_SECONDS` | `8` | Maximum wait for SMS delivery acceptance |
| `OSM_USER_AGENT` | `PlacePulse-Course-Project/0.1` | Identifies backend requests to OpenStreetMap services |
| `OVERPASS_URL` | public Overpass URL | Containing-place and boundary endpoint |
| `AI_PROVIDER` | `local` | Use the internal local service; `openai` and `openai-compatible` remain available as fallbacks |
| `AI_LOCAL_URL` | `http://local-ai:8081` | Docker-internal inference service URL |
| `TEXT_SAFETY_MODEL_ID` | `Qwen/Qwen3Guard-Gen-0.6B` | Local text-safety model |
| `ROUTER_MODEL_ID` | `Qwen/Qwen3-0.6B` | Local semantic text-routing model |
| `IMAGE_SAFETY_MODEL_ID` | `OwenElliott/image-safety-classifier-s` | Local NSFW/NSFL image classifier |
| `LOCAL_AI_DEVICE` | `auto` | Select CPU automatically in the default image |
| `LOCAL_AI_MAX_CONCURRENT_INFERENCES` | `1` | Bounds concurrent model executions and memory spikes |
| `IMAGE_UNSAFE_THRESHOLD` | `0.5` | Reject an NSFW or NSFL class at or above this probability |
| `AI_API_URL` | OpenAI Responses API | Structured-output endpoint |
| `AI_API_FORMAT` | `responses` | `responses` for native OpenAI or `chat_completions` for compatible JSON-mode providers |
| `AI_API_KEY` | empty | Provider API key; required only when an AI operation is used |
| `AI_MODEL` | `gpt-4.1-mini` | Model used for moderation |
| `AI_MODERATION_URL` | OpenAI Moderations API | Image-moderation endpoint |
| `AI_MODERATION_MODEL` | `omni-moderation-latest` | Model used for DIG image and video-frame moderation |
| `AI_MEDIA_MODERATION_MODE` | `moderations` | Use the moderation endpoint, or `model` to moderate media with a multimodal chat model |
| `AI_TIMEOUT_SECONDS` | `30` | Maximum wait for a local or external model decision |
| `MAX_REQUEST_BODY_BYTES` | `11534336` (11 MiB) | Backend-wide request cap, including multipart overhead for a 10 MiB DIG |
| `MAX_CONCURRENT_HTTP_REQUESTS` | `50` | Per-backend in-flight HTTP admission limit |
| `MAX_WEBSOCKET_CONNECTIONS` | `100` | Per-backend WebSocket admission limit |
| `POSTGRES_DB` | `placepulse` | PostgreSQL database name |
| `POSTGRES_USER` | `placepulse` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `placepulse` | Local PostgreSQL password |

Do not commit `.env`; it is ignored by Git.

## Abuse and overload protection

All request models reject unexpected fields, bound text and numeric inputs, trim required text, and reject invalid control characters. Nginx and the backend independently cap request bodies at 11 MiB; DIG validation then enforces the stricter 10 MiB file limit, allow-listed formats, decoded dimensions, and video duration.

Authentication and write-heavy features use sliding-window rate limits, including KNOCK limits that remain in effect when a client reconnects. Nginx also bounds per-IP request bursts and connections. The backend admits at most 50 concurrent HTTP requests and 100 WebSockets by default, returning a retryable `503` or WebSocket `1013` instead of accepting unbounded work. Uvicorn adds a final connection/backlog and 64 KiB WebSocket-frame cap. These are intentionally single-instance, course-deployment safeguards rather than distributed production controls.

When no SMS provider is configured, registration returns the six-digit code and
the frontend labels it as a demo code. To send real verification messages with
Twilio, configure all of the following values:

```dotenv
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-private-auth-token
TWILIO_FROM_NUMBER=+15005550006
SMS_TIMEOUT_SECONDS=8
```

Users must register with an international phone number such as `+972...` when
real SMS delivery is enabled. If Twilio is configured but incomplete or rejects
a message, registration fails safely instead of exposing the verification code.

For an OpenAI-compatible Alibaba Model Studio workspace using `qwen3.7-plus`, use the workspace URL from its credential export and this shape in your private `.env`:

```dotenv
AI_PROVIDER=openai-compatible
AI_API_URL=https://YOUR_WORKSPACE.REGION.maas.aliyuncs.com/compatible-mode/v1/chat/completions
AI_API_FORMAT=chat_completions
AI_API_KEY=your-private-key
AI_MODEL=qwen3.7-plus
AI_MODERATION_MODEL=qwen3.7-plus
AI_MEDIA_MODERATION_MODE=model
AI_TIMEOUT_SECONDS=20
```

In compatible mode, text decisions and DIG image/video-frame checks use validated JSON returned by the configured model. This is an optional fallback; the default path is the internal local service.

On PowerShell, a two-column Alibaba credential export can be imported without printing the key:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure-ai-provider.ps1 -CredentialFile "C:\path\to\api-key.csv" -Model "qwen3.7-plus"
```

## Local authentication flow

1. Open <http://localhost:8080> and choose **Register**.
2. Enter a nickname, phone number, and password of at least eight characters.
3. With no `SMS_PROVIDER`, the six-digit verification code is shown directly on the verification screen. When Twilio is configured, it is sent by SMS and omitted from the API response.
4. Verify the phone number, then log in with the same phone number and password.

Passwords are Argon2-hashed. Login creates a random, revocable session whose token hash is stored in PostgreSQL; logging out deletes that session.

## Location and presence flow

1. Log in and select **Share my location**.
2. Allow the browser's location prompt. Localhost is treated as a secure browser context for geolocation.
3. The backend resolves the coordinates through OpenStreetMap Overpass, classifies every useful named non-administrative enclosure, and displays the nested scopes as clickable map orbits. Administrative features supply locality context instead of becoming interaction rooms.
4. While location sharing remains enabled, the page sends a heartbeat every 30 seconds. Each heartbeat is resolved through Overpass so a previously stored broad place cannot hide a newly returned inner place. Existing OSM objects are upserted to keep their internal place IDs stable. If Overpass is unavailable, the heartbeat fails without replacing the user's last successful place hierarchy with a less-specific reverse-geocoding result.

For demos and testing, the map's **Custom location** box accepts an `https://openstreetmap.org` share URL containing either `#map=zoom/latitude/longitude` or `?mlat=...&mlon=...`. The saved override uses the same heartbeat and backend OSM resolution flow. Select **Use browser** to clear it and return to browser geolocation, which remains the default when no override is saved.

Presence expires after 90 seconds without a heartbeat. A completed presence becomes a saved visit, and three completed visits at a place promote the user from `VISITOR` to `BELONG`.

The innermost orbit is selected automatically. Clicking another orbit changes one shared active scope for KNOCK, DIG, Explore, and Forum; it does not change the user's physical presence. Scope identity comes from the stable OSM object, while `VENUE`, `BUILDING`, `OUTDOOR`, `SITE`, `DISTRICT`, and `OTHER` classes provide deterministic colors and labels. The same backend-generated place label is used across every place-scoped feature. Direct messages are not place-scoped.

## KNOCK live messages

After sharing a location, the main screen connects to the authenticated KNOCK WebSocket and loads recent messages for the selected orbit. Every message includes that exact scope, which the backend validates against current presence before storing and broadcasting it. A building KNOCK therefore stays in the building room, while a campus KNOCK reaches users currently sharing the campus scope.

`VISITOR` messages are moderated before publication and fail closed if local inference is unavailable. `BELONG` messages appear immediately and create a PostgreSQL background job for the worker to check afterward.

## DIG temporary media

After sharing a location, the map shows DIGs from the selected orbit and the composer posts to that same exact scope. A DIG may be a JPEG, PNG, WebP, MP4, or WebM file up to 10 MB; videos are limited to 15 seconds. Every upload is validated and moderated before it is written to the persistent media volume or listed in the feed.

Approved DIGs remain available to users currently at that place for 24 hours. Rejected and expired media is not shown. Videos are checked using three representative frames because the local safety classifier accepts images rather than video files directly. Automated tests use a fake provider and never download or invoke model weights.

## Explore place memories

The background worker checks approved DIG activity without making another AI call. Three unpreserved DIGs posted to the same place within one hour create an Explore memory containing up to five DIGs. The memory and its selected media remain available after the original 24-hour DIG feed entries expire.

Every author whose DIG was selected is a participant and can revisit that memory after leaving. Other users can view, like, and comment on it only while their location heartbeat shows that they are currently at the same place. **Explore** defaults to the selected orbit; **My memories** preserves participant access after leaving.

## Place forum and personal area

Open **Forum** after sharing your location to see persistent posts from the selected orbit. New posts use that exact active scope while recording the deepest current place as their physical origin. Posts may be anonymous, and present users can add comments or change an upvote/downvote. Post and comment text is moderated before publication and fails closed if the configured AI provider is unavailable. Forum media is intentionally omitted to keep this optional course feature small.

The **My posts** view remains available after leaving a place. It lists the signed-in user's posts and totals their received likes, dislikes, and net score. Anonymous posts never reveal their author in public API responses.

## Direct messages

The **Messages** tab supports private one-to-one conversations without requiring location presence. Search for another verified user by nickname or phone number, send a saved message, and reopen the complete recent history later. Only the sender and recipient can obtain that conversation through the API.

An authenticated WebSocket remains connected while the signed-in app is open. New messages update the unread badge immediately, while unread counts and read timestamps are also persisted in PostgreSQL.

## AI moderation and worker

The backend uses one AI adapter backed by the internal `local-ai` service. `Qwen3Guard-Gen-0.6B` moderates text, `Qwen3-0.6B` performs constrained semantic text routing, and `image-safety-classifier-s` classifies uploaded images and sampled video frames as SFW, NSFW, or NSFL. Pre-publication calls have a timeout and fail closed: invalid input, prompt-injection patterns, invalid model output, and inference failures never produce an approval. Audience selection is constrained to validated active orbits; AI can never invent a scope ID.

Post-publication moderation is placed in the PostgreSQL `ai_jobs` table. The internal `worker` service rotates among users' oldest jobs so one busy user cannot starve everyone else, records a completed structured result or a safe failed status, and continues running after model errors.

The local service exposes only `/health`, `/v1/moderate/text`, `/v1/moderate/images`, and `/v1/route/text` on the Compose network. It loads each model once, serializes inference by default, validates generated decisions, and keeps its model cache in a named volume. The selected image model is not a vision-language router, so media scope routing safely falls back to the application-selected deepest scope.

Model inputs are normalized before broader jailbreak-pattern checks and moderation categories are restricted. Selected scope IDs are validated against fresh presence before publication. Automated tests inject deterministic fakes or mocked HTTP transport, so test runs never call external services or load the real models.

## Automated tests

With the database service running, execute:

```sh
docker compose run --build --rm backend pytest -q
```

The tests automatically create and use a separate PostGIS-enabled `placepulse_test` database. OpenStreetMap is replaced with a deterministic fake resolver, so tests do not depend on live network services or modify users created through the application.

The organized suites can also be run separately. Unit tests use no database;
the remaining backend categories use the isolated test database where needed:

```sh
docker compose run --build --rm --no-deps backend pytest -q -m unit
docker compose run --build --rm backend pytest -q -m integration
docker compose run --build --rm backend pytest -q -m system
docker compose run --build --rm backend pytest -q -m security
docker compose run --build --rm backend pytest -q -m stress
```

Tests live under matching `tests/unit`, `tests/integration`, `tests/security`,
`tests/system`, and `tests/stress` directories. Security is also a cross-cutting
marker on relevant unit and integration tests. The `system` suite is an
API-level cross-feature user journey.

See the [feature-to-test matrix](docs/feature-test-matrix.md) for the complete mapping of features to unit, integration, system, security, and stress coverage.

## Fresh-install verification

The following PowerShell command creates an isolated Compose project on port `18080`, verifies all four services, the public UI, database health, and registration/login through Nginx, then removes only its temporary containers and volumes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fresh-start-test.ps1
```

It does not reset the normal `place_pulse` Compose project or its saved data. GitHub Actions repeats the backend tests, frontend production build, and fresh four-service startup on every push and pull request. An enabled Azure deployment runs afterward only for `main`.

## Startup smoke test

On PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

The smoke test builds and starts the stack, waits for the public health endpoint, confirms that the schema exists, writes one harmless foundation record, restarts PostgreSQL, and confirms the record is still present. It leaves the application running for inspection.

## Optional Azure VM deployment

The course-sized Azure path runs the same Docker Compose stack on one Ubuntu VM, so PostgreSQL/PostGIS, media, the backend, worker, and Nginx keep the same architecture. Only SSH and Nginx on port 80 are opened publicly. Initial provisioning creates billable Azure resources and must be run manually.

Prerequisites:

- Azure CLI, signed in with `az login` and set to the intended subscription
- An SSH public key
- The repository available from the public GitHub URL, with the target branch pushed
- A private environment file outside the repository containing strong `VERIFICATION_SECRET` and `POSTGRES_PASSWORD` values plus the AI provider configuration and optional Twilio settings

Deploy from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/deploy-azure.ps1 `
  -ResourceGroup placepulse-course-rg `
  -VmName placepulse-course `
  -Location westeurope `
  -SshPublicKeyPath "C:\path\to\id_ed25519.pub" `
  -EnvironmentFile "C:\private\placepulse-azure.env"
```

The environment file is base64-encoded into VM custom data during provisioning and installed as `/opt/placepulse/.env` with root-only permissions. For a course demo, use a dedicated low-value AI key rather than reusing an important production credential. The helper validates repository/branch inputs, starts Compose through cloud-init, prints the public IP, and deletes its temporary rendered cloud-init file.

After the VM is provisioned, GitHub Actions can automatically deploy the exact tested `main` commit through Azure VM Run Command. The job uses short-lived OIDC authentication and stays disabled until its GitHub variables and environment secrets are configured. Follow [the automatic Azure deployment setup](docs/azure-auto-deploy.md).

When the demo is finished, remove the Azure resource group from the portal or with `az group delete --name placepulse-course-rg`. This permanently deletes the VM and its stored database/media volumes.

## Final project documents

- [Final report](docs/final-report.md)
- [Feature-to-test matrix](docs/feature-test-matrix.md)
- [Risk assessment](docs/risk-assessment.md)
- [Demonstration video script](docs/demo-script.md)
- [Automatic Azure deployment setup](docs/azure-auto-deploy.md)

## Useful commands

View logs:

```sh
docker compose logs -f
```

Stop the application while preserving data:

```sh
docker compose down
```

Start it again with `docker compose up -d`; the named database and media volumes are reused.

Reset all local application data:

```sh
docker compose down -v
```

The reset command permanently removes the local database and media volumes.
