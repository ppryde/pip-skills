# Backend For Frontend (BFF) Architecture Doctrine

The BFF doctrine enforces the creation of specialized backend layers for specific user interfaces. It ensures that core domain services remain clean and "client-agnostic" while providing a tailored, high-performance experience for diverse clients (e.g., Mobile, Web, IoT).

**Language Scope:** Language-agnostic

## When to Use

Use the BFF pattern when your application supports multiple diverse client types that have significantly different data requirements, display constraints, or security profiles. It is essential when a mobile client would otherwise need to make dozens of "chatty" calls to a general-purpose API, or when a Web UI requires a different authentication flow than a Mobile app.

**Do NOT use this pattern** if you have only one client type or if your clients have identical data requirements. In those cases, a single "General API" is more cost-effective.

## Why Use It

* **Performance (Aggregation)** — A BFF aggregates data from multiple downstream services into a single response, reducing mobile latency.
* **UI-Specific Optimization** — Format and filter data specifically for the client's display needs (e.g., removing heavy fields for smartwatch UIs).
* **Decoupled Evolution** — Frontend teams can change their BFF's API contract without waiting for core domain teams to update general services.
* **Security Specialization** — Handle different security protocols (e.g., cookie-based sessions for Web, JWT for Mobile) within isolated layers.

## Pros and Cons

| Pros | Cons |
|---|---|
| Faster UI rendering by aggregating multiple downstream calls into one. | Increased operational overhead; more deployment units to manage and monitor. |
| Shields frontend teams from changes in the complex backend service graph. | Risk of "Logic Leak" where domain business rules start living in the BFF. |
| Enables client-specific security, rate-limiting, and compression policies. | Potential for code duplication across different BFFs (e.g., shared auth logic). |
| Smaller, focused payloads tailored to the client's specific screen size. | Latency amplification if the BFF itself is not highly performant/parallel. |
| Simplifies frontend code by removing data-massaging and aggregation logic. | Requires strong contract testing to ensure BFFs don't drift from Core APIs. |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `bff/` — Root directory for all specialized backends.
- `bff/*/api/` — Client-facing endpoint definitions (REST/GraphQL).
- `bff/*/mappers/` — Logic transforming Core service models into UI-specific DTOs.
- `bff/*/clients/` — Proxies and clients used to call downstream Core Services.
- `services/core/` — Source-of-truth domain services consumed by the BFFs.

## Violation Catalog

### Boundary, Responsibility & Mapping Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-001 | logic-leak | Domain business logic must not reside in the BFF | error | Calculation or validation logic in `bff/` that isn't purely about formatting |
| BFF-002 | persistence-leak | A BFF must not have its own database or direct DB access | error | Import of ORMs, SQL clients, or database drivers inside `bff/` |
| BFF-003 | cross-bff-dependency | BFFs must not depend on or call other BFFs | error | `import <pkg>.bff.mobile` found in `bff/web/` |
| BFF-004 | direct-core-bypass | Clients must not bypass the BFF to call Core Services directly | warning | Frontend code containing direct URLs to `services/core/` |
| BFF-005 | shared-bff | A single BFF must not serve multiple diverse client types | warning | One BFF handling both Mobile and Web if payloads are >30% different |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-021 | model-coupling | BFFs must not use Core Service DTOs as their own API response | error | `bff/*/api/` methods returning classes defined in `services/core/` |
| BFF-022 | missing-mapper | Every BFF endpoint should use a dedicated mapper | warning | Controllers in `bff/` performing inline data transformation |
| BFF-023 | polymorphic-leak | BFF should hide internal type hierarchies from the UI | warning | Returning internal class type names or discriminator fields in JSON |
| BFF-024 | invalid-date-format | BFF must standardize dates to a client-preferred format | warning | Returning raw DB timestamps instead of ISO-8601 or localized strings |
| BFF-025 | enum-leak | Do not expose internal service Enums directly to the UI | warning | Mapping core Enums 1:1 without a stable BFF-specific Enum |

