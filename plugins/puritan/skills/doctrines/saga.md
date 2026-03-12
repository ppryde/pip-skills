# Saga Pattern Doctrine

This doctrine audits saga implementations for distributed transactions, ensuring proper compensation logic, isolation handling, and coordination patterns in microservices architectures.

## When to Use

Use the saga pattern when you need distributed transactions across multiple services without using two-phase commit (2PC). Essential for maintaining data consistency in microservices where each service owns its database, long-running business processes that span multiple bounded contexts, and workflows requiring compensating actions on failure. [The saga pattern is an anti-pattern if used too frequently](https://dev.to/siy/the-saga-is-antipattern-1354) — it often indicates services organized around entities instead of business capabilities.

## Why Use It

Sagas enable distributed transactions without the scalability issues of 2PC. This provides:
- **Eventual consistency** across service boundaries without distributed locks
- **Failure recovery** via compensating transactions
- **Service autonomy** — each service commits its local transaction independently
- **Observable progress** — each step is visible for monitoring/debugging
- **Partial completion handling** — business logic can handle partially completed workflows

## Pros and Cons

| Pros | Cons |
|---|---|
| No distributed locks or 2PC coordination overhead | [Lack of isolation causes data anomalies](https://microservices.io/patterns/data/saga.html) |
| Each service can scale and fail independently | [No automatic rollback — must design compensating transactions](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga) |
| Business process visible as sequence of events/commands | [Cannot handle technical errors reliably](https://www.ufried.com/blog/limits_of_saga_pattern/) |
| Supports long-running workflows (hours/days) | Debugging distributed flows is complex |
| Natural audit trail of all steps and compensations | Testing requires all services running |
| Can implement complex business workflows | [Cyclic dependencies in choreography](https://medium.com/@dinesharney/implementing-the-saga-pattern-using-choreography-and-orchestration-53e66cbd520e) |

## Applicable Directories

Primary targets:
- `application/services/` — saga orchestrators and coordinators
- `domain/commands/` — saga step commands
- `domain/events/` — saga events and compensation triggers
- `infrastructure/messaging/` — saga message handlers
- `infrastructure/workflow/` — workflow engines (if using Temporal/Camunda)
- `api/sagas/` — saga initiation endpoints

## Violation Catalog

### Saga Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-001 | design | [Saga overuse indicates design smell](https://dev.to/siy/the-saga-is-antipattern-1354) | warning | >30% of use cases require sagas (services organized by entities) |
| SAG-002 | design | Missing saga definition | error | Distributed transactions without explicit saga coordinator or choreography |
| SAG-003 | design | Mixing orchestration and choreography | error | Same saga using both patterns (events AND commands from orchestrator) |
| SAG-004 | design | [Saga for technical errors](https://www.ufried.com/blog/limits_of_saga_pattern/) | error | Compensating transactions triggered by network/timeout errors |
| SAG-005 | design | No saga state machine | warning | Saga without explicit state transitions (PENDING→PROCESSING→COMPLETED/FAILED) |
| SAG-006 | design | Unbounded saga duration | warning | Sagas without timeout or maximum duration |
| SAG-007 | design | Nested sagas | error | Saga triggering another saga (composition complexity) |

### Compensation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-010 | compensation | [Missing compensating transaction](https://microservices.io/patterns/data/saga.html) | error | Saga steps without corresponding compensation logic |
| SAG-011 | compensation | Non-idempotent compensation | error | Compensating transactions without idempotency checks |
| SAG-012 | compensation | Compensation throws exceptions | error | Compensating transactions that can fail without retry |
| SAG-013 | compensation | Compensation order incorrect | error | Compensations not executed in reverse order |
| SAG-014 | compensation | No compensation timeout | warning | Compensating transactions without timeout handling |
| SAG-015 | compensation | Incomplete compensation | error | Compensation doesn't fully undo the forward action |
| SAG-016 | compensation | Compensation side effects | warning | Compensating transactions triggering new business logic |

### Isolation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-020 | isolation | [No isolation strategy](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices) | error | Concurrent sagas modifying same entities without countermeasures |
| SAG-021 | isolation | Missing semantic locks | warning | No application-level locks for business resources |
| SAG-022 | isolation | No dirty read prevention | warning | Reading uncommitted saga changes without versioning |
| SAG-023 | isolation | No saga correlation | error | Cannot track which changes belong to which saga |
| SAG-024 | isolation | Race condition in compensation | error | Compensation can race with normal operations |
| SAG-025 | isolation | No version checks | warning | Updates without checking if data changed during saga |

### Orchestration Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-030 | orchestration | [Single point of failure](https://blog.bytebytego.com/p/saga-pattern-demystified-orchestration) | warning | Orchestrator without high availability setup |
| SAG-031 | orchestration | Orchestrator contains business logic | error | Business rules in orchestrator instead of services |
| SAG-032 | orchestration | No orchestrator persistence | error | Orchestrator state only in memory |
| SAG-033 | orchestration | Synchronous orchestration | error | Orchestrator making blocking calls to services |
| SAG-034 | orchestration | No orchestrator monitoring | warning | No metrics/alerting for orchestrator health |
| SAG-035 | orchestration | Orchestrator versioning missing | warning | No strategy for upgrading running sagas |

### Choreography Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-040 | choreography | [Cyclic dependencies](https://medium.com/@dinesharney/implementing-the-saga-pattern-using-choreography-and-orchestration-53e66cbd520e) | error | Services consuming each other's events in cycles |
| SAG-041 | choreography | No event correlation | error | Events missing saga_id/correlation_id |
| SAG-042 | choreography | Implicit flow | warning | Saga flow not documented/discoverable |
| SAG-043 | choreography | [Complex choreography](https://www.baeldung.com/cs/saga-pattern-microservices) | warning | >4 services in choreographed saga |
| SAG-044 | choreography | Missing event handlers | error | Service not handling expected saga events |
| SAG-045 | choreography | Event ordering assumptions | error | Choreography assuming event order without guarantees |

### State Management Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-050 | state | No saga persistence | error | Saga state not persisted to durable storage |
| SAG-051 | state | State machine violations | error | Invalid state transitions (COMPLETED→PROCESSING) |
| SAG-052 | state | Lost saga instances | error | No mechanism to recover in-flight sagas after crash |
| SAG-053 | state | No saga history | warning | Cannot reconstruct what happened in saga |
| SAG-054 | state | Saga state in multiple places | error | State split across orchestrator and services |
| SAG-055 | state | No idempotency tokens | error | Saga steps without idempotency tokens |

### Testing & Operations Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| SAG-060 | testing | [No integration tests](https://medium.com/@serhatalftkn/implementing-the-saga-pattern-in-net-microservices-a-comprehensive-guide-9b2b1d1366b6) | error | Saga without end-to-end tests |
| SAG-061 | testing | No failure scenario tests | error | Tests don't cover compensation paths |
| SAG-062 | testing | No concurrent saga tests | warning | Tests don't verify isolation/conflicts |
| SAG-063 | operations | No saga observability | error | Cannot trace saga execution across services |
| SAG-064 | operations | No manual intervention | warning | No way to manually complete/compensate stuck sagas |
| SAG-065 | operations | No saga metrics | warning | No monitoring of saga success/failure rates |

## Allowed Exceptions

- **Technical error compensation (SAG-004):** Acceptable if wrapped in reliable infrastructure (e.g., Temporal) that handles retries
- **Complex choreography (SAG-043):** May be necessary for truly decentralized systems, but document the flow clearly
- **Synchronous steps (SAG-033):** Acceptable for read-only operations or when using circuit breakers
- **No semantic locks (SAG-021):** Acceptable if business naturally prevents conflicts (e.g., user-specific resources)
- **Nested sagas (SAG-007):** Can be valid for sub-workflows if carefully managed with clear boundaries

## Cross-Reference

This doctrine pairs well with:
- **messaging.md** — reliable message delivery for saga steps
- **event-sourcing.md** — event-driven choreography patterns
- **cqrs.md** — command handling in saga participants
- **resilience.md** — circuit breakers, retries for saga steps
- **monitoring.md** — distributed tracing for saga flows

## Sources and Authority

Based on authoritative saga pattern sources:

**Foundational Works:**
- [Microservices.io - Saga Pattern](https://microservices.io/patterns/data/saga.html) — Chris Richardson's definitive guide
- [Microsoft - Saga Design Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga) — Azure architecture guidance
- [AWS - Saga Patterns](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga.html) — AWS prescriptive guidance

**Implementation Approaches:**
- [Saga Pattern Demystified: Orchestration vs Choreography](https://blog.bytebytego.com/p/saga-pattern-demystified-orchestration) — ByteByteGo comparison
- [Implementing Saga with Choreography and Orchestration](https://medium.com/@dinesharney/implementing-the-saga-pattern-using-choreography-and-orchestration-53e66cbd520e) — Practical comparison
- [Temporal - Mastering Saga Patterns](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices) — Modern tooling approach

**Anti-Patterns & Limitations:**
- [The Saga is Antipattern](https://dev.to/siy/the-saga-is-antipattern-1354) — When saga indicates design problems
- [The Limits of the Saga Pattern](https://www.ufried.com/blog/limits_of_saga_pattern/) — Technical error handling issues
- [Saga Pattern Guide 2024](https://medium.com/@noahblogwriter2025/saga-pattern-distributed-transactions-microservices-34296bd513df) — Recent pitfalls

**Practical Guides:**
- [Baeldung - Saga Pattern in Microservices](https://www.baeldung.com/cs/saga-pattern-microservices) — Implementation guide
- [Implementing Saga in .NET](https://medium.com/@serhatalftkn/implementing-the-saga-pattern-in-net-microservices-a-comprehensive-guide-9b2b1d1366b6) — .NET specifics
- [Managing Distributed Transactions](https://dev.to/willvelida/the-saga-pattern-3o7p) — DEV Community guide
- [Solving Distributed Transactions with Temporal](https://medium.com/skyro-tech/solving-distributed-transactions-with-the-saga-pattern-and-temporal-27ccba602833) — Temporal approach
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest the Saga pattern is in use):
- `sagas/` or `application/sagas/` — saga definitions
- `orchestrators/` — saga orchestrator classes
- `compensations/` or `domain/compensations/` — compensation / rollback logic
- `infrastructure/workflow/` — workflow engine integration (Temporal, Camunda, Conductor)

### File signals
Strong indicators (any 1 is significant):
- Files named `*Saga.*` anywhere in the codebase
- Files named `*Orchestrator.*` containing multi-step coordination logic
- Files named `*Compensation.*` or `*Rollback.*`
- Workflow definition files (`.workflow.yml`, Temporal workflow descriptors, Camunda BPMN)
- Files named `*SagaStep.*` or `*SagaState.*`

### Anti-signals
Suggest the Saga pattern is NOT in use:
- No saga, orchestrator, or compensation directory
- Distributed operations with no rollback or compensation mechanism
- Simple synchronous service-to-service calls with no multi-step coordination
- All transactions handled within a single database boundary
