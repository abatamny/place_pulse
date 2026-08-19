# PlacePulse risk assessment

This assessment is intentionally scoped to a university course deployment: one Docker Compose stack on one machine or Azure VM.

| Risk | Current control | Remaining limitation / production improvement |
|---|---|---|
| AI provider timeout, outage, or invalid output | Short request timeout, strict response validation, pre-publication operations fail closed, worker records failed jobs and continues | Live posting that requires AI can be temporarily unavailable. Production could add provider redundancy and operator alerts. |
| Prompt injection or unsafe generated decisions | Inputs are normalized and checked, moderation categories are allow-listed, place IDs and hierarchy are validated | Pattern checks cannot guarantee detection of every future attack. Production needs ongoing adversarial evaluation and policy updates. |
| OpenStreetMap outage or rate limit | Errors return safely without replacing current presence with an unverified local match | Every heartbeat depends on OpenStreetMap. Production could use a permitted cache/proxy and monitored retry policy that still refreshes nested-place data. |
| Unauthorized access to place content | Short-lived presence is checked for KNOCK, DIG, Explore, and Forum; automated cross-place tests cover isolation | Browser coordinates can be spoofed. Stronger proof of physical presence is outside the course scope. |
| Direct-message privacy leak | Every conversation query is filtered to the authenticated sender/recipient; tests include an unrelated user | Messages are not end-to-end encrypted. Production would add stronger privacy review, retention controls, and audit tooling. |
| Anonymous-post identity exposure | Public responses replace the author with `Anonymous` while the database retains ownership for the personal area | Database administrators can still identify authors. The UI should describe anonymity as public, not absolute. |
| Malicious or excessive media uploads | Allow-listed MIME types, decoded file validation, 10 MB limit, 15-second video limit, pixel limit, moderation before persistence | Sophisticated parser attacks remain possible. Production could isolate media processing and scan files with dedicated tooling. |
| Authentication abuse | Argon2 password hashing, random hashed sessions, verification expiry, revocable sessions, per-process rate limits | Rate-limit state resets when the backend restarts and does not coordinate across replicas. This is acceptable for the single backend course deployment. |
| Database or host failure | PostgreSQL health checks, persistent Docker volumes, safe API health response | One VM/database remains a single point of failure. Production needs backups, restore drills, and managed high availability. |
| Worker backlog or user starvation | Durable PostgreSQL jobs and round-robin selection among users | One worker limits throughput. Production could add safe multi-worker claiming and queue monitoring. |
| WebSocket scaling | Place rooms and DM connections are isolated correctly inside one backend process | Multiple backend replicas would need shared pub/sub. The course deployment intentionally stays single-process. |
| Secret exposure | `.env` and Azure environment files are ignored; credentials are never embedded in images or tests | Local files and shell history still require care. Use a dedicated low-value demo key and rotate any exposed key. |
| Automatic deployment compromise or failure | Deployment requires successful CI, uses short-lived GitHub OIDC tokens, scopes the Azure role to one VM, deploys the tested commit SHA, and performs a health check | Virtual Machine Contributor can execute commands as root through the VM agent. Protect the GitHub environment and disable deployment when the demo VM is not needed. |
| Loss of local media/database data | Named volumes survive normal shutdown; reset is explicitly documented as destructive | There is no automatic backup. Export important demo data before resetting or deleting an Azure resource group. |
| Dependency or regression failure | Pinned Python packages, fixed frontend versions, deterministic tests, GitHub Actions build/test/fresh-start jobs | Automated dependency updates and vulnerability scanning are not included at course-project scope. |

## Failure behavior summary

- AI or OSM failures return a clear error and do not publish unverified content.
- Database failure makes `/api/health` return `503`; Compose health checks prevent dependent services from being treated as ready.
- Expired presence removes access to place-only feeds and turns the completed presence into a visit.
- Failed post-publication moderation jobs are stored as failed instead of crashing the worker loop.
- A fresh-start test uses a separate Compose project and deletes only its temporary containers and volumes.
