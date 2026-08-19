# PlacePulse

[![CI](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml)

Repository: <https://github.com/abatamny/place_pulse>

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place. The project currently includes authentication, place/presence tracking, AI-backed moderation, live place-scoped KNOCK messages, temporary DIG media, permanent Explore memories, place forums, and private direct messages.

## Requirements

- Docker Desktop, or Docker Engine with Docker Compose v2

No local Node.js, Python, PostgreSQL, or PostGIS installation is required.

## Start the application

From the repository root, run:

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. The backend health endpoint is available through the public web service at <http://localhost:8080/api/health>.

This one command builds the React frontend and FastAPI backend, starts PostGIS, creates the application schema automatically, starts the background worker, and starts Nginx. Only Nginx is exposed on the host; the backend, worker, and database remain on the internal Compose network.

## Configuration

The defaults work without creating an `.env` file. To change them, copy `.env.example` to `.env` and edit:

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8080` | Public application port |
| `APP_ENV` | `development` | Runtime environment label; verification delivery does not depend on it |
| `VERIFICATION_SECRET` | local development value | Hashes temporary verification codes; change it outside localhost |
| `SMS_PROVIDER` | empty | Leave empty to show a demo code, or set to `twilio` to send SMS |
| `TWILIO_ACCOUNT_SID` | empty | Twilio account identifier, required when `SMS_PROVIDER=twilio` |
| `TWILIO_AUTH_TOKEN` | empty | Twilio API credential, required when `SMS_PROVIDER=twilio` |
| `TWILIO_FROM_NUMBER` | empty | Message-capable Twilio sender number in international format |
| `SMS_TIMEOUT_SECONDS` | `8` | Maximum wait for SMS delivery acceptance |
| `OSM_USER_AGENT` | `PlacePulse-Course-Project/0.1` | Identifies backend requests to OpenStreetMap services |
| `NOMINATIM_URL` | public Nominatim URL | Reverse-geocoding endpoint |
| `OVERPASS_URL` | public Overpass URL | Containing-place and boundary endpoint |
| `AI_PROVIDER` | `openai` | AI adapter provider |
| `AI_API_URL` | OpenAI Responses API | Structured-output endpoint |
| `AI_API_FORMAT` | `responses` | `responses` for native OpenAI or `chat_completions` for compatible JSON-mode providers |
| `AI_API_KEY` | empty | Provider API key; required only when an AI operation is used |
| `AI_MODEL` | `gpt-4.1-mini` | Model used for moderation and place routing |
| `AI_MODERATION_URL` | OpenAI Moderations API | Image-moderation endpoint |
| `AI_MODERATION_MODEL` | `omni-moderation-latest` | Model used for DIG image and video-frame moderation |
| `AI_MEDIA_MODERATION_MODE` | `moderations` | Use the moderation endpoint, or `model` to moderate media with a multimodal chat model |
| `AI_TIMEOUT_SECONDS` | `8` | Maximum wait for a model decision |
| `POSTGRES_DB` | `placepulse` | PostgreSQL database name |
| `POSTGRES_USER` | `placepulse` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `placepulse` | Local PostgreSQL password |

Do not commit `.env`; it is ignored by Git.

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

In compatible mode, text decisions and DIG image/video-frame checks use validated JSON returned by the configured model. Native OpenAI remains the default and continues to use strict Responses schemas plus the Moderations API.

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
3. The backend resolves the coordinates through OpenStreetMap and displays nested places, such as a campus and its building.
4. While location sharing remains enabled, the page sends a heartbeat every 30 seconds. Stored PostGIS boundaries are reused instead of contacting OpenStreetMap again for known places.

Presence expires after 90 seconds without a heartbeat. A completed presence becomes a saved visit, and three completed visits at a place promote the user from `VISITOR` to `BELONG`.

## KNOCK live messages

After sharing a location, the main screen connects to the authenticated KNOCK WebSocket and loads recent messages from every active place layer. Messages are routed to one matching layer, so a building KNOCK is not broadcast to unrelated places. Accepted messages are stored in PostgreSQL and return after reconnecting.

`VISITOR` messages are moderated before publication and fail closed if the AI provider is unavailable. `BELONG` messages appear immediately and create a PostgreSQL background job for the worker to check afterward. Set `AI_API_KEY` in `.env` to send visitor messages or route messages when OpenStreetMap returns multiple nested places.

## DIG temporary media

Open the **DIG** tab after sharing your location to view or post media for any active place layer. A DIG may be a JPEG, PNG, WebP, MP4, or WebM file up to 10 MB; videos are limited to 15 seconds. Every upload is validated and moderated before it is written to the persistent media volume or listed in the feed.

Approved DIGs remain available to users currently at that place for 24 hours. Rejected and expired media is not shown. Videos are checked using three representative frames because the configured moderation model accepts images rather than video files directly. Set `AI_API_KEY` in `.env` to publish DIGs in a live demo; automated tests use a fake provider.

## Explore place memories

The background worker checks approved DIG activity without making another AI call. Three unpreserved DIGs posted to the same place within one hour create an Explore memory containing up to five DIGs. The memory and its selected media remain available after the original 24-hour DIG feed entries expire.

Every author whose DIG was selected is a participant and can revisit that memory after leaving. Other users can view, like, and comment on it only while their location heartbeat shows that they are currently at the same place. Open the **Explore** tab to see all memories currently accessible to the signed-in user.

## Place forum and personal area

Open **Forum** after sharing your location to read or create persistent text posts for any active place layer. Posts may be anonymous, and present users can add comments or change an upvote/downvote. Post and comment text is moderated before publication and fails closed if the configured AI provider is unavailable. Forum media is intentionally omitted to keep this optional course feature small.

The **My posts** view remains available after leaving a place. It lists the signed-in user's posts and totals their received likes, dislikes, and net score. Anonymous posts never reveal their author in public API responses.

## Direct messages

The **Messages** tab supports private one-to-one conversations without requiring location presence. Search for another verified user by nickname or phone number, send a saved message, and reopen the complete recent history later. Only the sender and recipient can obtain that conversation through the API.

An authenticated WebSocket remains connected while the signed-in app is open. New messages update the unread badge immediately, while unread counts and read timestamps are also persisted in PostgreSQL.

## AI moderation and worker

The backend has one adapter for structured text-moderation and nested-place routing decisions. Pre-publication calls have a timeout and fail closed: invalid input, prompt-injection patterns, invalid model output, and provider failures never produce an approval.

Post-publication moderation is placed in the PostgreSQL `ai_jobs` table. The internal `worker` service rotates among users' oldest jobs so one busy user cannot starve everyone else, records a completed structured result or a safe failed status, and continues running after model errors.

Model inputs are normalized before broader jailbreak-pattern checks, untrusted OpenStreetMap place facts and containment relationships are validated, moderation categories are restricted, and routing results must use known place IDs without contradicting an explicitly named place. Automated tests inject a deterministic fake adapter, so test runs never call or charge a real provider. For a live demo, set `AI_API_KEY` in your uncommitted `.env` file.

## Automated tests

With the database service running, execute:

```sh
docker compose run --build --rm backend pytest -q
```

The tests automatically create and use a separate PostGIS-enabled `placepulse_test` database. OpenStreetMap is replaced with a deterministic fake resolver, so tests do not depend on live network services or modify users created through the application.

The final suites can also be run separately:

```sh
docker compose run --build --rm backend pytest -q -m system
docker compose run --build --rm backend pytest -q -m security
docker compose run --build --rm backend pytest -q -m stress
```

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
