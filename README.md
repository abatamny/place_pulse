# PlacePulse

[![CI](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml)

Repository: <https://github.com/abatamny/place_pulse>

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place. The project currently includes authentication, place/presence tracking, AI-backed moderation, live place-scoped KNOCK messages, temporary DIG media, permanent Explore memories, place forums, and private direct messages.

## Requirements

- Docker Desktop, or Docker Engine with Docker Compose v2
- Several GB of free disk and memory for the three local models and regional Overpass index
- SSD storage is strongly recommended for the first Overpass import

No local Node.js, Python, PostgreSQL, or PostGIS installation is required.

### VM specifications

For a single VM running the complete Compose stack (PostGIS, backend, worker,
Nginx, the three local AI models, and regional Overpass), use:

- **Minimum supported course/demo VM:** 2 vCPUs, 8 GiB RAM, and 40 GiB SSD storage.
- **Operating system:** Ubuntu 24.04 LTS x64, or a comparable current Linux
  distribution with Docker Engine and Docker Compose v2.

## Start the application

From the repository root, run:

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. The backend health endpoint is available through the public web service at <http://localhost:8080/api/health>.

This one command builds the React frontend, FastAPI backend, and local AI service; starts PostGIS; initializes the regional Overpass database; creates the application schema automatically; starts the background worker; and starts Nginx. The first start downloads the configured Hugging Face model weights and the Israel and Palestine Geofabrik extract. Model weights persist in `ai_models`, while the imported Overpass index persists in `overpass_data`. Initial indexing and area generation can take substantially longer than an ordinary restart. Only Nginx is exposed on the host; the backend, worker, database, local AI service, and Overpass remain on the internal Compose network.

## Local configuration

Nothing must be set in `.env` for local development. The Compose defaults use port `8080`, demo verification codes, the internal Overpass service, the bundled local AI service, and a local `placepulse` database. No API key is required for that default path.

Create `.env` only when you want to override a default:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use `cp .env.example .env`. Docker Compose reads the root `.env` file automatically. After changing it, run `docker compose up -d` to recreate affected containers. Never commit `.env`; it is ignored by Git.

### General and infrastructure variables

| Variable | Default | When to set it |
|---|---|---|
| `APP_PORT` | `8080` | Change the host port used to open the app. |
| `VERIFICATION_SECRET` | local development value | Set a long random value whenever the app is accessible beyond your own localhost. |
| `OSM_USER_AGENT` | `PlacePulse-Course-Project/0.1` | Override the identifier used for OpenStreetMap requests. |
| `OVERPASS_URL` | `http://overpass/api` | Keep the Docker-internal URL unless deliberately connecting the backend to another Overpass service. |
| `OVERPASS_PLANET_URL` | Israel and Palestine Geofabrik PBF | Override the extract downloaded when the Overpass volume is initialized. |
| `OVERPASS_TIMEOUT_SECONDS` | `20` | Change the heartbeat lookup and query timeout. |
| `MAX_REQUEST_BODY_BYTES` | `11534336` (11 MiB) | Change the backend-wide request cap. It must leave multipart overhead above the 10 MiB DIG limit. |
| `MAX_CONCURRENT_HTTP_REQUESTS` | `50` | Change the per-backend in-flight HTTP limit. |
| `MAX_WEBSOCKET_CONNECTIONS` | `100` | Change the per-backend WebSocket limit. |
| `POSTGRES_DB` | `placepulse` | Override the local database name before the first database start. |
| `POSTGRES_USER` | `placepulse` | Override the local database user before the first database start. |
| `POSTGRES_PASSWORD` | `placepulse` | Override the local password before the first database start; use a strong value outside localhost. |

PostgreSQL initialization values are applied only when its data volume is first created. Changing them later requires updating the existing database credentials or resetting the local volumes as described below.

### AI variables

The default `AI_PROVIDER=local` path uses these settings and ignores the external-provider block:

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `local` | Select `local`, `openai`, or `openai-compatible`. |
| `AI_LOCAL_URL` | `http://local-ai:8081` | Docker-internal local inference URL. |
| `AI_TIMEOUT_SECONDS` | `30` | Maximum wait for a local or external model decision. |
| `TEXT_SAFETY_MODEL_ID` | `Qwen/Qwen3Guard-Gen-0.6B` | Local text-safety model. |
| `ROUTER_MODEL_ID` | `Qwen/Qwen3-0.6B` | Local semantic text-routing model. |
| `IMAGE_SAFETY_MODEL_ID` | `OwenElliott/image-safety-classifier-s` | Local image-safety model. |
| `LOCAL_AI_DEVICE` | `auto` | Select the inference device; the default image automatically uses CPU. |
| `LOCAL_AI_MAX_CONCURRENT_INFERENCES` | `1` | Bound simultaneous model executions and memory use. |
| `IMAGE_UNSAFE_THRESHOLD` | `0.5` | Reject an NSFW or NSFL class at or above this probability. |

Set the following only when `AI_PROVIDER=openai` or `AI_PROVIDER=openai-compatible`:

| Variable | Default | Purpose |
|---|---|---|
| `AI_API_URL` | OpenAI Responses API | Structured-output or compatible chat-completions endpoint. |
| `AI_API_FORMAT` | `responses` | Use `responses` for OpenAI or `chat_completions` for a compatible JSON-mode provider. |
| `AI_API_KEY` | empty | Required credential for an external provider. |
| `AI_MODEL` | `gpt-4.1-mini` | Text moderation and routing model. |
| `AI_MODERATION_URL` | OpenAI Moderations API | Used for media only when `AI_MEDIA_MODERATION_MODE=moderations`. |
| `AI_MODERATION_MODEL` | `omni-moderation-latest` | Media moderation model. |
| `AI_MEDIA_MODERATION_MODE` | `moderations` | Use the moderation endpoint, or `model` for a multimodal compatible model. |

### Optional SMS variables

Leave `SMS_PROVIDER` empty for the local demo-code flow. Real SMS delivery requires all three Twilio credentials:

| Variable | Default | Purpose |
|---|---|---|
| `SMS_PROVIDER` | empty | Set to `twilio` to send verification codes. |
| `TWILIO_ACCOUNT_SID` | empty | Twilio account identifier. |
| `TWILIO_AUTH_TOKEN` | empty | Twilio API credential. |
| `TWILIO_FROM_NUMBER` | empty | Message-capable Twilio sender in international format. |
| `SMS_TIMEOUT_SECONDS` | `8` | Maximum wait for SMS delivery acceptance. |

### Twilio example

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

### External AI example

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

## Abuse and overload protection

All request models reject unexpected fields, bound text and numeric inputs, trim required text, and reject invalid control characters. Nginx and the backend independently cap request bodies at 11 MiB; DIG validation then enforces the stricter 10 MiB file limit, allow-listed formats, decoded dimensions, and video duration.

Authentication and write-heavy features use sliding-window rate limits, including KNOCK limits that remain in effect when a client reconnects. Nginx also bounds per-IP request bursts and connections. The backend admits at most 50 concurrent HTTP requests and 100 WebSockets by default, returning a retryable `503` or WebSocket `1013` instead of accepting unbounded work. Uvicorn adds a final connection/backlog and 64 KiB WebSocket-frame cap. These are intentionally single-instance, course-deployment safeguards rather than distributed production controls.

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

### Local Overpass initialization

The `overpass` service downloads the configured Geofabrik PBF only when its persistent database is empty. It converts the PBF, imports the current OSM objects, and builds the derived area index required by the application's `is_in` query. During this first import, the rest of PlacePulse can start normally, but location heartbeats return the existing temporary-unavailable error until area generation finishes.

Follow initialization progress with:

```sh
docker compose logs -f overpass
```

When the service is healthy, verify a real coordinate through its internal API and the same query shape used by the backend:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test-overpass.ps1
```

Custom coordinates can be supplied with `-Latitude` and `-Longitude`. The Overpass HTTP endpoint is intentionally not published to the host; the smoke script executes the request inside the container.

The course-sized default is a static snapshot, so no replication feed runs in the background. To refresh it, first stop the stack with `docker compose down`, list the exact targeted volume with `docker volume ls --filter label=com.docker.compose.volume=overpass_data`, remove only that Overpass volume with `docker volume rm <exact-volume-name>`, and start the stack again. This rebuild does not require deleting the PostgreSQL, media, or model volumes. Removing a Docker volume is destructive, so verify the printed volume name before running the removal command.

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

### Jailbreak and hallucination robustness

PlacePulse includes course-sized **jailbreak robustness**. Untrusted text is Unicode-normalized, invisible characters are removed, and known prompt-injection/jailbreak patterns are rejected before inference. Prompts tell the model not to follow instructions embedded in user text or media, generated reason text is screened again, and invalid, timed-out, or nonconforming decisions fail closed.

It also includes **hallucination robustness** by treating AI output as an untrusted suggestion rather than a source of application facts. Decisions must match strict schemas and allow-listed moderation categories. Routing can select only backend-supplied OpenStreetMap place IDs with a valid stored hierarchy; an invented ID, a result that contradicts an explicitly named place, or low-confidence media routing is rejected. The final selected scope is independently checked against fresh user presence before publication.

Security-marked tests cover direct and zero-width-obfuscated jailbreak text, invented moderation categories and place IDs, contradictory place routing, instruction-like model output, low-confidence routing, malformed output, and timeouts. These controls reduce and contain model errors; they do not prove resistance to every future jailbreak or hallucination, so the remaining limitation is tracked in the [risk assessment](docs/risk-assessment.md).

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

It does not reset the normal `place_pulse` Compose project or its saved data. GitHub Actions repeats the backend tests, frontend production build, local-AI contract tests, and fresh four-service startup on every push and pull request. An enabled Azure deployment runs afterward only for `main`.

## Startup smoke test

On PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

The smoke test builds and starts the stack, waits for the public health endpoint, confirms that the schema exists, writes one harmless foundation record, restarts PostgreSQL, and confirms the record is still present. It leaves the application running for inspection.

## Optional Azure VM deployment

The course-sized Azure path runs the same Docker Compose stack on one Ubuntu VM, so PostgreSQL/PostGIS, media, the backend, worker, and Nginx keep the same architecture. Only SSH and Nginx on port 80 need to be opened publicly. Create the billable VM manually in the Azure portal; the repository does not provision Azure resources.

Prerequisites:

- An Ubuntu 24.04 VM with a public IP or DNS name. For the complete stack with local AI, use a non-burstable **4-vCPU, 16 GiB RAM** VM with at least **80 GiB of fast SSD storage**. When an external AI provider is configured, **2 vCPUs and 8 GiB RAM** is a workable minimum.
- Azure network rules allowing inbound TCP ports 22 and 80
- An SSH user with `sudo` access
- The repository available from the public GitHub URL, with the target branch pushed
- A private `.env` containing strong `VERIFICATION_SECRET` and `POSTGRES_PASSWORD` values, plus external AI or Twilio settings only if those services are used

Overpass initialization is largely single-core and disk intensive, so 8 vCPUs do not make the first import twice as fast as 4 vCPUs. Prefer sustained per-core CPU performance and fast SSD storage over a larger burstable core count.

Connect to the new VM and install the application once:

```sh
ssh <user>@<vm-host>
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
sudo install -d -o "$USER" -g "$USER" /opt/placepulse
git clone --depth 1 --branch main https://github.com/abatamny/place_pulse.git /opt/placepulse
exit
```

Reconnect so the Docker group membership takes effect, then create `/opt/placepulse/.env`. For the default local AI and demo verification flow, it needs:

```dotenv
VERIFICATION_SECRET=replace-with-a-long-random-value
POSTGRES_PASSWORD=replace-with-a-strong-database-password
APP_PORT=80
```

Restrict and start it with:

```sh
chmod 600 /opt/placepulse/.env
cd /opt/placepulse
docker compose up --build -d
```

For a course demo, use dedicated low-value external-service credentials rather than important production credentials. GitHub Actions can automatically deploy the exact tested `main` commit over SSH and remains disabled until its GitHub variables and secrets are configured. Follow [the automatic Azure deployment setup](docs/azure-auto-deploy.md) to add a deployment key and pin the VM host key.

### GitHub Actions deployment configuration

Create a GitHub environment named `azure-production` and configure these values:

| GitHub location | Name | Value |
|---|---|---|
| Repository variable | `AZURE_DEPLOY_ENABLED` | `true` to enable deployment; use `false` to disable it. |
| Repository variable | `AZURE_VM_HOST` | The VM's public IPv4 address or DNS name. |
| Repository variable | `AZURE_VM_USER` | The SSH user that owns `/opt/placepulse` and can run Docker. |
| `azure-production` environment secret | `AZURE_VM_SSH_PRIVATE_KEY` | A deployment-only private SSH key authorized on the VM. |
| `azure-production` environment secret | `AZURE_VM_KNOWN_HOSTS` | A verified `known_hosts` entry for the VM. |

The VM copy of `/opt/placepulse/.env` remains outside Git, and normal deployments preserve it along with the PostgreSQL, media, model, and Overpass volumes. The workflow performs the fetch, Compose rebuild, and health check directly over SSH; it needs no Azure service principal, federated credential, or Azure client secrets.

When the demo is finished, delete the Azure resource group in the portal. This permanently deletes the VM and its stored database/media volumes.

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

Start it again with `docker compose up -d`; the named database, media, model, and Overpass volumes are reused.

Reset all local application data:

```sh
docker compose down -v
```

The reset command permanently removes the local database, media, model-cache, and Overpass volumes. The next startup must download and import the models and regional OSM extract again.
