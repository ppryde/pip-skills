# Repository Pattern Doctrine

The Repository pattern mediates between the domain and data mapping layers using a collection-like interface for accessing domain objects. It enforces a single, strict dependency direction: services interact with domain objects through a repository interface they own; the database engine, ORM, and query language are implementation details the rest of the system never sees.

**Language Scope:** Language-agnostic

## When to Use

Use the Repository pattern in any system with a meaningful separation between business logic and data storage — specifically when:
- A service layer orchestrates domain objects that need to be loaded, persisted, and queried
- The persistence technology may change, or must be swapped per environment (e.g., in-memory for tests)
- Integration tests are expensive and unit tests must run without a live database
- Multiple services share the same aggregate types and you want a single, authoritative access path

**Do NOT use it** for trivial single-table CRUD scripts or "serverless glue" functions where the overhead of defining an interface outweighs the benefit. Do not introduce a Repository when ActiveRecord or a simple ORM query in a controller is the entire application — the pattern pays dividends only when the distance between business logic and storage is real, not invented.

## Why Use It

- **Persistence ignorance** — Domain objects contain zero knowledge of how or where they are stored. Swapping Postgres for DynamoDB or Redis requires changing the repository implementation only, not the service layer or domain model ([Fowler, PEAA 2002](https://martinfowler.com/eaaCatalog/repository.html)).
- **Testability without a live database** — A fake or in-memory repository is trivially constructed; unit tests run in milliseconds without Docker or migrations ([Percival & Gregory, Cosmic Python 2020](https://www.cosmicpython.com/book/chapter_02_repository.html)).
- **Centralised query logic** — All permutations of "how do we fetch an Order?" live in one class, eliminating duplicate ORM code scattered across handlers and services.
- **Dependency inversion at the storage boundary** — Services depend on an interface they own; the concrete implementation depends on the ORM, not the other way around.
- **Clean transaction boundary** — Repositories do not manage transactions; callers (services or Unit of Work) decide commit/rollback scope, keeping atomicity policy explicit.
- **Domain language in queries** — Repository methods express intent (`find_active_sessions_for_user`) rather than ORM mechanics (`session.query(Session).filter(...).all()`).

## Pros and Cons

| Pros | Cons |
|---|---|
| Zero persistence knowledge in domain and service layers | Interface + implementation boilerplate for every aggregate type |
| In-memory fakes make unit tests fast and independent | Risk of generic "grab-bag" repository accumulating every possible query ([Stemmler, 2019](https://khalilstemmler.com/articles/typescript-domain-driven-design/repository-dto-mapper/)) |
| Single authoritative path to each aggregate prevents scattered ORM calls | Teams unfamiliar with the pattern mistake it for a DAO and add update/delete mutations directly ([Percival & Gregory, 2020](https://www.cosmicpython.com/book/chapter_02_repository.html)) |
| Enables storage technology swap without touching service code | Thin pass-through repositories add indirection with no real benefit (Fowler's Sinkhole Anti-pattern) |
| Makes transaction scope explicit — the repository is not responsible for commits | N+1 query risks increase if repositories load eagerly and callers are unaware |
| Query logic is consolidated — one place to fix a slow query | ORM change-tracking can conflict with repository semantics if not handled carefully |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `repositories/` — concrete repository implementations; all database queries live here
- `infrastructure/persistence/` — alternative to `repositories/` in Hexagonal layouts; adapters implementing repository interfaces
- `domain/` or `domain/repositories/` — repository interface definitions (abstract contracts, no implementations)
- `services/` or `application/` — service layer that imports only repository interfaces, never concrete implementations
- `tests/fakes/` or `tests/stubs/` — in-memory fake repositories used in unit tests

## Violation Catalog

### Interface & Abstraction Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-001 | interface-design | Repository must be defined as an interface or abstract class | error | Concrete repository class (no abstract base class, no Protocol, no interface) that has no corresponding abstract definition anywhere in the codebase — this is a multi-file check: find all files named `*Repository.*`, identify those that are non-abstract, and confirm no abstract counterpart exists |
| REP-002 | interface-design | Repository interface must be owned by the domain or application layer, not the infrastructure layer | error | Repository interface definitions (abstract class / Protocol) located inside `infrastructure/` or `persistence/` directories |
| REP-003 | interface-design | Repository interface must not expose ORM or database types in its method signatures | error | Method signatures in repository interfaces containing ORM-specific types (e.g. `Session`, `Connection`, `QuerySet`, `Cursor`, `Row`) |
| REP-004 | interface-design | Repository interface must not expose raw SQL strings | error | SQL string literals (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) present in repository interface files |
| REP-005 | interface-design | Repository interface methods must use domain object types, not primitive IDs alone | warning | Repository interface methods accepting or returning untyped primitives or raw data containers where a domain type is expected — e.g. `dict`/`tuple`/`Any` (Python), `Map`/`Object[]` (Java), `any`/`Record<string, unknown>` (TypeScript) — rather than a named domain class |

### Dependency Direction Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-010 | dependency-direction | Service layer must not import concrete repository implementations | error | Import of a concrete repository class (e.g. `PostgresOrderRepository`, `SqlAlchemySessionRepo`) in `services/` or `application/` files |
| REP-011 | dependency-direction | Domain objects must not import from the repository layer | error | Import of any repository class (interface or concrete) in `domain/` model files |
| REP-012 | dependency-direction | Repository implementations must not import from the service layer | error | Import of service-layer classes in `repositories/` or `infrastructure/persistence/` files |
| REP-013 | dependency-direction | Controllers or transport handlers must not directly instantiate repositories | error | Direct class construction of a concrete repository class inside route/handler/controller files — look for repository class names followed by `()` or `new` in handler files; constructions inside files named `*factory.*`, `*container.*`, `*provider.*`, or `*bootstrap.*` are excluded |
| REP-014 | dependency-direction | ORM session or database connection must not be passed into the service layer | error | ORM session, connection, or cursor objects (e.g. `Session`, `Connection`, `AsyncSession`) in service-layer method signatures |

### Responsibility Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-020 | responsibility | Repository must not contain business logic | error | Conditional branching, arithmetic, or domain rule enforcement in repository implementation methods beyond query construction and null-guard / not-found handling (e.g. `if result is None: raise NotFound` is permitted; tax calculations, discount logic, or state machine transitions are not) — flag methods with >3 conditional branches unrelated to null checks or empty-result handling |
| REP-021 | responsibility | Repository must not manage transaction commit or rollback | error | `commit()`, `rollback()`, `BEGIN`, or `SAVEPOINT` calls inside repository method bodies |
| REP-022 | responsibility | Repository must not send notifications, publish events, or trigger side effects | error | Calls to message brokers, email clients, or event publishers inside repository method bodies — signals: method calls named `publish`, `emit`, `dispatch`, `send_email`, `send_notification`, `enqueue`, or imports of messaging/email client packages (`kombu`, `celery`, `boto3 SNS/SQS`, `sendgrid`, `smtplib`, or equivalents) inside repository files |
| REP-023 | responsibility | Repository must not validate domain invariants | error | Raise/throw of domain validation exceptions inside repository method bodies — language-specific signals: `raise ValueError` / `raise DomainError` (Python), `throw new IllegalArgumentException` / `throw new DomainException` (Java/C#), `throw new Error` with domain message text (TypeScript/Node) |
| REP-024 | responsibility | Repository must not orchestrate multiple aggregates | warning | Repository method bodies that load or persist more than one distinct aggregate root type |
| REP-025 | responsibility | Repository save must harvest domain events from the aggregate before returning | warning | `save()`/`add()` method bodies that do not reference the aggregate's event collection (`aggregate.events`, `aggregate.domain_events`, or equivalent) before returning — applies only where the aggregate type declares a domain event list; exempt in non-DDD codebases where aggregates carry no event queue |

**Scanning approach:** Repository methods should be mechanically simple: build query, execute query, map result to domain object, return. Any branching on domain state is a red flag.

### Query Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-030 | query-design | Raw SQL must not appear outside the repository layer | error | SQL string literals (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) in `services/`, `application/`, `domain/`, or controller/handler files |
| REP-031 | query-design | ORM queries must not appear outside the repository layer | error | ORM query methods in `services/`, `application/`, or `domain/` files — language-specific signals: `.query()`, `.filter()`, `.execute()`, `db.session` (SQLAlchemy/Django); `.findBy()`, `.createQueryBuilder()` (TypeORM/Hibernate); `EntityManager.find()`, `CriteriaBuilder` (JPA); `.find()`, `.aggregate()` (Mongoose) |
| REP-032 | query-design | Repository must not expose query builder objects to callers | error | Repository methods returning an ORM query builder, `QuerySet`, or `SelectBase` object rather than resolved domain objects or collections |
| REP-033 | query-design | Duplicate query logic must not exist across multiple repositories | warning | Identical query fragments (same table name + same column filter combination as a string literal) appearing verbatim in more than one repository file outside a shared query helper — near-identical detection requires AST-level analysis; flag only on exact string match duplication at grep level |
| REP-034 | query-design | Repository methods must be named in domain language, not storage language | warning | Repository method names using storage-tier vocabulary rather than domain intent — snake_case examples (Python): `execute_query`, `run_sql`, `fetch_rows`, `select_where`, `db_get`; camelCase equivalents (Java/TypeScript): `executeQuery`, `runSql`, `fetchRows`, `selectWhere`, `dbGet` |
| REP-035 | query-design | Repository find methods must explicitly exclude soft-deleted records | error | `find`/`get`/`list` methods in repository implementations that query a table with a soft-delete column (`deleted_at`, `is_deleted`, `archived_at`, `deleted`) where no filter clause excluding soft-deleted records appears in the method body — signals: absence of `deleted_at IS NULL`, `is_deleted = false`, or equivalent guard in queries against tables that carry a soft-delete column |

### Mapping & Data Integrity Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-040 | mapping | ORM entity models must not be returned directly to the service layer | error | Repository methods with return type annotations of ORM model classes (e.g. `UserModel`, `SessionRow`, `Base` subclasses) rather than domain objects |
| REP-041 | mapping | Domain objects must not carry ORM annotations or decorators | error | ORM-specific decorators or base classes on domain model classes — language-specific signals: inheriting from `declarative_base` or `Base` (SQLAlchemy/Python); `@Entity`, `@Table`, `@Column` annotations (JPA/Hibernate Java); `@Entity()`, `@Column()` decorators (TypeORM/TypeScript); `extends Model` from an ORM namespace (Django, Sequelize) |
| REP-042 | mapping | Repository must explicitly map persistence model to domain object | warning | Repository `get`/`list` methods returning data without a mapping step (e.g. direct `return row` where `row` is a raw ORM object) |
| REP-043 | mapping | Repository must explicitly map domain object to persistence model on save | warning | Repository `add`/`save` methods that pass the domain object directly to the ORM save method without an explicit conversion step |
| REP-044 | mapping | Database-generated IDs must not be treated as domain identity without explicit mapping | warning | Auto-increment integer primary keys from the ORM used directly as domain entity identity fields without UUID or domain-assigned ID abstraction — applies only where DDD-style aggregate identity is the stated architecture; codebases that do not use DDD aggregates and have no stated UUID/domain-ID strategy are exempt from this rule |
| REP-045 | mapping | Repository save must enforce optimistic concurrency on versioned entities | warning | `save()`/`update()` methods writing to an entity that declares a version, `etag`, or `row_version` field without a version-guard condition in the resulting query — signals: absence of `WHERE version = :version`, `WHERE etag = :etag`, or ORM-level version check (`@Version`, `version_id_col`) in update operations on entities that carry a version attribute |

**Scanning approach:** Trace the return path of every `get()` and `find_*()` method. If the chain ends in `return orm_object` with no mapper call, REP-040/042 fires.

### Naming & Convention Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-050 | naming | Repository class names must follow the `<Aggregate>Repository` convention | warning | Repository implementation classes whose names do not end in `Repository` (e.g. `OrderStore`, `UserDao`, `PersonalityManager` used as a persistence class) |
| REP-051 | naming | Repository interface names must be distinct from concrete implementations | warning | Repository interface and its concrete implementation sharing the same name without a differentiating prefix/suffix (e.g. both named `OrderRepository` with no `I`, `Abstract`, or `Postgres` qualifier) |
| REP-052 | naming | Repository methods must use collection-semantic names | warning | Repository methods named using database/infrastructure vocabulary rather than domain intent — snake_case (Python): `fetch_all_records`, `retrieve_entity`, `load_data`, `get_db_row`; camelCase (Java/TypeScript): `fetchAllRecords`, `retrieveEntity`, `loadData`, `getDbRow` — instead of domain-semantic names such as `list_active` / `listActive`, `find_by_id` / `findById`, `find_by_user` / `findByUser` |
| REP-053 | naming | Repository methods must use collection vocabulary — add/get/remove, not create/update/delete | warning | Repository class methods named `create_*`/`createX`, `update_*`/`updateX`, or `delete_*`/`deleteX` instead of collection-semantic equivalents (`add`, `get`, `remove`, or domain-intent names) — CRUD vocabulary signals the class has been implemented as a DAO; the collection metaphor is foundational to the Fowler definition ([Fowler, PEAA 2002](https://martinfowler.com/eaaCatalog/repository.html)) |

### Testability Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-060 | testability | Each repository interface must have a corresponding fake or in-memory implementation | warning | Repository interface in `domain/` or `application/` with no corresponding `Fake*Repository`, `InMemory*Repository`, `Mock*Repository`, or `Stub*Repository` class in any `tests/` directory — absence check: count abstract repository definitions in domain/application; confirm each has at least one matching fake class |
| REP-061 | testability | Unit tests for services must not use the concrete database repository | error | Unit test files in `tests/unit/` importing a concrete repository class that holds a real ORM session or database connection |
| REP-062 | testability | Fake repositories must implement the same interface as the real repository | error | `Fake*Repository` class not inheriting from or implementing the same interface as its corresponding production repository |
| REP-063 | testability | Repository integration tests must be isolated to the persistence layer | warning | Tests classified as integration tests that import service-layer classes alongside repository classes in the same test module |

### Anti-Pattern Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| REP-070 | anti-pattern | Generic catch-all repositories must not accumulate every query in the system | warning | Single repository class exceeding 15 public methods or 400 lines, particularly when serving multiple distinct aggregate types |
| REP-071 | anti-pattern | Repository must not be used as a DAO with arbitrary CRUD for every table | warning | Repository class containing `create_<entity>`, `update_<entity>`, `delete_<entity>` method triplets for more than 3 distinct entity types |
| REP-072 | anti-pattern | Services must not bypass the repository to access the database directly | error | Database driver or low-level client imports in `services/` or `application/` files — any import of a package whose sole purpose is direct database wire-protocol access (Python examples: `psycopg2`, `asyncpg`, `pymongo`, `sqlite3`; Java examples: `java.sql.Connection`, `jdbc`; Node examples: `pg`, `mysql2`, `mongoose`) |
| REP-073 | anti-pattern | Repository must not be a thin wrapper that adds no encapsulation value | warning | Repository implementation methods that are a single line returning a direct ORM call with no mapping, no domain object construction, and no query abstraction |
| REP-074 | anti-pattern | Repository must not accumulate lazy-load triggers that cause N+1 queries | warning | Repository `list` or `find_all` / `findAll` methods that return collections without explicit eager-load directives where related entities are accessed by callers — language-specific signals: absence of `joinedload`/`selectinload` (SQLAlchemy), `prefetch_related`/`select_related` (Django), `JOIN FETCH` (JPQL/HQL), `.include()` (TypeORM/Prisma), or equivalent in the relevant ORM |
| REP-075 | anti-pattern | Repositories must only be created for aggregate roots, not for child entities | error | Repository class whose name references a known non-root entity type — detectable by cross-referencing: if the entity has no independent identity outside its parent aggregate (no standalone `id` used outside the parent context, always loaded via parent in the domain), a standalone repository for it violates the DDD aggregate boundary rule ([Evans, DDD 2003]); signals: repository names ending in a type that is also declared as a child collection on a parent entity class |
| REP-076 | anti-pattern | Repository list methods must not return unbounded collections | error | `list()`/`find_all()`/`findAll()`/`get_all()`/`getAll()` repository methods with no `limit`, `page`, `offset`, `cursor`, or `per_page` parameter in the signature and no hardcoded result-size cap in the query body — returning an unbounded collection is a production incident waiting to happen as data grows |
| REP-077 | anti-pattern | Repositories with excessive find_by_* methods should adopt the Specification pattern | warning | Repository class with more than 5 methods matching `find_by_*`/`findBy*`, `get_by_*`/`getBy*`, or `list_by_*`/`listBy*` naming — signals that query-building responsibility is accumulating inside the repository rather than being delegated to composable Specification objects; the repository becomes a query bag, not a collection |

**Scanning approach:** REP-070 fires on method count (>15 public methods) or LOC (>400). REP-073 fires on methods that are a single return statement wrapping a raw ORM call with no mapping step. REP-072 fires on driver-level imports — if any DB client package is imported directly in a service file, the repository boundary is broken regardless of how few lines the import is.

## Allowed Exceptions

- **Test fixtures and factories:** Test setup code (`conftest.py`, factory functions) may directly instantiate concrete repositories or call ORM sessions to seed state. This code does not run in production and is exempt from REP-010, REP-013, REP-061.
- **Database migration scripts:** Migration files (Alembic, Flyway, Liquibase) contain raw SQL by definition and are exempt from REP-030.
- **Read models and projections (CQRS):** When the codebase uses CQRS, the query side may bypass the repository pattern entirely and use direct ORM queries or raw SQL in dedicated query handlers. REP-030, REP-031, REP-040 do not apply to files within a `queries/` or `read_models/` directory explicitly designated as the CQRS read side.
- **Tiny scripts and CLI tools:** One-off administrative scripts that are not part of the application's deployed service layer are exempt from all REP rules.
- **ActiveRecord in frameworks:** In frameworks where ActiveRecord is the intended pattern (Rails, early Django views), REP-041 (ORM annotations on domain models) is a framework requirement, not a violation. Only applicable where DDD-style domain/infrastructure separation is the stated architecture.
- **Shared query utilities:** A single shared private query helper method used by multiple methods within the same repository does not trigger REP-033.

## Cross-Reference

This doctrine pairs well with:
- **ddd.md** — Repositories are a tactical DDD pattern. DDD doctrine governs the internal structure of the domain objects the repository loads and saves (Aggregates, Entities, Value Objects).
- **hexagonal.md** — In Hexagonal Architecture, the repository interface is a Driven Port and the concrete implementation is an Adapter. HEX-010 and REP-002 are complementary rules.
- **layered-n-tier.md** — In Layered Architecture, repositories live in the persistence layer. LNT-009 (no business logic in persistence) and REP-020 express the same invariant from different angles.
- **cqrs.md** — Repositories govern the write (command) side. The CQRS read side may legitimately bypass the repository pattern — see REP-031 exception.
- **unit-of-work.md** — The Unit of Work pattern manages transaction scope; the repository is intentionally transaction-unaware. These two patterns are designed to compose.
- **testing.md** — Fake repositories are the primary test double mechanism for service-layer unit tests. Testability rules (REP-060 through REP-063) align with testing doctrine expectations.

## Sources and Authority

**Foundational Works:**
- [Martin Fowler — Patterns of Enterprise Application Architecture (2002)](https://martinfowler.com/eaaCatalog/repository.html) — Canonical definition: "Mediates between the domain and data mapping layers using a collection-like interface for accessing domain objects." Establishes the collection metaphor and the one-way dependency rule.
- Eric Evans — Domain-Driven Design: Tackling Complexity in the Heart of Software (2003) — Defines Repository as a tactical DDD pattern; specifies that only Aggregate Roots should have repositories and that the interface belongs to the domain layer.

**Practitioner Guidance:**
- [Harry Percival & Bob Gregory — Architecture Patterns with Python (Cosmic Python, 2020)](https://www.cosmicpython.com/book/chapter_02_repository.html) — Definitive practical treatment: fake repository pattern, persistence ignorance, ORM dependency inversion, and Unit of Work composition. Establishes the `add() / get()` minimal interface.
- [Khalil Stemmler — Repository, DTO, and Mapper (2019)](https://khalilstemmler.com/articles/typescript-domain-driven-design/repository-dto-mapper/) — Practitioner guidance on interface-first design, domain-language method naming, mapper responsibilities, and the risk of generic repositories accumulating unbounded query methods.

**Anti-Patterns / Failure Cases:**
- [Harry Percival & Bob Gregory — Unit of Work chapter (Cosmic Python, 2020)](https://www.cosmicpython.com/book/chapter_06_uow.html) — Documents the failure mode of passing ORM session objects through the call stack, breaking persistence ignorance and making unit tests impossible without a live database. Establishes explicit commit as a design requirement. The pathology: when `Session` leaks into services, every unit test needs a live database, and the repository layer becomes a performance.
- Khalil Stemmler — Tackling complexity in TypeScript (2019) — Identifies the "generic grab-bag repository" anti-pattern: teams that implement a single generic `Repository<T>` with `getAll()`, `update()`, `delete()` methods for every entity type end up rebuilding a DAO with extra steps. The encapsulation benefit dissolves — every caller still needs to know which fields to filter on and the repository accumulates unbounded query permutations until it becomes unmaintainable.

## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest the Repository pattern is in use):
- `repositories/` — dedicated directory for repository implementations (not just a `persistence/` catch-all)
- `domain/repositories/` or `application/repositories/` — repository interfaces defined inside the domain or application layer
- `tests/fakes/` or `tests/stubs/` — in-memory fake implementations indicating deliberate test-double strategy
- `infrastructure/persistence/` alongside a separate `domain/` layer — adapter implementations separated from domain interfaces (bare `infrastructure/` alone is not sufficient; require the `persistence/` sub-path)

### File signals
Strong indicators (any 1 is significant):
- Files named `*Repository.*` in a persistence or infrastructure directory
- Files named `Fake*Repository.*` or `InMemory*Repository.*` in a tests directory
- Files named `Abstract*Repository.*` or `I*Repository.*` in a domain or application directory

### Anti-signals
Suggest the Repository pattern is NOT in use:
- ORM queries (`.filter()`, `.query()`, `.find()`, `SELECT`) present directly in service or handler files — leans ActiveRecord or naive layering
- No files named `*Repository.*` anywhere in the codebase — leans DAO pattern, Table Gateway, or no persistence abstraction
- Domain model files contain ORM base class inheritance (`declarative_base`, `Model`) — leans ActiveRecord, not Repository
