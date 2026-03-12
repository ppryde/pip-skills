# Resilience & Fault Tolerance Doctrine

The Resilience doctrine enforces patterns that ensure a system remains functional (perhaps in a degraded state) despite the inevitable failure of its components, network, or downstream dependencies. It aims to prevent cascading failures that turn a minor service hiccup into a total system outage.

**Language Scope:** Language-agnostic

## When to Use

Resilience patterns must be applied to any system involving network boundaries, such as **microservices.md**, **backend-for-frontend.md**, or even a **layered-n-tier.md** monolith that communicates with external APIs. It is critical for systems with strict Availability SLAs and high-concurrency environments where failures can rapidly deplete shared resources.

**Do NOT use this pattern** in purely local, single-process CLI tools or simple batch scripts where failing fast and exiting is the desired behavior.

## Why Use It

* **Stability Under Stress** — Prevents a single slow dependency from backing up your entire thread pool and crashing your service.
* **Graceful Degradation** — Allows the system to return "good enough" data (e.g., cached results) when the "perfect" data source is offline.
* **Self-Healing** — Patterns like Circuit Breakers allow systems to automatically recover once a failing dependency stabilizes.
* **Blast Radius Reduction** — Isolates failures to a single module or service using bulkheads.

## Pros and Cons

| Pros | Cons |
|---|---|
| Protects the system from "death by a thousand timeouts" and resource exhaustion. | Significantly increases code complexity and testing requirements. |
| Improves user experience by providing fallbacks instead of generic error pages. | Improperly configured retries can worsen an outage (Retry Storms). |
| Provides deep visibility into the health of downstream dependencies. | Can lead to "stale data" bugs if fallbacks are not carefully managed. |
| Eliminates the need for manual intervention during transient network blips. | Adds latency to the "happy path" due to proxying and monitoring overhead. |
| Ensures "fail-fast" behavior, which is easier to debug than "slow-hang" behavior. | Debugging a "degraded" system can be harder than debugging a crashed one. |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `infrastructure/resilience/` — Global resilience configurations and policies.
- `clients/` or `gateways/` — Outgoing network calls that require protection.
- `bff/*/clients/` — Downstream service proxies in the BFF layer.
- `services/*/integration/` — Integration points within microservices.

## Violation Catalog

### Timeouts & Circuit Breakers Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-001 | missing-timeout | Every network call must have an explicit timeout | error | HTTP/gRPC/DB client calls without a timeout configuration |
| RES-002 | infinite-wait | Blocking calls must not wait indefinitely for a response | error | Usage of default "infinite" or `-1` timeout values in library configs |
| RES-003 | excessive-timeout | Timeouts should not exceed the user's patience threshold | warning | Timeouts configured for > 5s on user-facing request paths |
| RES-004 | missing-deadline | Propagate deadlines across service boundaries | warning | Lack of `context.WithDeadline` or `X-Request-Deadline` propagation |
| RES-005 | static-timeout | Use dynamic timeouts based on remaining request budget | warning | Hardcoded `500ms` timeout when the total request budget is variable |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-006 | missing-breaker | All external service calls must be wrapped in a circuit breaker | error | Network client calls missing a breaker decorator/wrapper |
| RES-007 | misconfigured-threshold | Breakers must have a defined failure rate threshold | warning | Circuit breaker settings with `failureRateThreshold` > 50% |
| RES-008 | sticky-open-breaker | Breakers must define an automatic transition to half-open state | error | Lack of `waitDurationInOpenState` or equivalent config |
| RES-009 | missing-health-integration | Breaker state must influence service health status | warning | `/health` returning `UP` when critical path breakers are `OPEN` |
| RES-010 | slow-call-breaker | Circuit breakers must also trigger on slow calls, not just errors | warning | Lack of `slowCallRateThreshold` in breaker configurations |

### Retry & Backoff Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-011 | retry-storm | Retries must implement exponential backoff and jitter | error | Retry logic using constant intervals (e.g., `sleep(1s)`) without randomization |
| RES-012 | infinite-retries | Retries must have a maximum attempt limit | error | Recursive or loop-based retries without a counter (max 3 recommended) |
| RES-013 | side-effect-retry | Do not retry non-idempotent operations (POST/PATCH) | error | Retry logic wrapping non-GET/non-HEAD requests without idempotency keys |
| RES-014 | shallow-retries | Do not retry on 4xx Client Errors | warning | Retries triggering for `401 Unauthorized` or `404 Not Found` |
| RES-015 | hidden-retries | Avoid nested retries (Library Retry + Application Retry) | warning | Both the HTTP library and the application logic having retry policies enabled |

