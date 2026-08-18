# PlacePulse

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place. This repository currently contains the runnable project foundation from Step 1 of `plan.md`.

## Requirements

- Docker Desktop, or Docker Engine with Docker Compose v2

No local Node.js, Python, PostgreSQL, or PostGIS installation is required.

## Start the application

From the repository root, run:

```sh
docker compose up --build -d
```

Open <http://localhost:8080>. The backend health endpoint is available through the public web service at <http://localhost:8080/api/health>.

This one command builds the React frontend and FastAPI backend, starts PostGIS, creates the application schema automatically, and starts Nginx. Only Nginx is exposed on the host; the backend and database remain on the internal Compose network.

## Configuration

The defaults work without creating an `.env` file. To change them, copy `.env.example` to `.env` and edit:

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8080` | Public application port |
| `POSTGRES_DB` | `placepulse` | PostgreSQL database name |
| `POSTGRES_USER` | `placepulse` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `placepulse` | Local PostgreSQL password |

Do not commit `.env`; it is ignored by Git.

## Startup smoke test

On PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

The smoke test builds and starts the stack, waits for the public health endpoint, confirms that the schema exists, writes one harmless foundation record, restarts PostgreSQL, and confirms the record is still present. It leaves the application running for inspection.

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

