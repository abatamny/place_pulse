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

The Azure path runs the same Compose stack on a single Ubuntu VM. Azure resources are created manually in the portal; this repo does not provision infrastructure.

1. Create an Ubuntu 24.04 VM (4 vCPUs / 16 GiB RAM / 80 GiB SSD for the full local-AI stack) with inbound TCP 22 and 80 open.
2. On the VM, install Docker and clone the repo:

   ```sh
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
   sudo systemctl enable --now docker
   sudo usermod -aG docker "$USER"
   sudo install -d -o "$USER" -g "$USER" /opt/placepulse
   git clone --depth 1 --branch main https://github.com/abatamny/place_pulse.git /opt/placepulse
   ```

3. Reconnect, then create `/opt/placepulse/.env` with at least:

   ```dotenv
   APP_PORT=80
   VERIFICATION_SECRET=replace-with-a-long-random-value
   POSTGRES_PASSWORD=replace-with-a-strong-database-password
   ```

4. Start it:

   ```sh
   chmod 600 /opt/placepulse/.env
   cd /opt/placepulse && docker compose up --build -d
   ```

5. Confirm `http://<vm-host>/api/health` responds.

### Automatic deployment from GitHub Actions

Pushes to `main` can redeploy the VM over SSH automatically. Create a GitHub environment named `azure-production` and set:

| Type | Name | Value |
|---|---|---|
| Repository variable | `AZURE_DEPLOY_ENABLED` | `true` to enable |
| Repository variable | `AZURE_VM_HOST` | VM public IP or DNS name |
| Repository variable | `AZURE_VM_USER` | SSH deployment user |
| Environment secret | `AZURE_VM_SSH_PRIVATE_KEY` | deployment-only private SSH key |
| Environment secret | `AZURE_VM_KNOWN_HOSTS` | pinned `ssh-keyscan -t ed25519 -H <vm-host>` output |

Full key-generation and host-pinning steps are in [docs/azure-auto-deploy.md](docs/azure-auto-deploy.md). Set `AZURE_DEPLOY_ENABLED` to `false` to disable deployment without touching the VM.

## More documentation

- [Final report](docs/final-report.md)
- [Feature-to-test matrix](docs/feature-test-matrix.md)
- [Risk assessment](docs/risk-assessment.md)
- [Demonstration video script](docs/demo-script.md)
- [Automatic Azure deployment setup](docs/azure-auto-deploy.md)
