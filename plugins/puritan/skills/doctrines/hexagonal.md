# Hexagonal Architecture Doctrine

Hexagonal Architecture (Ports and Adapters) decouples core business logic from external concerns like databases, UIs, and third-party APIs. By treating the application as a central "inside" surrounded by an "outside," it ensures business rules remain testable in isolation and resilient to infrastructure evolution.

## When to Use

Use Hexagonal Architecture for mid-to-high complexity systems where the business logic is the primary asset and infrastructure (DBs, message brokers, external APIs) is likely to evolve or change. It is ideal for teams practicing TDD and those requiring high degrees of testability without "mocking the world."

**Do NOT use it** for simple CRUD applications, thin wrappers around a single database, or "serverless-first" glue code where the overhead of defining interfaces outweighs the benefit of isolation.

## Why Use It

- **Infrastructure Independence** — Swap a SQL database for a Document store or an HTTP API for a gRPC interface without touching a line of domain logic.
- **Isolate Testability** — Test business use cases in milliseconds by providing "mock" or "in-memory" adapters instead of hitting real databases or networks.
- **Domain Purity** — Protects the core logic from "leaking" framework-specific or vendor-specific code, making the code easier to reason about for domain experts.
- **Parallel Development** — Enables front-end and back-end teams to work against stable "Ports" (interfaces) before the actual "Adapters" (implementations) are built.
- **Deferred Decisions** — Postpone choices about specific database vendors or delivery mechanisms until the domain requirements are fully understood.

## Pros and Cons