### Communication, Latency & Concurrency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-006 | synchronous-bottleneck | Downstream calls should be executed in parallel where possible | warning | Sequential `await` statements for independent data sources |
| BFF-007 | missing-aggregation | BFFs should provide aggregated endpoints for complex UI views | warning | UI making multiple BFF calls to load one screen instead of one composite call |
| BFF-008 | payload-bloat | BFF responses must only contain fields required by the UI | error | BFF returning 1:1 copies of Core Service entities without filtering |
| BFF-009 | excessive-hop-count | BFF endpoints should not call more than 10 downstream services | warning | A single BFF request triggering > 10 internal network calls |
| BFF-010 | missing-pagination | BFF must forward or implement pagination for large lists | error | Endpoints returning arrays without `limit`, `offset`, or `cursor` |
| BFF-035 | thread-leak | Async operations must use managed thread pools | error | Usage of `new Thread()` or unmanaged `CompletableFuture` in BFF logic |
| BFF-036 | connection-monopoly | Limit the number of concurrent calls to a single Core service | warning | Lack of bulkhead configuration for high-traffic downstream services |
| BFF-037 | unconstrained-buffers | Limit the size of incoming request bodies in the BFF | error | Missing `max-payload-size` configuration in BFF settings |
| BFF-038 | event-loop-block | BFF must not perform synchronous IO on the main event loop | error | `fs.readFileSync` or similar blocking calls in Node.js/Netty BFFs |

### Security, Privacy & Data Sovereignty Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-011 | secret-exposure | Downstream API keys/secrets must not be exposed to the UI | error | BFF responses containing raw internal tokens or service-to-service keys |
| BFF-012 | token-passing | BFF must translate client auth to internal service auth | error | Passing UI cookies/session-ids directly to downstream domain services |
| BFF-013 | missing-cors-policy | Every BFF must have a strict, client-specific CORS policy | error | Usage of `Access-Control-Allow-Origin: *` in any `bff/` configuration |
| BFF-014 | plaintext-transmission | PII or sensitive data must be encrypted if the client is public | warning | Lack of field-level encryption for sensitive fields in the `mappers/` layer |
| BFF-015 | inadequate-sanitization | BFF must sanitize all inputs before forwarding to Core | error | Direct forwarding of raw UI request bodies to downstream PUT/POST calls |
| BFF-046 | cross-region-leak | BFF should live in the same region as the client's data | warning | A US-based BFF calling EU-based core services for EU users |
| BFF-047 | excessive-pii-handling | BFF should only "see" PII it absolutely needs for display | warning | Mapping logic that touches PII fields not used in the final response |
| BFF-048 | missing-consent-check | BFF must respect user data consent flags | error | Returning "Marketing" data through the BFF when the `consent_flag` is false |
| BFF-049 | unmasked-id | Mask or obfuscate internal database IDs in public responses | warning | Returning raw integer Auto-increment IDs instead of HashIDs or UUIDs |
| BFF-050 | static-client-coupling | Avoid hard-coupling BFF DTOs to specific UI components | warning | Naming BFF DTO fields after UI elements (e.g., `SubmitButtonLabel`) |

### Resilience & Fault Tolerance Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-016 | missing-circuit-breaker | Downstream calls must use circuit breakers | error | Client calls in `bff/*/clients/` missing a resilience wrapper |
| BFF-017 | missing-timeout | Every downstream call must have a strict timeout (< 2s) | error | Client instantiations without an explicit `readTimeout` |
| BFF-018 | missing-fallback | BFF endpoints must define a fallback for failed downstream calls | warning | Lack of "graceful degradation" (e.g., returning cached or empty data) |
| BFF-019 | retry-storm | BFF retries must use exponential backoff and jitter | error | Simple loop retries found in `bff/` client logic |
| BFF-020 | bulkhead-isolation | Use bulkheads to prevent one downstream service from killing the BFF | warning | Lack of dedicated thread pools or semaphores per downstream client |

### Caching & State Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-026 | stateful-bff | BFFs should be stateless to allow horizontal scaling | error | Usage of local file system or in-memory sessions for user data |
| BFF-027 | missing-header-forwarding | Cache-Control headers from Core should be respected/forwarded | warning | BFF ignoring downstream `ETag` or `Cache-Control` headers |
| BFF-028 | over-caching | Sensitive user data must not be cached at the BFF level | error | Caching responses containing PII without a user-specific cache key |
| BFF-029 | distributed-cache-leak | Avoid sharing a single cache instance between different BFFs | warning | `bff/web` and `bff/mobile` using the same Redis namespace/prefix |

