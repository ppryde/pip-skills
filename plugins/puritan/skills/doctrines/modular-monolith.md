# Modular Monolith Architecture Doctrine

The Modular Monolith doctrine enforces strict logical isolation within a single deployment unit. It aims to provide the organizational benefits of microservices (team autonomy, clear boundaries) without the "distributed systems tax" of network latency and extreme operational complexity.

**Language Scope:** Language-agnostic

## When to Use

This pattern is the "Goldilocks" choice for systems with high domain complexity but moderate scale. Use it when the team is large enough to require independent workstreams but the infrastructure budget does not yet justify a fleet of microservices. It is the ideal "Starting Point" to prevent a codebase from becoming a "Big Ball of Mud."

**Do NOT use this pattern** if different modules require radically different execution environments or if the application requires "Scale-to-Zero" capabilities for specific sub-components (use **microservices.md**).

## Why Use It

* **Logical Decoupling** — Clearly defined boundaries allow developers to reason about a single business capability at a time.
* **Refactoring Safety** — Since all modules reside in one process, the compiler/IDE can verify boundary integrity and type safety.
* **Operational Simplicity** — Single database, single deployment pipeline, and unified monitoring.
* **Strategic Flexibility** — A well-implemented modular monolith can be easily decomposed into microservices later because the boundaries are already enforced.

## Pros and Cons

| Pros | Cons |
|---|---|
| Low operational overhead; single deployment unit and single database. | Lack of physical isolation; a memory leak in one module crashes the entire process. |
| Strong type safety and compile-time checking across all module boundaries. | Risk of "hidden coupling" through shared database tables if not strictly audited. |
| Near-zero network latency for inter-module communication compared to REST/gRPC. | Deployment is all-or-nothing; you cannot patch a single module without restarting the app. |
| Supports atomic transactions across modules (facilitates data consistency). | Technology lock-in; the entire system must typically share the same runtime/language. |
| Simplifies local development; developers can run the entire system on one machine. | Boundary erosion is easy to ignore without automated enforcement (Inquisition). |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `modules/` — Root directory for functional modules (e.g., `modules/billing/`).
- `modules/*/api/` — The public interface; the ONLY folder accessible to other modules.
- `modules/*/internal/` — Private implementation, domain logic, and persistence logic.
- `modules/*/db/` — Module-specific database migrations and schema definitions.
- `platform/` — Shared infrastructure, logging, and common technical utilities.

## Violation Catalog

### Boundary & Encapsulation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-001 | internal-leak | Modules must not import from another module's internal folder | error | `import <pkg>.modules.moduleA.internal` in `modules/moduleB/` |
| MOM-002 | api-bypass | All inter-module calls must go through the designated API package | error | `import` of any non-API class or interface from a sibling module |
| MOM-003 | circular-module-dep | Circular dependencies between functional modules are forbidden | error | Module A depends on Module B, and Module B depends on Module A |
| MOM-004 | shared-domain-leak | Modules must not share internal domain entities or value objects | warning | `modules/moduleA/internal` using a domain class defined in `modules/moduleB/internal` |
| MOM-005 | deep-nesting | Functional modules should not be nested within other modules | warning | Directory structure exceeding `modules/<name>/<layer>` (e.g., `modules/a/b/c`) |

### Data Isolation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-006 | cross-module-join | Modules must not perform SQL joins across module boundaries | error | SQL queries in `modules/moduleA` joining tables owned by `modules/moduleB` |
| MOM-007 | shared-table | No database table should be modified by more than one module | error | Write/Update operations on `table_x` occurring in multiple module directories |
| MOM-008 | foreign-key-leak | Hard foreign keys across module boundaries should be avoided | warning | Database schema in `moduleA` defining a `FOREIGN KEY` to a table in `moduleB` |
| MOM-009 | direct-repo-access | A module must not use another module's Persistence/DAO layer | error | `modules/moduleA` instantiating or injecting a Repository from `modules/moduleB` |
| MOM-010 | transaction-bypass | Use local module transactions instead of global monolith transactions | warning | Cross-module calls that assume an open transaction from the caller |