### Bulkhead & Resource Isolation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-016 | shared-thread-pool | Distinct dependencies must use separate thread pools | warning | Multiple `clients/` sharing one global thread pool/executor |
| RES-017 | missing-bulkhead | Limit concurrent calls to any single dependency | error | Lack of semaphores or pool size limits on outgoing client calls |
| RES-018 | resource-exhaustion | Resilience wrappers must be registered as singletons | warning | Dynamic creation of breakers/retries per-request causing memory leaks |
| RES-019 | unconstrained-queues | Bulkhead queues must have a maximum capacity | error | Usage of unbounded queues (e.g., `LinkedBlockingQueue` without size) |
| RES-020 | shared-circuit-breaker | Do not share a single circuit breaker across different service endpoints | error | One breaker instance guarding multiple unrelated external APIs |

### Fallback & Degradation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-021 | missing-fallback | Every circuit breaker must have a defined fallback action | error | Breakers without a `recover` or `fallback` method |
| RES-022 | opaque-fallback | Fallbacks should indicate that the data is degraded | warning | Fallbacks returning "empty" data without a `degraded: true` flag |
| RES-023 | recursion-in-fallback | Fallbacks must not trigger secondary unprotected network calls | error | A fallback method that makes its own unprotected network call |
| RES-024 | fallback-logic-leak | Do not put complex business logic in fallback methods | warning | Fallbacks exceeding 10 lines of code or performing complex calculations |
| RES-025 | fallback-failure-loop | Fallback methods must be guaranteed to succeed or fail-fast | error | Fallback logic that itself contains nested retry loops or complex IO |

### Load Shedding & Self-Preservation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-026 | missing-load-shedding | Services must drop requests when overloaded | warning | Lack of an "Active Request Limit" or "Admission Control" middleware |
| RES-027 | queue-clogging | Use LIFO or Priority queues when shedding load | warning | Standard FIFO queues that keep "old" requests during a spike |
| RES-028 | expensive-health-check | Health checks must be lightweight and non-blocking | error | `/health` endpoints that perform deep DB queries or external API calls |
| RES-029 | startup-deadlock | Do not wait for all dependencies before starting the app | warning | Blocking the `main()` thread until a DB or Cache is available |
| RES-030 | missing-backpressure | Propagate backpressure signals to the caller | error | Catching overload errors and returning generic `500` instead of `503 Service Unavailable` |

### Observability & Stale-Data Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-031 | silent-recovery | State changes in circuit breakers must be logged | warning | Breaker transitions (`CLOSED` -> `OPEN`) without a log or event |
| RES-032 | missing-chaos-test | High-traffic integration points must be chaos-tested | warning | Lack of `Toxiproxy` or `Chaos Mesh` experiments in CI/CD |
| RES-033 | invisible-retries | Retries must be incrementing a specific metric | error | Retrying without incrementing a `service_retries_total` counter |
| RES-034 | opaque-latency | Measure latency *with* and *without* resilience overhead | warning | Only measuring final response time, ignoring time spent in retries |
| RES-035 | missing-fallback-alert | Frequent fallback triggering must trigger an alert | warning | Lack of an alert for `fallback_calls_total` exceeding a threshold |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-036 | cache-as-fallback-only | Do not use cache-as-fallback for sensitive real-time data | error | Returning cached "Balance" or "Stock Level" during a service outage |
| RES-037 | missing-ttl-on-fallback | Fallback data must have a strict Time-To-Live | warning | Serving fallback data that hasn't been refreshed in over 24 hours |
| RES-038 | cache-stampede-protection | Use "Singleflight" or "Coalescing" for cache misses | warning | Multiple threads hitting the same DB record simultaneously on a cache miss |

