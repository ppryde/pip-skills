# Strategy Pattern Doctrine

The Strategy doctrine audits the correct application of the Strategy behavioral pattern — swappable implementations behind a shared interface — ensuring that algorithms, infrastructure runners, and execution policies remain interchangeable without touching the code that depends on them.

**Language Scope:** Language-agnostic

## When to Use

Use the Strategy pattern wherever you have a family of interchangeable behaviors, algorithms, or infrastructure implementations that must be selectable at configuration time or runtime without altering the client code. Typical targets include: background job executors (inline vs. queued), storage backends (local filesystem vs. S3), payment processors, notification channels, rate-limiting policies, and serialization formats.

**Do NOT use this pattern** when there is only one known implementation and no realistic prospect of a second. A single-implementation interface is speculative abstraction — it adds indirection without delivering the swap-ability that justifies Strategy. Do not apply Strategy to stateful workflows where the chosen behavior changes in response to internal state transitions — that is the State pattern, not Strategy. Do not use Strategy as a plugin registry or composite: if the client iterates over all implementations rather than selecting one, that is the Chain of Responsibility or Composite pattern — the defining property of Strategy is that exactly one implementation is active at a time.

## Why Use It

- **Infrastructure swap without service changes** — Migrate from an in-process runner to a queued worker by swapping one injected dependency; no business logic changes.
- **Testability** — Inject a deterministic fake strategy in tests; no mocking of I/O.
- **Open/Closed compliance** — Add new implementations (new strategy) without modifying the client or existing strategies.
- **Explicit configuration boundary** — The selection of which strategy to use becomes a single, auditable configuration decision rather than scattered conditionals.
- **Parallel development** — Teams can build strategy implementations independently behind the agreed interface.
- **Deferred infrastructure decisions** — Use a simple synchronous implementation until scale demands the queued alternative, then swap without rework.

## Pros and Cons

