# Event Sourcing Doctrine

This doctrine audits event sourcing implementation for correctness, performance, and
maintainability. Grounded in best practices from Greg Young, Martin Fowler, and
Microsoft CQRS/ES guidance.

## When to Use

Use event sourcing when you need immutable audit trails, temporal queries
(what was the state on date X?), retroactive corrections, or complex business
flows that benefit from event-driven architecture. Essential for financial
systems, regulatory compliance, multi-step workflows with compensations, and
systems where "what happened" is as important as "what is." Not recommended
for simple CRUD or high-volume sensor data without aggregation.

## Why Use It

Event sourcing provides a complete history of state changes, not just current
state. This enables:
- **Audit trail by default** — every change is an immutable event with who/when/why
- **Time travel** — reconstruct state at any point in history
- **Retroactive fixes** — replay events with updated logic to fix past bugs
- **Event-driven integration** — other systems subscribe to domain events
- **Debugging superpowers** — replay exact sequence that led to a bug
- **Projection flexibility** — create new read models without migrating data

## Pros and Cons

| Pros | Cons |
|---|---|
| Complete audit trail with zero additional effort | Eventually consistent projections (unless sync) |
| Temporal queries — "what was the balance on Jan 1?" | Event schema evolution requires careful planning |
| Can retroactively fix bugs by replaying with new logic | Storage grows forever (mitigated by snapshots) |
| Natural integration point via domain events | Complex queries require projections, not direct event queries |
| Enables event-driven architecture patterns | Learning curve — different mental model from CRUD |
| Parallel read models optimized for different queries | Debugging requires understanding event sequences |

## Applicable Directories

Primary targets:
- `domain/aggregates/` — event emission and replay
- `domain/events/` — event design and schema
- `infrastructure/event_store/` — persistence and publishing
- `infrastructure/projectors/` — projection updates
- `application/services/` — orchestration patterns
- `scripts/` — rebuild and migration scripts

## Violation Catalog

### Event Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-100 | event-design | Events must be immutable | error | Event classes without `frozen=True` config, or mutable fields, or setter methods |
| EVS-101 | event-design | Events need globally unique IDs | error | Events without unique identifiers (UUID v4/v7, ULID, or sequential per aggregate) |
| EVS-102 | event-design | Event names must be past tense | warning | Event class names not in past tense (e.g., `CreateLoan` instead of `LoanCreated`) |
| EVS-103 | event-design | Events must extend base event class | error | Event classes not inheriting from `DomainEvent` or equivalent base class |
| EVS-104 | event-design | Events must auto-register | warning | Event classes without `__init_subclass__` registration or manual registry entry |
| EVS-105 | event-design | Events need occurred_at timestamp | error | Events missing `occurred_at` field with timezone-aware datetime |
| EVS-106 | event-design | Avoid large event payloads | warning | Event classes with >20 fields or storing full aggregate state instead of deltas |
| EVS-107 | event-design | Event cascade loops | error | Events that directly trigger other events without command mediation (infinite loop risk) |
| EVS-108 | event-design | Over-granular events | warning | Storing every field change as separate event (e.g., NameChanged, EmailChanged vs UserUpdated) |

### Event Sourcing Flow Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-110 | flow | Events must be persisted before publishing | error | Service methods that call `bus.publish()` before `store.append_events()` |
| EVS-111 | flow | Uncommitted events must be cleared after save | error | Missing `aggregate.clear_uncommitted()` after successful `append_events()` |
| EVS-112 | flow | Events published outside transaction boundary | warning | Event publishing inside database transaction blocks (should be after commit) |
| EVS-113 | flow | Missing optimistic concurrency control | error | EventStore without catching unique violations or version conflicts on append |
| EVS-114 | flow | Synchronous projections blocking writes | warning | Projector handlers called within write transaction (should be async or after) |

