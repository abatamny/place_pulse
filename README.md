# PlacePulse

PlacePulse is a mobile-first course project for interacting with people and content connected to a physical place. The project currently includes the runnable foundation, authentication, and Step 3 place/presence tracking.

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
| `APP_ENV` | `development` | Returns verification codes in the UI for localhost use |
| `VERIFICATION_SECRET` | local development value | Hashes temporary verification codes; change it outside localhost |
| `OSM_USER_AGENT` | `PlacePulse-Course-Project/0.1` | Identifies backend requests to OpenStreetMap services |
| `NOMINATIM_URL` | public Nominatim URL | Reverse-geocoding endpoint |
| `OVERPASS_URL` | public Overpass URL | Containing-place and boundary endpoint |
| `POSTGRES_DB` | `placepulse` | PostgreSQL database name |
| `POSTGRES_USER` | `placepulse` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `placepulse` | Local PostgreSQL password |

Do not commit `.env`; it is ignored by Git.

## Local authentication flow

1. Open <http://localhost:8080> and choose **Register**.
2. Enter a nickname, phone number, and password of at least eight characters.
3. In development mode, the six-digit verification code is shown directly on the verification screen. No SMS service is required for the course demo.
4. Verify the phone number, then log in with the same phone number and password.

Passwords are Argon2-hashed. Login creates a random, revocable session whose token hash is stored in PostgreSQL; logging out deletes that session.

## Location and presence flow

1. Log in and select **Share my location**.
2. Allow the browser's location prompt. Localhost is treated as a secure browser context for geolocation.
3. The backend resolves the coordinates through OpenStreetMap and displays nested places, such as a campus and its building.
4. While location sharing remains enabled, the page sends a heartbeat every 30 seconds. Stored PostGIS boundaries are reused instead of contacting OpenStreetMap again for known places.

Presence expires after 90 seconds without a heartbeat. A completed presence becomes a saved visit, and three completed visits at a place promote the user from `VISITOR` to `BELONG`.

## Automated tests

With the database service running, execute:

```sh
docker compose run --build --rm backend pytest -q
```

The tests automatically create and use a separate PostGIS-enabled `placepulse_test` database. OpenStreetMap is replaced with a deterministic fake resolver, so tests do not depend on live network services or modify users created through the application.

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