| Pros | Cons |
|---|---|
| Client code never changes when adding or swapping implementations | Adds at least one interface/abstract class per strategy family — real boilerplate cost |
| Implementations are independently testable with no shared state | Can be over-engineered for problems with a single stable implementation ([Fowler: "beware risky complexity"](https://martinfowler.com/bliki/DesignStaminaHypothesis.html)) |
| Strategy selection is explicit and centralised (DI config, factory, env var) | Callers must receive the strategy via injection — requires DI discipline across the codebase |
| Each implementation can be evolved, profiled, and replaced in isolation | If the interface is poorly designed, all implementations carry the same design flaw |
| Eliminates if/else/switch dispatch on type within client code | Proliferation of small classes can obscure the dominant code path during debugging |
| Enables A/B testing of implementations in production with zero service downtime | Runtime strategy selection adds a layer of indirection that can surprise new contributors |

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):
- `infrastructure/runners/` — concrete strategy implementations for job execution or processing backends
- `infrastructure/adapters/` — pluggable external-system adapters (storage, notifications, queues)
- `application/services/` — client code that holds a strategy reference; must depend on the interface, not an implementation
- `domain/ports/` or `ports/` — the strategy interface definitions (abstract classes / protocols)
- `config/` or `bootstrap/` — the single location where the active strategy implementation is selected and wired
- `workers/` — background processing implementations that may be strategies

## Violation Catalog

### Interface Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-001 | interface-design | Strategy interface must be abstract — no concrete logic in the base | error | Base/parent strategy class containing method bodies with executable statements — abstract interfaces should declare method signatures only, with no implementation (language examples: empty body, `abstract` keyword, or protocol declaration — any non-trivial body is a violation) |
| STG-002 | interface-design | Strategy interface must be minimal — one focused capability per interface | warning | Strategy interface or abstract class declaring more than 8 methods, or declaring methods across more than one distinct responsibility (e.g. mixing execution methods with configuration accessors or lifecycle hooks) — the method-count threshold is a proxy; the real violation is mixed concerns on a single interface |
| STG-003 | interface-design | Strategy interface must not leak implementation details in method signatures | error | Method parameters named after specific backends (e.g. `redis_client`, `sqs_queue`, `celery_app`) in the interface definition |
| STG-004 | interface-design | Strategy interface must not import from concrete infrastructure | error | Interface/abstract class file containing import statements referencing concrete infrastructure sub-packages (e.g. `infrastructure/celery`, `infrastructure/redis`, or equivalent technology-named modules) |
| STG-005 | interface-design | Strategy interface must be named after capability, not implementation | warning | Interface or abstract class names containing technology-specific words (e.g. `CeleryRunner`, `S3Storage`, `RedisCache` used as the interface name) |

**Scanning approach:** The interface file is the contract. Any concrete detail in it — import, parameter name, method body — is a boundary violation.

### Client Coupling Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-010 | client-coupling | Client must depend on the strategy interface, not a concrete implementation | error | Constructor, function signature, or attribute declaration in `application/` or `domain/` that names a concrete strategy class rather than the interface |
| STG-011 | client-coupling | Client must not instantiate concrete strategies internally | error | Constructor invocation of a known concrete strategy class name inside a client class method body (outside `config/`, `bootstrap/`, or factory modules) — look for the concrete class name followed by a call expression |
| STG-012 | client-coupling | Client must not use runtime type inspection to switch on strategy type | error | Type-check expressions against a concrete strategy class name in client code — e.g. `instanceof`, `isinstance`, `typeof`, `is_a`, or equivalent — followed by conditional logic branching on the result |
| STG-013 | client-coupling | Client must not import concrete strategy modules | error | Import of concrete strategy class in client file (files outside `config/`, `bootstrap/`, or factory modules) |
| STG-014 | client-coupling | Strategy must be injected, not fetched from a global registry | warning | Client calling a global `get_runner()`, `registry.get()`, or singleton accessor to obtain its strategy mid-method |

**Scanning approach:** Any direct reference to a concrete strategy type inside client code is the canonical smell. Focus on constructor parameters and method bodies in service/application layer files.

### Strategy Implementation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-020 | implementation | Concrete strategy must implement all methods of the interface | error | AST check: concrete strategy class that does not declare all method names present on the abstract base/interface — grep-proxy: methods listed in the interface file absent from the concrete file |
| STG-021 | implementation | Concrete strategies must not call each other | warning | One concrete strategy class importing or instantiating another concrete strategy class from the same family |
| STG-022 | implementation | Concrete strategy must not access client/context internals | error | Strategy implementation directly importing or referencing the client class that holds it |
| STG-023 | implementation | Each concrete strategy must be independently deployable — no shared mutable class-level state | error | Class-level variable declared outside any instance initialiser (constructor or equivalent) and assigned a mutable default (list, dict/map, set literal, or object); or `static` field declaration on a concrete strategy class |
| STG-024 | implementation | Strategy implementation complexity must be bounded | warning | Concrete strategy method exceeding 80 lines (grep/line-count detectable); cyclomatic complexity > 10 requires static analysis tooling (e.g. `radon`, `lizard`) — either signal indicates the strategy is doing too much |
| STG-025 | implementation | Strategy must not silently swallow errors | error | Empty or bare error-handling block inside a concrete strategy method body — a catch/except clause that contains no re-raise, no logging call, and no meaningful recovery action (e.g. empty `catch {}`, a catch block containing only a comment, or a catch body whose only statement is a no-op) |

**Scanning approach:** Each concrete strategy should be narrow, independent, and behaviorally complete on its own. Cross-strategy dependencies and shared state are the primary failure modes.

### Selection and Wiring Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-030 | selection-wiring | Strategy selection must occur in one place — not scattered across the codebase | error | Conditional blocks selecting a concrete strategy class outside of `config/`, `bootstrap/`, or a dedicated factory file |
| STG-031 | selection-wiring | Strategy selection must not be hard-coded in production code | error | Concrete strategy class names hard-coded as string literals in non-config files (e.g. `runner = "InlineRunner"` in service code) |
| STG-032 | selection-wiring | A fallback or default strategy must be explicitly declared | warning | No default assignment for the strategy in factory or DI config — absent default causes a null-reference or missing-binding error at runtime |
| STG-033 | selection-wiring | Strategy must be wired at application start, not lazily in hot paths | warning | Constructor calls to a concrete strategy class inside request handlers or consumer loop methods |
| STG-034 | selection-wiring | DI container must register each concrete strategy explicitly | warning | Concrete strategy class present in `infrastructure/` with no corresponding DI registration in `config/` or `bootstrap/` — exempt when the DI framework uses auto-discovery or scan-based registration (e.g. Spring component scan, some Python DI frameworks), provided the discovery convention is consistently applied and documented |

**Scanning approach:** The factory or DI bootstrap file is the single source of truth for which implementation is active. Any strategy instantiation found elsewhere is a selection-wiring violation.

### Context Object Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-040 | context-design | Context must not pass itself into the strategy | warning | `self` or `this` passed as an argument in a strategy method call inside the client (e.g. `self.strategy.run(self)`) |
| STG-041 | context-design | Strategy must receive only the data it needs — not the full context object | warning | Strategy method parameter whose declared type matches the client class that holds this strategy as a field — detectable by cross-referencing: if a strategy method's parameter type name appears as a class that itself declares this strategy type as an attribute, the full context is being passed in; simpler grep-level proxy: flag strategy method parameters whose declared type name ends in `Service`, `Client`, `Context`, or `Manager` |
| STG-042 | context-design | Context must not expose internal state for the strategy's benefit | warning | Public getter or property on a client class that is referenced only inside strategy files — detectable by cross-referencing property name usage: if the only call sites are in `infrastructure/` strategy files and not in `application/` or `domain/`, the property exists solely for the strategy |
| STG-043 | context-design | Strategy must not mutate the context's state directly | error | Strategy implementation writing to fields of the context/client object (e.g. `context.status = ...`, `client.result = ...`) |

**Scanning approach:** Context leakage is subtle — look for method signatures where the client class is itself a parameter, and for public properties that only exist to serve one strategy.

### Naming and Discoverability Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-050 | naming | Concrete strategy classes must include a discriminating suffix or prefix | warning | Concrete strategy class names that do not end in `Runner`, `Strategy`, `Policy`, `Adapter`, or `Executor` (or an equivalent domain term); `Handler` is permitted only when the strategy is clearly performing a handling role — flag it when `Handler` is ambiguous with event or HTTP handler contexts |
| STG-051 | naming | Strategy family members must share a common base name | warning | Concrete strategies for the same family using unrelated names (e.g. `InlineExecutor` and `QueueDispatchService` for the same interface) — detection requires cross-referencing: group all classes implementing the same interface, then check whether their names share a common suffix or prefix; single-file grep cannot detect this — Inquisition must resolve the shared interface first |
| STG-052 | naming | Interface file must not be named after a concrete implementation | error | Interface/abstract class file named after a specific technology (e.g. `celery_runner`, `s3_storage`, `redis_cache`) in the ports or interface directory — regardless of file extension |

**Scanning approach:** Consistent naming is a discoverability requirement. When a developer searches for "all runners," inconsistent suffixes mean some implementations won't surface.

### Testing Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-060 | testability | Each concrete strategy must have its own unit test file | warning | Concrete strategy class with no corresponding test file (`test_<strategy_name>.*` or `<strategy_name>_test.*`) |
| STG-061 | testability | Client tests must use a fake or stub strategy, not a concrete implementation | warning | Test files for client/service classes importing a concrete strategy implementation directly rather than a fake or stub |
| STG-062 | testability | A null/no-op strategy must exist for testing contexts where the side effect is irrelevant | warning | Two or more concrete strategy classes exist in `infrastructure/` but no file matching `Fake*`, `Stub*`, `Noop*`, or `InMemory*` exists anywhere in the test directories for the same strategy family |
| STG-063 | testability | Strategy interface compliance must be verified via a contract test | warning | No test file that exercises all methods declared on the strategy interface against each concrete implementation — look for a shared abstract test class, a parametrized test fixture, or a test that imports multiple concrete strategy classes and calls the same method on each |

**Scanning approach:** The central promise of Strategy is testability. Any test file that imports a concrete strategy to test the client has forfeited that promise.

### Anti-Pattern Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| STG-070 | anti-pattern | Strategy with exactly one implementation and no test fake must be removed — it is speculative abstraction | warning | Interface with one concrete implementation and no `Fake*`/`Stub*`/`InMemory*` test double in the codebase |
| STG-071 | anti-pattern | Do not confuse Strategy with State — Strategy is selected at injection time, not mid-execution | warning | Strategy implementation that reassigns which strategy is active — an assignment to the context's strategy field from within a strategy method body (e.g. `context.strategy = OtherStrategy()`) |
| STG-072 | anti-pattern | Strategy must not contain selection logic that delegates to a sibling strategy | error | Concrete strategy class with conditional logic that instantiates or calls a sibling concrete strategy |
| STG-073 | anti-pattern | Strategies must not be aware of each other by name | error | Concrete strategy file importing a sibling concrete strategy class |
| STG-074 | anti-pattern | Do not version strategies via subclassing — create a new class implementing the interface instead | warning | Concrete strategy class whose parent is another concrete strategy rather than the shared interface or abstract base (e.g. `QueueRunnerV2` extending `QueueRunner` instead of `JobRunner`) |

**Scanning approach:** Anti-patterns are often hiding in plain sight as "sensible shortcuts." STG-072 and STG-073 are the most common; they signal the interface has been bypassed rather than respected.

## Allowed Exceptions

- **Bootstrap/Factory files:** Concrete strategy instantiation and direct class references are permitted in `config/`, `bootstrap/`, DI container setup, and factory modules — these are the designated selection points.
- **Test files:** Concrete strategy imports are permitted in test files that test that specific strategy class. The violation is importing a concrete strategy into a client/service test file.
- **Single-file scripts and CLIs:** Scripts outside of a shared application core may select a strategy inline. The doctrine targets shared service code, not standalone scripts.
- **Framework-mandated signatures:** When a framework (e.g. Celery, Dramatiq) requires a specific function signature, the adapting strategy class may carry framework-specific parameter types — annotate with a comment explaining the constraint.
- **Observability:** Strategies may accept an injected logger or tracer as a constructor argument even if the interface does not declare it, provided logging does not alter the behavioral contract.
- **STG-070 (roadmap-committed second implementation):** A single-implementation interface is acceptable as a forward declaration when a second implementation is roadmap-committed — document the intent with an inline comment in the interface file.

## Cross-Reference

This doctrine pairs well with:
- **hexagonal.md** — Strategy implementations are a category of Driven Adapter; hexagonal.md governs the broader port/adapter boundary that Strategy implementations live within.
- **resilience.md** — Circuit breaker and retry policies are frequently implemented as strategies; resilience.md governs what those strategies must contain.
- **messaging.md** — Background job runners (the motivating example) are strategies over a messaging infrastructure; messaging.md governs the message contracts those runners handle.
- **ddd.md** — Domain policies (pricing, discounting, validation rules) are a common Strategy application within a DDD domain layer.
- **testing.md** — Validates that strategy-holding clients are tested via fakes, and that contract tests exist per strategy interface.
- **dependency-injection.md** — Governs the DI container configuration that wires the active strategy — the selection-wiring rules in this doctrine assume a DI-based runtime.

## Sources and Authority

**Foundational Works:**
- [Gamma, Helm, Johnson, Vlissides — Design Patterns: Elements of Reusable Object-Oriented Software (1994)](https://www.oreilly.com/library/view/design-patterns-elements/0201633612/) — Original GoF definition: "Define a family of algorithms, encapsulate each one, and make them interchangeable. Strategy lets the algorithm vary independently from clients that use it." The GoF chapter also defines the Context, Strategy interface, and ConcreteStrategy triad that underpins the violation categories here.
- [Martin Fowler — Refactoring: Improving the Design of Existing Code (1999, 2018)](https://martinfowler.com/books/refactoring.html) — Documents "Replace Conditional with Strategy" as a canonical refactoring; establishes that the pattern's value scales with the number of implementations and the frequency with which they change.

**Practitioner Guidance:**
- [Lindsey Broos — Using the Strategy Pattern with Dependency Injection (2024)](https://lindseybroos.be/blog/2024/strategy-pattern/) — Practitioner account of wiring Strategy implementations via a DI container; identifies the "remember to register every new concrete class" failure mode (the source of STG-034).
- [Stackify — Strategy Pattern: Definition, Examples, and Best Practices](https://stackify.com/strategy-pattern-definition-examples-and-best-practices/) — Broad best-practice survey covering interface design, naming, and testability considerations. (Author/date unattributed; treat as secondary practitioner reference.)

**Reference:**
- [Refactoring.Guru — Strategy Pattern](https://refactoring.guru/design-patterns/strategy) — Modern language-illustrated walkthrough; good companion for identifying the pattern structure during codebase discovery.

**Anti-Patterns / Failure Cases:**
- [DEV Community — Strategy Design Pattern with Dependency Injection](https://dev.to/davidkroell/strategy-design-pattern-with-dependency-injection-7ba) — Documents the canonical violation: `PaymentService` hard-coding concrete strategy instantiation inside if/else blocks, coupling the client to implementations, violating Open/Closed, and making the service untestable. This directly motivates STG-010 through STG-013.

## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest the Strategy pattern is in use):
- `infrastructure/runners/` — named directory for swappable job or task execution backends
- `infrastructure/adapters/` — pluggable external-system implementations behind shared interfaces
- `domain/ports/` or `ports/` alongside `infrastructure/runners/` or `infrastructure/adapters/` — interface definitions paired with concrete implementations (bare `ports/` alone is not discriminating; it also appears in Hexagonal architecture)
- `config/` or `bootstrap/` alongside `infrastructure/runners/` or `infrastructure/adapters/` — a wiring point paired with a strategy implementation directory (bare `config/` alone is not discriminating)
- `workers/` alongside `application/services/` — background processing implementations beside orchestrating clients

### File signals
Strong indicators (any 1 is significant):
- Files named `*Runner.*`, `*Strategy.*`, `*Policy.*`, or `*Executor.*` specifically inside `infrastructure/`, `adapters/`, or `workers/` directories — concrete strategy implementations (this signal is too broad in `domain/` or root directories where these suffixes are common)
- A single abstract class or protocol file in `ports/` or `interfaces/` declaring one to five abstract methods with no concrete logic — the canonical strategy interface contract; this is the strongest single-file fingerprint
- A `Fake*`, `Stub*`, or `InMemory*` file in test directories whose name mirrors a production strategy suffix (e.g. `FakeJobRunner`, `InMemoryStorageAdapter`) — confirms the pattern is being tested correctly

### Anti-signals
Suggest the Strategy pattern is NOT in use (or is being violated):
- If/else or switch blocks selecting a concrete class by name in service/application files — suggests inline selection rather than injected strategy (leans Procedural or Big Ball of Mud)
- No abstract base class, interface, or protocol file corresponding to the concrete runner/adapter classes — implementations exist without a shared contract (leans ad-hoc polymorphism or Layered N-Tier with no port layer)
- Concrete runner classes importing sibling concrete runners — suggests the abstraction has been bypassed entirely (leans tightly coupled procedural decomposition)