### Event Replay Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-120 | replay | Event handlers must be idempotent | error | Handlers using `+=`, `.append()` without checking for duplicates, or lacking event_id tracking |
| EVS-121 | replay | Replay must be deterministic | error | Event handlers using `datetime.now()`, `random`, or external service calls |
| EVS-122 | replay | from_events() must not emit new events | error | `from_events()` or replay methods that add to uncommitted events list |
| EVS-123 | replay | Event handlers must use _when_* naming | warning | Public methods handling events, or handlers not following `_when_<event_name>` pattern |
| EVS-124 | replay | Missing handler for registered event | warning | Event type in registry but no corresponding `_when_*` method in any aggregate |
| EVS-125 | replay | Handler mutating state without event | error | `_when_*` methods that change state but aggregate method doesn't emit event first |

### Snapshot Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-130 | snapshot | Snapshots must include last_event_id | error | `to_snapshot()` not including last_event_id, or `from_snapshot()` not restoring it |
| EVS-131 | snapshot | Decimal fields must serialize as strings | error | Snapshot methods using `float(decimal_value)` instead of `str(decimal_value)` |
| EVS-132 | snapshot | Snapshot load must have fallback | error | Snapshot loading without try/catch fallback to full event replay |
| EVS-133 | snapshot | Snapshots need periodic cleanup | warning | No cleanup of old snapshots (should keep only N most recent per aggregate) |
| EVS-134 | snapshot | Snapshot interval not configured | warning | No snapshot interval config ([Young: every 50-100 events typical](https://www.youtube.com/watch?v=JHGkaShoyNs)) |
| EVS-135 | snapshot | from_snapshot() must validate invariants | warning | `from_snapshot()` that doesn't validate business rules after reconstruction |

### Projection Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-140 | projection | Projectors must be idempotent | error | Missing `last_event_id` check or `ON CONFLICT DO NOTHING` in projector handlers |
| EVS-141 | projection | Projections storing domain logic | error | Projections with business methods beyond simple getters (logic belongs in aggregates) |
| EVS-142 | projection | Missing projection rebuild script | warning | No script to rebuild projections from event stream |
| EVS-143 | projection | Projectors modifying event data | error | Projector handlers that mutate the event object instead of just reading it |
| EVS-144 | projection | Synchronous projector without error handling | error | Projector in sync path that can crash the write operation on failure |
| EVS-145 | projection | Projector accessing external services | warning | Projectors making HTTP calls or accessing external DBs (couples availability) |

### Event Store Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-150 | store | Event store allows event mutation | error | Event store with UPDATE/DELETE permissions on event table |
| EVS-151 | store | Missing event serialization registry | error | No registry mapping event_type strings to event classes for deserialization |
| EVS-152 | store | Events stored without aggregate_type | error | Event records missing aggregate_type field (needed for filtering) |
| EVS-153 | store | No batch loading support | warning | EventStore without methods to load multiple aggregates in single query |
| EVS-154 | store | No event ordering strategy | error | No way to order events (via timestamp, sequence number, or time-ordered IDs) |
| EVS-155 | store | No event versioning strategy | warning | No version field or schema migration plan for event evolution |

### Event Schema Evolution Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-160 | evolution | Breaking event schema changes | error | Removing fields from events, renaming without alias, changing field types |
| EVS-161 | evolution | New required fields without defaults | error | Adding non-nullable fields to events without default values |
| EVS-162 | evolution | Missing backward-compatible aliases | warning | Renamed events without keeping old handler name as alias (e.g., `_when_payment_received = _when_repayment_received`) |
| EVS-163 | evolution | Event upcasting not documented | warning | Schema migrations without documentation of how old events map to new structure |

### Performance Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| EVS-170 | performance | Loading aggregates without snapshots | warning | Services loading aggregates with >100 events but no snapshot support |
| EVS-171 | performance | N+1 queries loading aggregates | error | Service loops calling `load_aggregate()` instead of using batch loading |
| EVS-172 | performance | Unbounded event queries | warning | Queries fetching all events without pagination or date ranges |
| EVS-173 | performance | Missing indexes on event queries | warning | No indexes on (aggregate_id, event_id), (aggregate_type, occurred_at) pairs |
| EVS-174 | performance | Snapshot on every save | warning | Taking snapshots too frequently (every event) instead of at intervals |
| EVS-175 | performance | Event sourcing applied universally | error | Using ES for entire app ([Young: "not a top-level architecture"](https://www.kurrent.io/blog/transcript-of-greg-youngs-talk-at-code-on-the-beach-2014-cqrs-and-event-sourcing)) |

## Allowed Exceptions

- **Fire-and-forget snapshots (EVS-114):** Snapshot failures shouldn't block writes.
  Log and monitor, but don't fail the write transaction.
- **Fire-and-forget async publishing:** RabbitMQ publishing failures shouldn't
  fail writes if events are safely in the store. The store is the source of truth.
- **Event IDs (EVS-101):** UUID v4, UUID v7, ULID, KSUID, or sequential integers
  per aggregate are all valid. The key is uniqueness and having SOME ordering
  strategy (timestamp, sequence number, or time-ordered IDs).
- **Sync projections (EVS-114):** Acceptable for critical read-after-write
  consistency requirements. Just ensure error handling doesn't break writes.
- **Historic events:** Events with `is_historic=true` and `event_date_override`
  are exempt from "must use current time" rules since they represent past facts.
- **Selective application (EVS-175):** Event sourcing should be applied to specific
  bounded contexts where audit trails, temporal queries, or event-driven integration
  provide value. Not every entity needs event sourcing.

## Cross-Reference

This doctrine pairs well with:
- **ddd.md** — ensures aggregates emit events correctly, handlers follow patterns
- **cqrs.md** — covers projection design, read/write separation (mandatory with ES)
- **saga.md** — covers process managers, compensating transactions (if applicable)
- **messaging.md** — covers message broker integration, delivery guarantees

## Sources and Authority

Based on industry best practices from:
- [Greg Young's CQRS and Event Sourcing talks](https://www.kurrent.io/blog/transcript-of-greg-youngs-talk-at-code-on-the-beach-2014-cqrs-and-event-sourcing)
- [Martin Fowler's Event Sourcing patterns](https://martinfowler.com/tags/event%20architectures.html)
- [Event Sourcing anti-patterns and pitfalls](https://event-driven.io/en/anti-patterns/)
- [Event Sourcing failures: Real-world lessons](https://kitemetric.com/blogs/event-sourcing-fails-5-real-world-lessons)
- [UUID v7 vs v4 for event IDs](https://tiagogalvao.com/uuids-in-microservices-v4-vs-v7-what-you-should-know/)
- [Microsoft Event Sourcing guidance](https://learn.microsoft.com/azure/architecture/patterns/event-sourcing)

## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest Event Sourcing is in use):
- `infrastructure/event_store/` or `event-store/` or `eventstore/` — append-only event log persistence
- `domain/events/` — event schema and contract definitions
- `domain/aggregates/` — event-emitting aggregate roots
- `infrastructure/projectors/` or `projectors/` — state-rebuilding projection handlers
- `scripts/rebuild/` or `scripts/migration/` — event replay and migration tooling
- `snapshots/` or `infrastructure/snapshots/` — snapshot storage

### File signals
Strong indicators (any 1 is significant):
- Files named `*EventStore.*` or `*EventRepository.*`
- Files named `*Snapshot.*` alongside event files
- Files named `*Projector.*` or `*ProjectionBuilder.*`
- Files named `*EventStream.*` or `*EventLog.*`
- Files named `*Replayer.*` or `*EventReplayer.*`

### Anti-signals
Suggest Event Sourcing is NOT in use:
- Standard mutable ORM models with no event log or append-only store
- No event store directory or event persistence layer
- Repository classes that update records in place (no append-only pattern visible)
- No projection or snapshot infrastructure
