# DDD Pureness Doctrine

This doctrine audits Domain-Driven Design implementation for isolation, consistency boundaries, and ubiquitous language compliance.

## When to Use

Use DDD when your domain has significant complexity — multiple aggregates with
non-trivial business rules, invariants that span state transitions, and
terminology that matters to the business. DDD is overkill for CRUD-heavy
applications with simple validation, but essential when the cost of getting
domain logic wrong is high (financial systems, regulatory compliance,
multi-party workflows).

## Why Use It

DDD isolates business logic from infrastructure concerns, making the domain
model the single source of truth for business rules. This means:
- Business rules are testable without databases, HTTP, or message brokers
- Domain experts can read the code and validate correctness
- Infrastructure can change (swap Postgres for DynamoDB) without touching
  business logic
- New team members understand the business by reading the domain layer

## Pros and Cons

| Pros | Cons |
|---|---|
| Business logic isolated and testable in pure Python | Upfront modelling cost — getting boundaries wrong is expensive to fix |
| Ubiquitous language makes code readable by non-engineers | More files and abstractions than simple CRUD |
| Infrastructure changes don't break business rules | Requires discipline — easy to "shortcut" and leak infrastructure in |
| Aggregates enforce consistency boundaries naturally | Aggregate size management requires ongoing attention |
| Value objects eliminate entire classes of bugs (money arithmetic, immutability) | Learning curve for developers unfamiliar with tactical DDD |
| Domain events provide audit trail and integration points | Cross-aggregate workflows need eventual consistency patterns |

## Applicable Directories

Primary targets (from `.architecture/config.yml` `layers` mapping):
- `domain/` layer — ALL files (strictest rules)
- `application/` layer — dependency direction only
- `api/` and `infrastructure/` — checked only for inward dependency violations

## Violation Catalog

### Layer Boundary Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-001 | layer-boundary | Domain must not import from infrastructure | error | `from <pkg>.infrastructure` or `import <pkg>.infrastructure` in domain/ files |
| DDD-002 | layer-boundary | Domain must not import from API layer | error | `from <pkg>.api` or `import <pkg>.api` in domain/ files |
| DDD-003 | layer-boundary | Domain must not import from application layer | error | `from <pkg>.application` or `import <pkg>.application` in domain/ files |
| DDD-004 | layer-boundary | Domain must not import framework libraries | error | `import sqlalchemy`, `fastapi`, `celery`, `redis`, `aiohttp`, `httpx`, `requests` in domain/ files |
| DDD-005 | layer-boundary | Domain must not perform I/O | error | `session.execute`, `await fetch`, `open(`, `publish(`, HTTP calls, DB queries in domain/ files |
| DDD-006 | layer-boundary | Application must not import from API layer | warning | `from <pkg>.api` in application/ files |

**Scanning approach:** Import analysis (grep) for DDD-001–004. Pattern matching
on I/O signatures for DDD-005. Grep application/ for DDD-006.

**Allowed domain imports:** `pydantic` (schema validation), stdlib (`uuid`,
`datetime`, `decimal`, `typing`, `abc`, `collections`, `re`, `json`, `os`,
`copy`), project utils that are pure functions (e.g., `utc_today`, `uuid7`).