### Control Plane, Configuration & Lifecycle Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-039 | hardcoded-resilience | Resilience parameters must be configurable at runtime | error | Hardcoded `failureRateThreshold: 0.5` inside the source code |
| RES-040 | missing-dry-run | Large resilience changes should be deployable in "Audit" mode | warning | Lack of a `force_open` or `dry_run` flag in the breaker configuration |
| RES-041 | configuration-dependency | Resilience config must not depend on a failing remote config server | error | Service failing to start its resilience layer because it can't fetch remote config |
| RES-042 | shared-secrets-in-resilience | Resilience logs must not contain authentication headers | error | Logging the raw downstream request/response when it contains `Authorization` tokens |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| RES-043 | static-state-in-resilience | Resilience policies must be stateless regarding user data | error | Storing user-specific data in a shared `Retry` or `CircuitBreaker` instance |
| RES-044 | unmanaged-goroutines | Background tasks must use a lifecycle-aware pool | error | Usage of `go func()` or `Thread.start()` for background resilience tasks |
| RES-045 | context-leak | Ensure contexts are passed to all async resilience tasks | error | Start of a background task that doesn't listen for parent shutdown |
| RES-046 | blocking-event-loop | Resilience logic must not block the main event loop | error | Synchronous `Thread.sleep()` in an async framework (Node.js/Netty) |
| RES-047 | excessive-concurrency | Limit the number of background retries to prevent OOM | warning | Lack of a global limit on the number of concurrently running retry workers |
| RES-048 | missing-graceful-drain | Wait for resilience tasks to complete before shutdown | warning | Service exiting immediately without letting retries finish their "last attempt" |
| RES-049 | dependency-cycle-resilience | Do not create a resilience dependency on a service you are protecting | error | A circuit breaker that calls a logging service which itself is behind that same breaker |
| RES-050 | orphaned-resilience | Ensure every resilience policy is actually attached to a client | warning | Definition of a `CircuitBreaker` or `Retry` policy that is never used in code |

## Allowed Exceptions

- **Idempotent Background Jobs:** Simple retry-until-success is allowed for workers that don't block user requests.
- **Local Dev Environments:** Resilience can be bypassed in `development` to see raw error traces.
- **Critical Auth Logic:** Loading a local public key for JWT validation may bypass breakers to prevent a "locked out" state.

## Cross-Reference

- **microservices.md** — Protecting the service mesh from cascading death.
- **backend-for-frontend.md** — Ensuring the UI remains responsive even when the backend is struggling.
- **messaging.md** — Asynchronous communication as a primary resilience strategy.
- **layered-n-tier.md** — Protecting the domain logic from slow database drivers.

## Sources and Authority

**Foundational Works:**
- [Michael Nygard - Release It! (2018)](https://www.oreilly.com/library/view/release-it-2nd/9781680504552/)
- [Google - SRE Book: Handling Overload](https://sre.google/sre-book/handling-overload/)

**Practitioner Guidance:**
- [Polly / Resilience4j Documentation](https://resilience4j.readme.io/)
- [Netflix - Fault Tolerance in a High Volume Environment](https://netflixtechblog.com/fault-tolerance-in-a-high-volume-distributed-system-91ab4fa2a468)

**Anti-Patterns / Failure Cases:**
- [The Retry Storm (Wikipedia)](https://en.wikipedia.org/wiki/Retry_storm)
- [AWS S3 Outage Case Study](https://aws.amazon.com/message/41922/)
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest Resilience patterns are in use):
- `infrastructure/resilience/` — global resilience policy configuration
- `clients/resilience/` or `gateways/resilience/` — per-client resilience wrapping
- `services/*/integration/` — microservice integration points with external dependencies

### File signals
Strong indicators (any 1 is significant):
- Files named `*CircuitBreaker.*`, `*RetryPolicy.*`, or `*Bulkhead.*`
- Files named `*Timeout.*` or `*RateLimiter.*` in infrastructure or client directories
- Resilience library configuration: `resilience4j.yml`, `polly_config.*`, `pybreaker_config.*`, `hystrix.yml`
- Files named `*FallbackHandler.*` or `*FallbackStrategy.*`

### Anti-signals
Suggest Resilience patterns are NOT in use:
- Direct HTTP or network calls with no retry, circuit breaker, or timeout wrapping
- No resilience policy, configuration, or strategy files anywhere in the project
- Error handling limited to basic try/catch with no structured retry or fallback logic