### Communication & Event Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-011 | excessive-sync-calls | Prefer internal events over synchronous calls for side effects | warning | Synchronous API call in `moduleA` that triggers a heavy write in `moduleB` |
| MOM-012 | missing-event-contract | Inter-module events must use shared DTOs, not internal types | error | Modules publishing events containing classes from their `internal/` package |
| MOM-013 | event-loop | Modules should not create infinite event loops | error | Module A publishes E1 -> Module B receives and publishes E2 -> Module A receives |
| MOM-014 | synchronous-coupling | Module startup must not be blocked by other modules | warning | A module's `init()` or `start()` method waiting for a response from another module |
| MOM-015 | blocking-event-bus | Event subscribers should not block the main event bus | error | Event handlers in `internal/` performing heavy IO without async wrappers |

### Platform, Shared Logic & Lifecycle Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-016 | platform-logic-leak | Business logic must not reside in the platform directory | error | `platform/` containing domain-specific rules (e.g., `calculateVAT`) |
| MOM-017 | platform-dependency | Platform code must not depend on functional modules | error | `import <pkg>.modules` in any `platform/` file |
| MOM-018 | utility-overuse | Avoid "Common" modules that become a dumping ground | warning | `platform/common` or `modules/shared` exceeding 2000 lines of code |
| MOM-019 | transitive-dependency | Modules must not rely on transitive dependencies from the platform | warning | A module using a library provided implicitly by a platform dependency |
| MOM-020 | platform-bloat | Platform layer must not exceed 20% of the total codebase size | warning | Codebase-wide LOC check: `platform/` vs total project LOC |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-021 | cross-module-di | Modules must not inject internal classes from other modules | error | Dependency Injection of a class from `modules/moduleB/internal` into `moduleA` |
| MOM-022 | missing-interface-binding | API services should be requested by interface, not implementation | warning | `moduleA` injecting `ModuleBServiceImpl` instead of `IModuleBService` |
| MOM-023 | hidden-initialization | Modules must have a clear entry point for lifecycle management | warning | Modules using "magic" static initializers instead of an explicit `onStart()` hook |
| MOM-024 | circular-init | Module initialization must be acyclic | error | Constructor chains that lead back to the same module during startup |
| MOM-025 | missing-graceful-shutdown | Modules must implement a cleanup/shutdown hook | warning | Modules holding resources (sockets/files) without an `onStop()` implementation |

### Resource Governance & Concurrency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-026 | thread-monopoly | A module must not spawn unmanaged threads | error | Usage of `new Thread()` or `Executors` outside of the `platform/` managed pool |
| MOM-027 | memory-hog | Large objects (>100MB) must be cleared or managed in a specific module scope | warning | In-memory caches in `internal/` folders that do not have an eviction policy |
| MOM-028 | connection-leak | Modules must use namespaced connection pools | warning | A single module opening > 50 concurrent DB connections without explicit config |
| MOM-029 | unconstrained-io | Filesystem access must be scoped to a module-specific directory | error | `modules/moduleA` writing to a path used by `modules/moduleB` |
| MOM-030 | compute-monopoly | Background tasks must be priority-labeled per module | warning | Usage of high-priority scheduler flags for non-critical module tasks |

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-031 | static-state-leak | Modules must not store request data in static variables | error | Usage of `static` fields to hold domain data, causing leaks between module calls |
| MOM-032 | mutable-dto | DTOs passed between modules must be immutable | warning | Classes in `modules/*/api/` containing setter methods or mutable collections |
| MOM-033 | unprotected-concurrency | Shared module services must be thread-safe | error | Non-final instance variables in `internal/` services modified after initialization |