### Observability & Performance Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-030 | trace-interruption | BFFs must propagate Correlation IDs | error | Downstream client calls that do not forward the `X-Correlation-ID` |
| BFF-031 | opaque-error-mapping | Translate downstream errors into UI-friendly codes | warning | Passing raw `500` or `403` errors from Core directly to the UI |
| BFF-032 | missing-golden-signals | BFFs must expose Rate, Error, and Duration metrics | error | Absence of Prometheus or OpenTelemetry metrics for BFF endpoints |
| BFF-033 | logs-in-production | Avoid logging PII or raw payloads in production logs | error | Log statements in `bff/` printing `request.body` or `response.data` |
| BFF-034 | slow-mapper | Mapping logic must not exceed 50ms per request | warning | Complex recursive mappers in `bff/*/mappers/` causing latency spikes |

### Deployment & Hygiene Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| BFF-039 | version-mismatch | BFF should be deployable independently of Core Services | warning | Build scripts requiring a synchronized deploy of `bff/` and `services/core/` |
| BFF-040 | orphaned-bff | BFF must be owned by the UI team, not the Core team | warning | Code review requirements for `bff/` not including Frontend developers |
| BFF-041 | hardcoded-core-urls | Core service URLs must be injected via environment/discovery | error | Hardcoded `http://core-service:8080` strings in BFF client code |
| BFF-042 | missing-contract-tests | BFF must have contract tests against the Core API | error | Absence of `Pact` or `Consumer Driven Contract` tests in `bff/*/tests/` |
| BFF-043 | legacy-bloat | Remove BFF endpoints that are no longer used by the UI | warning | Endpoints in `bff/` with zero recorded traffic in the last 30 days |
| BFF-044 | monolithic-bff-structure | Every client must have a physically isolated BFF directory | error | `bff/` containing all client logic without `web/`, `mobile/` sub-folders |
| BFF-045 | bypass-validation | BFF must validate UI inputs before hitting the Core network | error | Lack of validation annotations on BFF API DTOs |

## Allowed Exceptions

- **Edge Gateway Functionality:** If using an API Gateway (like Kong) as the BFF, transformation logic in Lua is allowed.
- **Admin Pass-through:** Simple proxies without mapping are permitted for internal admin tools.
- **SSR Layers:** Next.js/Nuxt SSR layers acting as the BFF are exempt from "No Logic" rules if the logic is purely for rendering.

## Cross-Reference

This doctrine pairs well with:
- **microservices.md** — BFFs act as the entrance to the service mesh.
- **resilience.md** — Protecting the BFF from downstream cascading failures.
- **messaging.md** — For triggering async background work from the BFF.
- **cqrs.md** — BFFs typically function as the "Read Model" aggregator.

## Sources and Authority

**Foundational Works:**
- [Sam Newman - Pattern: Backends For Frontends (2015)](https://samnewman.io/patterns/architectural/bff/)
- [Phil Calçado - Pattern: Backends For Frontends](https://philcalcado.com/2015/09/18/the_back_end_for_front_end_pattern_bff.html)

**Practitioner Guidance:**
- [Microsoft Azure - Backend for Frontend pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/backends-for-frontends)
- [Netflix Tech Blog - Adopting GraphQL](https://netflixtechblog.com/our-learnings-from-adopting-graphql-f1a2398d5738)

**Anti-Patterns / Failure Cases:**
- [The General-Purpose API](https://samnewman.io/patterns/architectural/bff/)
- [The Logic-Heavy BFF (ThoughtWorks Radar)](https://www.thoughtworks.com/radar/techniques/logic-heavy-bff)
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest the BFF pattern is in use):
- `bff/` — dedicated BFF root directory
- `bff/web/`, `bff/mobile/`, `bff/tv/` — client-specific BFF instances
- `bff/*/api/` — client-specific endpoint definitions
- `bff/*/mappers/` — response aggregation and client-specific transformation logic
- `bff/*/clients/` — downstream service proxies scoped to a client type

### File signals
Strong indicators (any 1 is significant):
- Files named `*BffController.*`, `*BffService.*`, or `*BffRouter.*`
- Aggregation files that combine multiple upstream service responses for a single client type
- Client-specific DTO or response model files (e.g. `*MobileResponse.*`, `*WebResponse.*`, `*TvPayload.*`)

### Anti-signals
Suggest the BFF pattern is NOT in use:
- Single API layer serving all client types from the same endpoints with no client differentiation
- No client-specific response shaping, aggregation, or transformation layer
- No `bff/` directory or client-differentiated backend structure
