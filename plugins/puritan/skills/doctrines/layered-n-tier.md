# Layered (N-Tier) Architecture Doctrine

The Layered (N-Tier) Architecture doctrine enforces strict horizontal separation of concerns. It ensures that changes in low-level details (like databases) do not leak into high-level business logic, and that user interface concerns remain isolated from data persistence.

## When to Use

Layered architecture is the standard choice for small to medium-sized applications where the primary goal is a clean, predictable structure that a team can understand quickly. It is ideal for CRUD-heavy applications and projects where the domain complexity does not yet justify the overhead of **ddd.md** or **hexagonal.md**.

**Do NOT use this pattern** if the application requires extreme scalability (use **microservices.md**), has highly complex lifecycle-based domain logic (use **ddd.md**), or requires multiple diverse delivery mechanisms for the same logic (use **hexagonal.md**).

## Why Use It

* **Simplicity and Familiarity** — It is the most widely understood pattern in software engineering, lowering the barrier for new contributors.
* **Separation of Concerns** — Each layer has a defined responsibility, making it easier to locate bugs and implement features.
* **Maintainability** — Changes to the UI or Database technology are isolated to their respective layers.
* **Testability** — Business logic can be tested in isolation by mocking the persistence layer.

## Pros and Cons

| Pros | Cons |
|---|---|
| Low cognitive overhead and easy for junior developers to grasp. | Prone to "Sinkhole Anti-pattern" where layers just pass calls through ([Fowler, 2015](https://martinfowler.com/articles/presentation-domain-data.html)). |
| Strict dependency rules prevent "spaghetti code" entanglements. | Tight coupling between layers can make the system rigid to change. |
| Clear mapping between the codebase and the deployment tiers. | High-level layers are transitively dependent on all layers below them. |
| Easy to implement standardized cross-cutting concerns (logging, auth). | Can lead to bloated "Service" classes that violate SRP. |
| Supports parallel development of UI and Backend via defined interfaces. | Does not handle complex asynchronous workflows well (see **messaging.md**). |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `presentation/` — UI components, controllers, view models, and API endpoints.
- `business/` — Domain services, business logic, and application rules.
- `persistence/` — Data Access Objects (DAOs), repositories, and ORM mapping.
- `database/` — Migrations, schemas, and stored procedures.
- `common/` — Shared utilities, constants, and cross-cutting helpers.

## Violation Catalog

### Layer Dependency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-001 | dependency-direction | Lower layers must not depend on higher layers | error | `import <pkg>.presentation` in `business/` or `persistence/` |
| LNT-002 | dependency-skip | Layers should not skip immediate neighbors | warning | `import <pkg>.persistence` directly in `presentation/` bypassing `business/` |
| LNT-003 | circular-dependency | Bi-directional dependencies between layers are forbidden | error | Circular import paths between `business/` and `persistence/` |
| LNT-004 | external-leak | Third-party UI or DB libraries must not leak into business logic | error | `import` of web frameworks (e.g., Express, Spring Web) or ORMs in `business/` |
| LNT-005 | direct-instantiation | Layers must not instantiate their own dependencies | warning | Usage of `new Service()` or `new Repository()` instead of Dependency Injection |

### Encapsulation & Boundary Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-006 | leaky-abstraction | Persistence-specific exceptions must not reach the presentation layer | error | `catch` blocks in `presentation/` handling `SQLException` or ORM-specific errors |
| LNT-007 | model-bleeding | Database entities must not be used as API responses | warning | Method signatures in `presentation/` controllers returning classes defined in `persistence/` |
| LNT-008 | logic-placement | Business logic must not reside in the presentation layer | error | `presentation/` files containing complex conditionals, math, or data transformation > 15 lines |
| LNT-009 | logic-displacement | Business logic must not reside in the persistence layer | error | `persistence/` classes containing non-query logic (e.g., tax calculation) |
| LNT-010 | direct-db-access | UI must not execute raw SQL or DB commands | error | SQL strings or DB client calls (e.g., `db.query()`) inside `presentation/` |
| LNT-011 | excessive-exposure | Internal service methods must be private or protected | warning | Public methods in `business/` that are not called by `presentation/` |

### Interface & Contract Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-012 | missing-abstraction | Business layer should access persistence via interfaces | warning | `business/` classes instantiating concrete `persistence/` classes instead of using DI |
| LNT-013 | contract-bypass | Business methods must be used instead of direct data manipulation | error | `presentation/` modifying objects and calling `persistence.save()` directly |
| LNT-014 | service-bloat | Business services should not exceed complexity thresholds | warning | Service classes in `business/` with > 10 public methods or > 500 lines of code |
| LNT-015 | utility-misplacement | Utilities in common/ must be logic-free | warning | `common/` files containing domain-specific rules or database access |

### State & Resource Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-016 | global-state | Layers must not communicate via global shared variables | error | Use of `global` or `static` variables to pass data between layers |
| LNT-017 | connection-leak | Persistence layer must manage its own connection lifecycle | error | Connection objects (e.g., `SqlConnection`) passed as arguments into `business/` |
| LNT-018 | transaction-leak | Transaction boundaries should be managed in the Business layer | warning | `commit()` or `rollback()` calls appearing inside `presentation/` or `persistence/` |
| LNT-019 | session-bleeding | HTTP session objects must not be passed to the business layer | error | `HttpServletRequest` or `Session` objects found in `business/` method signatures |

### Anti-Pattern Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-020 | sinkhole-pattern | Avoid services that only delegate to the layer below | warning | Methods in `business/` that consist of a single return call to `persistence/` |
| LNT-021 | fat-controller | Controllers must delegate to business services | error | `presentation/` controllers exceeding 3 injected dependencies or 200 lines |
| LNT-022 | smart-ui | UI components must not contain data validation logic | warning | UI-tier code performing complex domain validation instead of calling `business/` |
| LNT-023 | anemic-domain | Ensure Business layer contains logic, not just getters/setters | warning | `business/` folder consisting entirely of DTOs with no logic-bearing services |
| LNT-024 | lasagne-architecture | Do not create unnecessary sub-layers | warning | A single request path crossing > 5 layer boundaries |

### Error Handling & Reliability Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-025 | silent-failure | Layers must not swallow exceptions without logging or rethrowing | error | Empty `catch` blocks or `catch` blocks that only log without re-escalation |
| LNT-026 | generic-exceptions | Layers must throw specific custom exceptions | warning | Usage of `throw new Exception()` or `throw new RuntimeException()` |
| LNT-027 | validation-bypass | Persistence must not be called without going through validation | error | Call sites for `persistence/` methods found outside of `business/` |

### Testing & Verification Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-028 | unit-test-isolation | Business layer unit tests must use mocks for persistence | error | Unit tests in `business/` that attempt to connect to a real database |
| LNT-029 | missing-layer-tests | Each layer should have a corresponding test suite | warning | A layer directory (e.g., `persistence/`) with 0 matching files in `tests/` |
| LNT-030 | integration-test-scope | Integration tests must span at least two layers | warning | Tests labeled "integration" that only exercise a single isolated class |

### Configuration & Lifecycle Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-031 | hardcoded-config | Configuration values must not be hardcoded in layers | error | Hardcoded DB URLs, API keys, or environment-specific flags in `business/` |
| LNT-032 | circular-init | Service initialization must not contain circular dependencies | error | `constructor` calls that eventually lead back to the same class during startup |
| LNT-033 | side-effect-ctor | Constructors must not perform heavy IO or logic | warning | `constructor` methods containing database queries or network calls |
| LNT-034 | static-dependency | Avoid static method calls for cross-layer logic | warning | `business/` calling static methods in `persistence/` (hinders mockability) |
| LNT-035 | improper-common-dep | Common layer must not depend on any other layer | error | `import <pkg>.business` or `import <pkg>.persistence` in `common/` |

### Data Integrity & Concurrency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| LNT-036 | race-condition | Business services should be stateless to ensure thread safety | error | Non-final instance variables in `business/` services that are modified after init |
| LNT-037 | missing-optimistic-lock | Updates must handle concurrent modifications | warning | `persistence/` update methods that do not use a version column or timestamp |
| LNT-038 | async-leak | Background tasks must not outlive the request scope in presentation | warning | `async` or `Thread
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest Layered N-Tier is in use):
- `presentation/` — UI components, controllers, view models, and API endpoints
- `business/` or `service/` or `services/` — business logic and domain rules layer
- `persistence/` or `dal/` or `data/` — data access objects and repository implementations
- `database/` — migrations, schemas, and stored procedures
- `common/` or `shared/` — cross-cutting utilities shared across layers

### File signals
Strong indicators (any 1 is significant):
- Files named `*DAO.*` or `*DataAccessObject.*` in a persistence directory
- Files named `*Controller.*` in `presentation/` alongside `*Service.*` in `business/`
- ORM mapping files (`*Mapping.*`, `*OrmEntity.*`) in a `persistence/` layer
- Files named `*Repository.*` as concrete classes (not interfaces) in `persistence/`

### Anti-signals
Suggest Layered N-Tier is NOT in use:
- Domain-driven directory structure with `domain/`, `application/`, `infrastructure/` (leans DDD instead)
- Multiple independent `Dockerfile` files per service (leans Microservices instead)
- No distinct presentation, business, or persistence directories
