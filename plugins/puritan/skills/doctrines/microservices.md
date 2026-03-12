# Microservices Architecture Doctrine

The Microservices Architecture doctrine enforces the decentralization of data, logic, and deployments. It ensures that services remain loosely coupled and independently scalable, preventing the formation of a "distributed monolith" where changes in one service require synchronized deployments across the entire fleet.

**Language Scope:** Language-agnostic

## When to Use

Microservices should be used for large-scale, complex systems where multiple independent teams need to deliver features at different velocities. It is appropriate when different parts of an application have vastly different scaling requirements (e.g., a high-traffic ingest service vs. a low-traffic reporting service).

**Do NOT use this pattern** for small teams (under 3-4 teams), early-stage startups searching for product-market fit, or applications where the overhead of network latency and distributed consistency outweighs the benefits of independent scaling. For these cases, refer to the **modular-monolith.md** doctrine.

## Why Use It

* **Independent Deployability** — Services can be updated and deployed without affecting the rest of the system, enabling high-velocity CI/CD.
* **Technological Freedom** — Teams can choose the best stack (language, database, framework) for their specific service's requirements.
* **Fault Isolation** — A failure in one service (e.g., a memory leak or crash) can be contained, preventing a total system outage.
* **Granular Scalability** — Resources can be allocated precisely to the services that need them most, optimizing cloud infrastructure costs.

## Pros and Cons

| Pros | Cons |
|---|---|
| Enables massive organizational scaling by decoupling development teams. | Significant operational complexity (service discovery, tracing, logging). |
| High resilience; failures are localized to specific business capabilities. | Harder to maintain data consistency without distributed transactions. |
| Improved agility; faster lead time for specialized service updates. | Network latency and "chitchat" overhead can impact performance. |
| Eliminates long-term commitment to a single technology stack. | Operational "distributed monolith" risk if boundaries are poorly defined. |
| Easier to understand individual services compared to a massive monolith. | Testing requires complex integration environments and contract tests. |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `services/` — Independent service root directories.
- `infrastructure/` — Global provisioning, mesh configuration, and CI/CD templates.
- `shared-libraries/` — Cross-cutting utilities (strictly governed).
- `contracts/` — Shared API definitions (OpenAPI/Proto) to prevent drift.

## Violation Catalog

### Service Boundary, Data Sovereignty & Consistency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-001 | data-sovereignty | Services must not share a database schema | error | Multiple services in `services/` connecting to the same DB schema/catalog |
| MCR-002 | direct-domain-access | Services must not import domain logic from other services | error | `import <pkg>.services.serviceA.domain` in `services/serviceB/` |
| MCR-003 | shared-state | Services must not share mutable global state | error | Hardcoded shared keys or global caches accessed by multiple service roots |
| MCR-004 | circular-dependency | Circular synchronous dependencies between services are forbidden | error | Service A calls B via API, and Service B calls A via API |
| MCR-005 | leaky-persistence | Internal DB primary keys must not be exposed in public APIs | warning | Entity ID fields (UUID/Serial) from `data/` used directly in `api/` responses |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-026 | distributed-transaction | Do not use cross-service atomic locks or 2PC | error | Usage of JTA, XA transactions, or cross-service mutexes |
| MCR-027 | missing-compensation | Async operations must have compensation actions | error | Event listeners without a failure-handling/rollback path |
| MCR-028 | ghost-writes | Ensure idempotency for all event consumers | error | Event handlers that perform writes without checking duplicate message IDs |
| MCR-029 | dual-write | Do not write to DB and Broker in one local transaction | warning | Logic calling `db.save()` and `broker.publish()` sequentially |
| MCR-030 | outbox-bypass | Use Outbox pattern for guaranteed message delivery | warning | Direct publishing to broker from business logic instead of Outbox table |

### Communication & API Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-006 | synchronous-chaining | Avoid deep chains of synchronous HTTP/gRPC calls | warning | Service call depth > 3 in a single request trace (e.g., A -> B -> C -> D) |
| MCR-007 | missing-contract | API changes must be governed by explicit versioning | error | Breaking changes to `api/` definitions without a version increment |
| MCR-008 | hardcoded-endpoints | Service locations must not be hardcoded | error | IP addresses or static DNS names for other services in configuration files |
| MCR-009 | client-library-leak | Service client libraries must not leak internal models | warning | Client SDKs in `shared-libraries/` exposing internal DB entities |
| MCR-010 | untyped-payloads | Inter-service communication must use structured schemas | error | Use of `JSON.parse` or generic Maps for API payloads without schema validation |

### Shared Code & Dependency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-011 | logic-in-shared | Business logic must not reside in shared libraries | error | `shared-libraries/` containing domain-specific validation or logic |
| MCR-012 | shared-lib-bloat | Shared libraries must be versioned and kept lean | warning | `shared-libraries/` exceeding 1000 LOC or including heavy dependencies |
| MCR-013 | version-lock | Services must not be forced into a single global library version | warning | Root-level build files enforcing one version for all `services/` |
| MCR-014 | transitive-leak | Shared libraries must not expose transitive deps to services | error | Services relying on a library provided implicitly by a shared parent |
| MCR-015 | binary-coupling | Avoid sharing compiled DTOs across services | warning | Services sharing a `.jar` or `.dll` containing data transfer objects |

### Resilience & Performance Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-016 | missing-timeout | Every inter-service call must have an explicit timeout | error | HTTP/gRPC client instantiations without a defined timeout duration |
| MCR-017 | missing-circuit-breaker | External service calls must be wrapped in circuit breakers | error | Inter-service calls lacking a circuit-breaker implementation |
| MCR-018 | chatty-api | Avoid fine-grained calls where one aggregate call suffices | warning | Loop constructs making repeated API calls to another service |
| MCR-019 | blocking-io | Prefer async communication for non-query operations | warning | Synchronous POST/PUT calls where an event-driven approach is viable |
| MCR-020 | retry-storm | Retries must implement exponential backoff and jitter | error | Retry logic with constant intervals (e.g., `retry(3, 1000ms)`) |