### Testing & Verification Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-034 | module-test-leak | Tests for Module A must not depend on the internals of Module B | error | `modules/moduleA/tests` importing from `modules/moduleB/internal` |
| MOM-035 | missing-module-isolation | Unit tests should be executable per module | warning | Inability to run tests for a single folder in `modules/` in isolation |
| MOM-036 | deep-stubbing | Do not stub the internal logic of other modules | warning | Tests in Module A using deep mocks for private methods in Module B |
| MOM-037 | missing-api-tests | Every public API class must have a corresponding contract test | warning | Classes in `modules/*/api/` with 0 test coverage in the `tests/` folder |
| MOM-038 | integration-flakiness | Integration tests must not depend on global shared state | error | Tests that fail if run in parallel due to database state clashes between modules |

### Observability, Deployment & Hygiene Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-039 | anonymous-logs | Every log statement must include the originating module name | error | Log calls that do not include a module context or tag (e.g., `[Billing] ...`) |
| MOM-040 | hidden-exceptions | Cross-module exceptions must be wrapped with module context | warning | Module A throwing a generic error that hides the fact it originated in Module B |
| MOM-041 | missing-module-metrics | Each module must expose independent success/failure metrics | error | Global "Total Errors" metric without breakdown by module folder |
| MOM-042 | trace-bypass | Cross-module calls must maintain a single trace ID | warning | Calls to Module API that do not propagate the current `Correlation-ID` |
| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MOM-043 | global-config-clash | Modules must use namespaced configuration keys | error | Use of generic config keys like `db.url` instead of `modules.ordering.db.url` |
| MOM-044 | feature-flag-bypass | New modules must be toggleable via feature flags | warning | Module registration code that cannot be disabled without a code change |
| MOM-045 | dead-module | Unused modules should be removed or archived | warning | Module directories with no incoming references or entry points |
| MOM-046 | bypass-validation | Cross-module calls must not bypass input validation | error | Module B calling Module A's API with raw, unvalidated data structures |
| MOM-047 | monolithic-build | Build scripts must allow for incremental compilation of modules | warning | A single file change in `modules/A` triggering a full re-compile of all modules |
| MOM-048 | manual-migration | Database migrations must be automated per module | error | Presence of SQL scripts in `modules/*/db/` not managed by a migration tool |
| MOM-049 | leaked-test-code | Test utilities must not be included in production module builds | error | `import <pkg>.modules.moduleA.tests` found in `internal/` code |
| MOM-050 | version-drift | All modules must share the same version of platform dependencies | error | Module A using `Spring v5` while Module B uses `Spring v6` in the same binary |

## Allowed Exceptions

- **Read-Only Projections:** A module may read from a "Shared View" database table owned by another module for performance, provided it is read-only and documented.
- **Legacy Migration:** During a "Strangler Fig" migration, boundary breaches are allowed if marked with `@Deprecated` and a ticket reference.
- **Global Auth:** The `platform/` layer is permitted to handle session state used by all modules.

## Cross-Reference

This doctrine pairs well with:
- **ddd.md** — Essential for defining the Bounded Contexts that become module boundaries.
- **cqrs.md** — Used within a module to separate read-only projections from command logic.
- **messaging.md** — Governing the internal event-bus used for cross-module side effects.
- **hexagonal.md** — Ensuring the `internal/` folder remains decoupled from infrastructure.

## Sources and Authority

**Foundational Works:**
- [Simon Brown - Modular Monoliths (2018)](https://structurizr.com/help/modularity)
- [Sam Newman - Monolith to Microservices (2021)](https://samnewman.io/books/monolith-to-microservices/)

**Practitioner Guidance:**
- [Shopify Engineering - Deconstructing the Monolith](https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity)
- [Kamil Grzybek - Modular Monolith with .NET](https://github.com/kgrzybek/modular-monolith-with-dotnet)

**Anti-Patterns / Failure Cases:**
- [The Big Ball of Mud](http://www.laputan.org/mud/)
- [The Distributed Monolith](https://microservices.io/antipatterns/distributed-monolith.html)