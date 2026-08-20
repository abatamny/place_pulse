# PlacePulse

[![CI](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/abatamny/place_pulse/actions/workflows/ci.yml)

Repository: <https://github.com/abatamny/place_pulse>

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place: live location-scoped KNOCK messages, temporary DIG media, permanent Explore memories, place forums, and direct messages, all backed by AI moderation.

## Run it locally

Requirements: Docker Desktop, or Docker Engine with Compose v2. No local Node.js, Python, or PostgreSQL install is needed.

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. No `.env` file is required — the defaults use demo verification codes, an internal Overpass service, and a bundled local AI model. The first start downloads model weights and an OSM extract, which can take a while; watch progress with `docker compose logs -f overpass`.

To override a default, copy `.env.example` to `.env` and edit it, then run `docker compose up -d` again. Never commit `.env`.

Useful commands:

```sh
docker compose logs -f            # view logs
docker compose down               # stop, keep data
docker compose down -v            # stop and wipe all local data/models
docker compose run --build --rm backend pytest -q   # run the test suite
```

See [.env.example](.env.example) for every configurable variable (ports, AI provider, Twilio SMS, request limits, database credentials).

## Deploy to Azure

Pushing to `main` deploys the same Compose stack to an Azure VM over SSH via GitHub Actions, once these are set in a GitHub environment named `azure-production`:

| Type | Name | Value |
|---|---|---|
| Repository variable | `AZURE_DEPLOY_ENABLED` | `true` to enable deployment |
| Repository variable | `AZURE_VM_HOST` | VM public IP or DNS name |
| Repository variable | `AZURE_VM_USER` | SSH deployment user |
| Environment secret | `AZURE_VM_SSH_PRIVATE_KEY` | deployment-only private SSH key authorized on the VM |
| Environment secret | `AZURE_VM_KNOWN_HOSTS` | pinned `ssh-keyscan -t ed25519 -H <vm-host>` output |

No Azure service principal, federated credential, or Azure CLI login is needed — the workflow only uses SSH. Set `AZURE_DEPLOY_ENABLED` to `false` to disable deployment without touching the VM.

## More documentation

- [Final report](docs/final-report.md)
