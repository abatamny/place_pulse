# PlacePulse - Codex Instructions

## Authoritative scope

- Read `plan.md` completely before making project changes.
- Treat `plan.md` as the authoritative definition of the architecture, features, implementation order, and completion conditions.
- Follow the user's current request. Work on only the requested numbered step and do not begin the next step automatically.
- If a decision would materially expand or change the plan, ask the user before implementing it.

## Keep the project course-sized

- This is a university course project, not a production startup. Implement the smallest clear solution that meets the proposal and course requirements.
- Do not implement optional features unless the user explicitly requests them.
- Prefer direct, readable feature code over speculative abstractions, generic frameworks, or premature extensibility.
- Do not add services or infrastructure outside the architecture in `plan.md` without the user's approval.
- Do not add Redis, a message broker, object storage, Kubernetes, service discovery, an API gateway, a service mesh, distributed caching, event sourcing, CQRS, or a separate observability stack.
- Do not add unrelated product features such as analytics, recommendations, following/friends, multi-tenancy, complex profiles, offline mode, an admin dashboard, or a production SMS provider.
- Interpret scalability and failure requirements at course-project level. Implement simple safeguards and document larger production improvements in the risk assessment instead of building them.

## Implementation rules

- Preserve working code and avoid unrelated refactors.
- Follow existing repository patterns. Add a dependency only when it is needed for the current step.
- Keep the frontend functional and mobile-friendly. Do not spend time on elaborate styling, animations, a design system, or unnecessary frontend abstractions.
- Do not add application seed data unless the user requests it. Users, places, and content should be created through the app and OSM flow described in `plan.md`.
- Never weaken course-required safeguards: password hashing, authentication and authorization, input validation, rate limits, upload limits, persistent data, safe failure handling, and internal-only database/worker services.

## Testing and completion

- Add the essential unit and integration tests needed for the current feature. Leave the broad E2E, security, and stress suites for Step 9 unless the current change specifically requires them.
- Use deterministic test fixtures or mocks for external services; automated tests must not depend on live OpenStreetMap or paid AI calls.
- Run the relevant available tests after changes. Do not claim a test passed unless it was actually run.
- A step is finished when its **Complete when** condition in `plan.md` is satisfied.
- When finished, summarize what changed and what was tested, then stop and wait for the user.