| Pros | Cons |
|---|---|
| Extreme testability; 100% logic coverage without IO | Significant boilerplate (many interfaces, DTOs, and mappers) |
| Zero vendor lock-in for the core application logic | Higher cognitive load and steeper learning curve for new developers |
| High maintainability as infrastructure changes over time | Overkill for simple applications ([Fowler: "beware risky complexity"](https://martinfowler.com/bliki/DesignStaminaHypothesis.html)) |
| Clean separation of concerns (Inside vs. Outside) | Potential performance overhead due to mapping layers |
| Consistent pattern for adding new delivery mechanisms | Risk of "Anemic Domain Model" if logic stays in adapters |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`).
Use relative paths without `src/` prefix (e.g. `domain/` not `src/domain/`):
- `domain/` — The "Inside." Pure business logic, entities, and value objects reside here.
- `application/` — Use case orchestration and the definition of Driving Ports.
- `infrastructure/` — The "Outside." Concrete Adapters (DB, Web, API) and implementation of Driven Ports.
- `ports/` — The boundary definitions (interfaces/contracts) between layers.

## Violation Catalog

### Dependency Direction Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| HEX-001 | dependency-direction | Domain layer must not import Infrastructure | error | `import .*infrastructure` pattern in `domain/` files |
| HEX-002 | dependency-direction | Application layer must not import Infrastructure | error | `import .*infrastructure` pattern in `application/` files |
| HEX-003 | dependency-direction | Domain layer must not import external frameworks | error | `import (fastapi\|django\|sqlalchemy\|pymongo\|flask)` in `domain/` |
| HEX-004 | dependency-direction | Ports must not import Infrastructure | error | `import .*infrastructure` pattern in `ports/` files |
| HEX-005 | dependency-direction | Core layers must not import test utilities | error | `import (pytest\|unittest\|mock)` in `domain/` or `application/` files |

**Scanning approach:** These rules are strictly enforced via import analysis. Any "inward-to-outward" dependency represents a fundamental breach of the architecture.

### Port & Boundary Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| HEX-010 | port-design | Ports must be defined as Interfaces or Abstract Classes | error | Files in `ports/` lacking `abc.ABC`, `Protocol`, or `Interface` definitions |
| HEX-011 | port-design | Application services must only interact with Ports | error | Class instantiations of `infrastructure` classes within `application/` |
| HEX-012 | port-design | Ports must use Domain Models or DTOs, never Infra Models | error | Port method signatures using types from `sqlalchemy`, `pydantic.BaseModel`, or ORM entities |
| HEX-013 | port-design | Ports must be named after capability, not implementation | warning | Port class names containing technology-specific words (e.g., `Sql`, `Mongo`, `Http`) |
| HEX-014 | port-design | Driven Ports must have at least one implementation | error | Port definition in `ports/` with no corresponding implementation in `infrastructure/` |

**Scanning approach:** Focus on the structural definition of the boundaries. Ports are the "contracts" and must remain implementation-agnostic.

### Adapter Implementation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| HEX-020 | adapter-boundary | Adapters must reside in the Infrastructure layer | error | Classes inheriting from `Port` or `Repository` found outside `infrastructure/` |
| HEX-021 | adapter-boundary | Adapters must not contain core business logic | error | Cyclomatic complexity > 10 in `infrastructure/` methods |
| HEX-022 | adapter-boundary | Infrastructure models must be mapped to Domain models | warning | Adapter method returning a third-party or ORM object directly to `application/` |
| HEX-023 | adapter-boundary | Adapters must not depend on other Adapters | warning | `import` of one sub-module in `infrastructure/` (e.g., `persistence`) by another (e.g., `web`) |
| HEX-024 | adapter-boundary | SQL or NoSQL queries must stay in Adapters | error | SQL strings, Query Builders, or Mongo selectors found outside `infrastructure/` |

**Scanning approach:** Check for "leakage" where infrastructure details or logic creep into the adapters or beyond.

### Domain & Application Purity Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| HEX-030 | core-purity | Domain Entities must not perform IO | error | Calls to `print`, `logging` (to file/network), or socket operations in `domain/` |
| HEX-031 | core-purity | Application services must be orchestration-focused | warning | Files in `application/` with > 400 lines of code |
| HEX-032 | core-purity | Domain logic must not leak into Controllers | error | If/Else logic or calculations found in `infrastructure/web/controllers` |
| HEX-033 | core-purity | Business logic must not be in Ports | error | Concrete method logic (non-abstract) inside `ports/` files |
| HEX-034 | core-purity | Use Cases must be atomic units of work | warning | `application/` methods calling more than 3 different Driven Ports |

**Scanning approach:** These rules protect the "brain" of the application from being cluttered by non-domain concerns.

### Mapping & Data Integrity Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| HEX-040 | mapping-integrity | Domain must not be aware of persistence IDs | warning | Use of database-generated `id` fields (auto-increment) as primary keys in `domain/` entities |
| HEX-041 | mapping-integrity | DTOs must be used for cross-boundary communication | error | Domain Entities used as request/response bodies in `infrastructure/api` |
| HEX-042 | mapping-integrity | Explicit mappers are required | warning | Direct attribute copying (`a.x = b.x`) in application services instead of using a Mapper class/function |

**Scanning approach:** Look for data leaks where internal state is exposed directly to the outside world.

## Allowed Exceptions

- **Standard Library:** Layers may import any language standard library module (e.g., `datetime`, `json`, `uuid`).
- **Shared Utilities:** A `common/` or `utils/` directory may be used by all layers, provided it contains zero business logic and zero infrastructure dependencies.
- **Pragmatic Logging:** Global logging abstractions (e.g., Python's `logging` module) are allowed in all layers to facilitate observability.
- **Framework DTOs:** Using Pydantic or similar for DTOs in the `application/` layer is permitted if the `domain/` remains independent of the framework.

## Cross-Reference

This doctrine pairs well with:
- **ddd.md** — Crucial for defining the internal structure of the `domain/` layer (Aggregates, Value Objects).
- **cqrs.md** — Used to separate read and write models at the Port level.
- **testing.md** — Validates that the "Inside" is tested purely with mocks/fakes.
- **resilience.md** — Handles failures in Driven Adapters (Retries, Circuit Breakers).
- **logging.md** — Standardizes how "Inside" events are captured without violating purity.

## Sources and Authority

**Foundational Works:**
- [Alistair Cockburn - Hexagonal Architecture (2005)](https://alistair.cockburn.us/hexagonal-architecture/) — The original definition and intent of the Ports and Adapters pattern.
- [Robert C. Martin - Clean Architecture (2012)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html) — Formalization of the concentric dependency rule.

**Practitioner Guidance:**
- [Netflix Tech Blog - Ready for changes with Hexagonal Architecture](https://netflixtechblog.com/ready-for-changes-with-hexagonal-architecture-b315ec967749) — Detailed practitioner view on implementing this at scale.
- [Herberto Graça - Ports & Adapters Architecture](https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/) — Comprehensive guide on layer interactions.

**Anti-Patterns / Failure Cases:**
- [Juan Manuel Garrido - Hexagonal Architecture: Common Mistakes](https://jmgarridopaz.github.io/static/articles/hexagonal-architecture/mistakes.html) — Case study on common implementation errors like "Adapters calling Adapters."

## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest Hexagonal Architecture is in use):
- `ports/` — port interface definitions (the boundary contracts)
- `adapters/` or `infrastructure/adapters/` — adapter implementations
- `domain/` — pure business logic isolated from infrastructure concerns
- `application/` — use case orchestration and driving port definitions
- `infrastructure/` alongside `domain/` with no direct coupling between them

### File signals
Strong indicators (any 1 is significant):
- Files named `*Port.*` defining interface contracts
- Files named `*Adapter.*` implementing those contracts
- Interface files in `ports/` with corresponding implementations in `adapters/` or `infrastructure/`
- Files named `*DrivingPort.*`, `*DrivenPort.*`, `*PrimaryPort.*`, or `*SecondaryPort.*`

### Anti-signals
Suggest Hexagonal Architecture is NOT in use:
- No `ports/` or `adapters/` directories anywhere in the codebase
- Infrastructure imports found directly inside `domain/` layer files
- No clear boundary between the application core and external systems
- Framework annotations (HTTP, ORM) mixed directly into domain classes