### Observability & Standards Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-021 | missing-trace-id | Correlation IDs must be propagated through all calls | error | API handlers in `services/*/api/` not forwarding `X-Correlation-ID` |
| MCR-022 | inconsistent-logging | Services must use a standardized structured logging format | warning | Log statements not using the approved JSON schema |
| MCR-023 | missing-health-check | Every service must expose a `/health` or `/ready` endpoint | error | Absence of standard health check route in the service's API |
| MCR-024 | opaque-failures | Services must return standard error codes (RFC 7807) | warning | Non-standard or generic `500` errors without diagnostic context |
| MCR-025 | missing-metrics | Services must expose standard golden signals (Rate/Errors/Dur) | error | Lack of Prometheus/Metrics endpoints in service initialization |

### Configuration & Environment Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-031 | secrets-in-code | Secrets must never be stored in source code | error | Presence of `API_KEY` or `SECRET` strings in `services/` files |
| MCR-032 | environment-pollution | Services must not rely on host-specific env vars | error | Hardcoded references to local machine paths or developer env vars |
| MCR-033 | config-drift | Configurations must be versioned alongside code | error | Services relying on unversioned external config stores (e.g., raw Etcd keys) |
| MCR-034 | missing-default-config | Every service must provide a safe `local` config | warning | Service failure to start without a connection to a remote config server |

### Deployment & Infrastructure Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-035 | manual-deployment | Services must have an automated CI/CD pipeline | error | Absence of `Jenkinsfile`, `.github/workflows`, or `gitlab-ci.yml` |
| MCR-036 | static-scaling | Services should not have hardcoded instance counts | warning | Deployment manifests with fixed `replicas: X` instead of HPA |
| MCR-037 | stateful-service | Services should be stateless for horizontal scaling | error | Usage of local file system or in-memory sessions for persistence |
| MCR-038 | unconstrained-resources | Manifests must define CPU/Memory limits | error | Manifests without `resources.limits` or `resources.requests` |
| MCR-039 | hardcoded-image-tags | Deployment manifests must not use `latest` tags | error | Usage of `image: my-service:latest` in deployment files |
| MCR-040 | sidecar-bypass | Services must use the designated service mesh for egress | warning | Direct socket calls bypassing the local mesh proxy (if configured) |

### Testing & Verification Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MCR-041 | missing-contract-tests | Inter-service APIs must be covered by contract tests | error | Lack of Pact or Spring Cloud Contract files in `services/*/tests/` |
| MCR-042 | slow-tests | Service unit tests must not exceed 5-minute execution | warning | Local test suites taking > 300s to complete |
| MCR-043 | fragile-integration | Integration tests should not depend on "live" dependencies | error | Tests in `services/` requiring a connection to a real Production/Staging DB |
| MCR-044 | missing-load-test | High-traffic services must have defined load test scripts | warning | Absence of `k6`, `Gatling`, or `JMeter` scripts for ingest services |
| MCR-045 | shadow-deployment-lacking | Major API changes must support canary or shadow traffic | warning | Lack of feature flags or traffic routing rules for new major versions |

## Allowed Exceptions

- **Infrastructure Services:** Logging agents, mesh proxies, and storage drivers are exempt from statelessness rules.
- **Legacy Bridges:** Temporary direct DB access is allowed during a monolith-to-microservice migration, provided it is marked with a `TTL` comment.
- **Shared Kernel:** Low-level primitives in `shared-libraries/` are permitted.

## Cross-Reference

- **messaging.md** — Async communication and outbox patterns.
- **saga.md** — Managing distributed consistency via compensation.
- **cqrs.md** — Separating read and write models within services.
- **ddd.md** — Defining Bounded Contexts as service boundaries.

## Sources and Authority

**Foundational Works:**
- [Sam Newman - Building Microservices (2015)](https://samnewman.io/books/building_microservices/)
- [Chris Richardson - Microservices Patterns (2018)](https://microservices.io/book)

**Practitioner Guidance:**
- [Martin Fowler - Microservices Guide](https://martinfowler.com/microservices/)
- [Netflix Technology Blog](https://netflixtechblog.com/)

**Anti-Patterns / Failure Cases:**
- [The Distributed Monolith](https://www.geepawhill.org/2019/06/17/microservices-the-distributed-monolith/)
- [Segment - Goodbye Microservices (2018)](https://segment.com/blog/goodbye-microservices/)
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest a Microservices architecture is in use):
- `services/` containing multiple distinct named subdirectories (e.g. `services/orders/`, `services/payments/`)
- Multiple top-level service directories each containing their own `Dockerfile`
- `contracts/` or `api-specs/` — shared API definitions between services
- `shared-libraries/` or `libs/` — cross-service shared utilities under strict governance
- `infrastructure/` at the monorepo root — shared provisioning, service mesh config, CI templates

### File signals
Strong indicators (any 1 is significant):
- `docker-compose.yml` at the root defining 3 or more independently named services
- Per-service `Dockerfile` inside multiple directories at the same level
- OpenAPI or Proto contract files (`*.proto`, `*.openapi.yml`, `*.swagger.json`) in a shared `contracts/` directory
- Service mesh config files: `istio.yml`, `envoy.yaml`, `linkerd-config.yml`

### Anti-signals
Suggest Microservices are NOT in use:
- Single `Dockerfile` at the project root serving the entire application
- All business logic in a single `src/` or `app/` directory
- No inter-service contract definitions or shared API specs
- No independent deployment manifests per service