### Aggregate Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-010 | aggregate-design | Aggregates must extend BaseAggregate | error | Classes in `aggregates/` not inheriting `BaseAggregate` (excluding base.py) |
| DDD-011 | aggregate-design | Aggregates must not hold other aggregates by instance | error | Aggregate attributes typed as another aggregate class. References by ID (`uuid.UUID`) are correct |
| DDD-012 | aggregate-design | State changes must only happen via events | error | `self.<field> =` assignments outside `_when_*` handlers in aggregate files |
| DDD-013 | aggregate-design | Event handlers must be private `_when_*` methods | warning | Public methods mutating state from event data without following the `_when_<snake_case>` naming convention |
| DDD-014 | aggregate-design | Aggregates must implement snapshot methods | warning | Missing `to_snapshot()` or `from_snapshot()` on aggregate classes |
| DDD-015 | aggregate-design | Aggregate size should be manageable | warning | Aggregate class >500 LOC ([Vernon: 300-400 LOC max](https://www.dddcommunity.org/library/vernon_2011/)), or >20 distinct event types, or >15 command methods |
| DDD-016 | aggregate-design | One aggregate per transaction | error | Service methods modifying multiple aggregates in one transaction ([Vernon: consistency boundary rule](https://www.dddcommunity.org/library/vernon_2011/)) |
| DDD-017 | aggregate-design | Constructor must establish valid state | warning | Aggregate `__init__` or `create()` methods with >5 parameters that perform no validation before emitting the creation event |

### Value Object Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-020 | value-object | Value objects should use `__slots__` | warning | Classes in `value_objects/` without `__slots__` |
| DDD-021 | value-object | Value objects must be immutable | error | Public setter methods, `self.<field> =` outside `__init__`, properties returning mutable references without copying |
| DDD-022 | value-object | Equality must be by value | warning | Value object classes without `__eq__` (relying on identity comparison) |
| DDD-023 | value-object | Must provide serialization | warning | Missing `to_dict()` or `from_dict()` methods |
| DDD-024 | value-object | Arithmetic must return new instances | error | `__add__`/`__sub__`/etc. that mutate `self` instead of returning `type(self)(...)` |
| DDD-025 | value-object | Immutable VOs should be hashable | warning | Value objects with `__eq__` but missing `__hash__` (prevents use in sets/dict keys) |

### Entity Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-030 | entity | Entities must have identity | error | Classes in `entities/` without an `*_id` attribute |
| DDD-031 | entity | Entities should use `__slots__` | warning | Entity classes without `__slots__` |
| DDD-032 | entity | Must provide serialization | warning | Missing `to_dict()` or `from_dict()` (needed for aggregate snapshots) |
| DDD-033 | entity | Entity equality must be by identity | warning | Entity `__eq__` comparing attributes instead of just `self.<id_field> == other.<id_field>` |

### Event Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-040 | event-design | Events must be immutable | error | Event classes without `model_config = {"frozen": True}` or Pydantic frozen inheritance |
| DDD-041 | event-design | Events must extend DomainEvent | error | Event classes in `events/` not inheriting `DomainEvent` |
| DDD-042 | event-design | Events should not contain business logic | warning | Event classes with methods beyond serialization, properties, or model validators |
| DDD-043 | event-design | Event names must be past tense | warning | Event class names not past tense (e.g., `CreateLoan` instead of `LoanCreated`) |
| DDD-044 | event-design | Events must support schema evolution | warning | New event fields without default values, or handlers that don't use `.get()` for optional fields |
| DDD-045 | event-design | Events must be dispatched after state change | error | Aggregate methods that publish directly to an event bus instead of adding to uncommitted events list |

### Command Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-050 | command-design | Commands must extend BaseCommand | error | Command classes in `commands/` not inheriting `BaseCommand` |
| DDD-051 | command-design | Commands must use imperative naming | warning | Command names not imperative (e.g., `LoanApproved` instead of `ApproveLoan`) |
| DDD-052 | command-design | Validation must use Pydantic | warning | Manual `if/raise` validation in `__init__` instead of Pydantic validators |
| DDD-053 | command-design | Commands must not contain business logic | warning | Commands with methods beyond Pydantic validators that perform domain calculations or call services |

### Domain Service Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-060 | domain-service | Domain services must be stateless | error | `self.<field> =` assignments in methods other than `__init__` in domain `services/` |
| DDD-061 | domain-service | Domain services must not perform I/O | error | Same as DDD-005 scoped to domain `services/` |
| DDD-062 | domain-service | Domain services must not orchestrate | warning | Domain services that load aggregates from repositories/event stores, manage transactions, or coordinate multi-aggregate workflows (that belongs in application services) |

### Anti-Pattern Detection

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-070 | anti-pattern | Anemic domain model | warning | Aggregate with >5 properties but <3 business methods ([Fowler: AnemicDomainModel](https://martinfowler.com/bliki/AnemicDomainModel.html)) |
| DDD-071 | anti-pattern | Primitive obsession | warning | Aggregate fields typed as raw `str`/`Decimal`/`int` for domain concepts that warrant value objects (e.g., email addresses, currency amounts not using `Money`, status codes as raw strings) |
| DDD-072 | anti-pattern | Invariant enforcement outside aggregate | warning | Application/service layer performing business rule validation (`if amount > limit: raise`) that should live in the aggregate's command method |
| DDD-073 | anti-pattern | Missing anti-corruption layer | warning | Domain layer importing external SDK types or using external system terminology directly without a translation adapter |

### Naming / Ubiquitous Language

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-080 | naming | Domain objects should use business language | warning | Technical jargon in domain names (`DBLoan`, `HttpPayment`, `CacheAccount`, `DataManager`, `EntityProcessor`) |
| DDD-081 | naming | Avoid CRUD naming in domain | warning | Methods named `create_record`, `update_row`, `delete_entry`, `insert_*`, `select_*`. Prefer domain verbs: `submit`, `approve`, `disburse`, `accrue` |
| DDD-082 | naming | Avoid abbreviations in domain | warning | Abbreviated names (`Mgr`, `Ctx`, `Proc`, `Svc`) in domain layer. Full words improve readability |

### UTC Consistency

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DDD-090 | temporal | Use `utc_today()` not `date.today()` | error | `date.today()` or `datetime.now()` without `timezone.utc` in domain/ files |

## Allowed Exceptions

- **Pydantic in domain:** Allowed as schema validation framework. Does not
  create infrastructure coupling. If a project's `decisions.yml` explicitly
  disallows Pydantic in domain, promote DDD-004 to also flag Pydantic imports.
- **`__slots__` on entities:** Entities (Draw, Earmark) are mutable by design.
  `__slots__` is recommended (DDD-031) for memory efficiency but not required
  for DDD compliance.
- **Aggregate size (DDD-015):** Large aggregates may be justified when splitting
  would break consistency boundaries. The violation is advisory — flag for review
  rather than automatic failure.
- **Stdlib Decimal in calculators:** Domain calculators (InterestCalculator,
  DemandCalculator) may use `decimal.Decimal` directly rather than `Money` when
  performing intermediate calculations. The final result should be wrapped in
  `Money` before returning.
- **Event handler idempotency:** Not checked in this doctrine because it overlaps
  with the event-sourcing doctrine (EVS-xxx). Cross-reference that doctrine for replay
  correctness rules.

## Cross-Reference

This doctrine pairs well with:
- **event-sourcing.md** — covers event store patterns, replay correctness,
  snapshot consistency, event handler idempotency
- **layer-boundaries.md** — covers generic layer separation beyond DDD-specific
  rules (useful for projects that want layer discipline without full DDD)
- **cqrs.md** — covers read/write model separation, projection design

## Sources and Authority

This doctrine is based on authoritative DDD sources:

**Foundational Works:**
- [Eric Evans - Domain-Driven Design (2003)](https://www.domainlanguage.com/ddd/) — The original DDD book
- [Evans - DDD Reference (2015)](https://www.domainlanguage.com/ddd/reference/) — Condensed pattern definitions
- [Vaughn Vernon - Implementing DDD (2013)](https://vaughnvernon.com/implementing-domain-driven-design/) — Tactical patterns
- [Vernon - Effective Aggregate Design](https://www.dddcommunity.org/library/vernon_2011/) — Three-part series on aggregate boundaries

**Aggregate Design Rules:**
- [Vaughn Vernon - Aggregate Design Rules](https://www.dddcommunity.org/library/vernon_2011/) — Small aggregates, consistency boundaries
- [Julie Lerman - DDD Aggregates](https://docs.microsoft.com/en-us/archive/msdn-magazine/2009/february/best-practice-an-introduction-to-domain-driven-design) — Microsoft guidance
- [Martin Fowler - Aggregate](https://martinfowler.com/bliki/DDD_Aggregate.html) — Aggregate pattern explanation

**Value Objects and Entities:**
- [Vladimir Khorikov - Entity vs Value Object](https://enterprisecraftsmanship.com/posts/entity-vs-value-object-the-ultimate-list-of-differences/) — Comprehensive comparison
- [Fowler - Value Object](https://martinfowler.com/bliki/ValueObject.html) — Immutability patterns
- [Evans - Value Objects in DDD](https://www.domainlanguage.com/ddd/reference/) — Original definition

**Anti-Patterns:**
- [Fowler - Anemic Domain Model](https://martinfowler.com/bliki/AnemicDomainModel.html) — The most common DDD anti-pattern
- [Vernon - Aggregate Boundaries](https://www.dddcommunity.org/library/vernon_2011/) — Transaction boundary violations
- [Jimmy Bogard - Primitive Obsession](https://jimmybogard.com/primitive-obsession/) — Why value objects matter

**Modern Practices (2020-2025):**
- [Nick Tune - Domain-Driven Architecture](https://github.com/ddd-crew) — DDD Crew patterns
- [Kamil Grzybek - DDD Starter Kit](https://github.com/kgrzybek/modular-monolith-with-ddd) — Modern C#/.NET patterns
- [DDD Community](https://www.dddcommunity.org/) — Current best practices
