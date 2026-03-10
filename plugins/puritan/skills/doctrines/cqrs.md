# CQRS Doctrine

This doctrine audits Command Query Responsibility Segregation implementation, ensuring
proper separation of read and write models without unnecessary complexity.

## When to Use

Use CQRS when you have complex domains with different optimization needs for
reads vs writes, collaborative systems where many users access the same data,
task-based UIs that model business processes, or when read/write loads differ
significantly. CQRS is overkill for simple CRUD systems and adds risky
complexity to most applications ([Fowler warns: "beware that for most systems
CQRS adds risky complexity"](https://martinfowler.com/bliki/CQRS.html)).

## Why Use It

CQRS allows you to optimize read and write models independently. Write models
focus on business logic and consistency, while read models optimize for query
performance and denormalization. This separation enables:
- Independent scaling of reads and writes
- Different storage technologies (event store for writes, document DB for reads)
- Task-based commands that capture intent, not CRUD
- Eventually consistent projections optimized for specific views

## Pros and Cons

| Pros | Cons |
|---|---|
| Read and write models independently optimized | Eventually consistent read models (unless using sync projections) |
| Commands capture business intent, not data changes | [Data synchronization risks and race conditions](https://www.techtarget.com/searchapparchitecture/tip/Common-CQRS-pattern-problems-and-how-teams-can-avoid-them) |
| Enables event sourcing naturally | Significant complexity for simple domains |
| Different teams can own read vs write sides | Debugging requires understanding both models |
| Read models can use denormalized/cached data | More infrastructure to maintain |
| Supports multiple read models for different views | [Can lead to serious difficulties if misapplied](https://martinfowler.com/bliki/CQRS.html) |

## Applicable Directories

Primary targets:
- `domain/commands/` — command definitions
- `domain/aggregates/` — write model (command handlers)
- `infrastructure/projections/` — read models
- `infrastructure/projectors/` — projection builders
- `application/services/` — command/query dispatchers
- `api/` — command and query endpoints

## Violation Catalog

### Command Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-200 | command-design | Commands must be task-based | warning | Commands named like `UpdateEntity`, `SetField` instead of business tasks like `ApproveLoan`, `SubmitOrder` |
| CQR-201 | command-design | Commands must not return query data | error | Command handlers returning domain data beyond ID/version ([CQS principle](https://en.wikipedia.org/wiki/Command%E2%80%93query_separation)) |
| CQR-202 | command-design | Commands must be immutable | error | Command classes with public setters or mutable fields |
| CQR-203 | command-design | One command per business operation | warning | Multiple commands to complete single business transaction |
| CQR-204 | command-design | Commands must have clear intent | warning | Generic commands like `ProcessData` or `HandleRequest` |
| CQR-205 | command-design | Commands should not contain logic | warning | Business logic in command classes instead of handlers |

### Query Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-210 | query-design | Queries must not mutate state | error | Query handlers that modify database/aggregate state |
| CQR-211 | query-design | Queries should use read models | warning | Queries reconstructing state from event stream instead of projections |
| CQR-212 | query-design | Query models should be denormalized | warning | Read models with multiple JOINs or complex aggregations |
| CQR-213 | query-design | Queries must be side-effect free | error | Query handlers triggering events, sending emails, or calling external APIs |
| CQR-214 | query-design | Avoid N+1 queries | error | Loops fetching related data one-by-one instead of batch loading |

### Separation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-220 | separation | Write models in read operations | error | Query handlers accessing aggregates or write model tables |
| CQR-221 | separation | Read models accepting commands | error | Projections/read models with methods that modify state |
| CQR-222 | separation | Shared models between read/write | warning | Same class/table used for both commands and queries |
| CQR-223 | separation | Direct aggregate queries | error | API endpoints querying aggregates instead of projections |
| CQR-224 | separation | [Write-through cache antipattern](https://www.techtarget.com/searchapparchitecture/tip/Common-CQRS-pattern-problems-and-how-teams-can-avoid-them) | error | Updating read model synchronously in command handler |

### Consistency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-230 | consistency | Missing eventual consistency handling | error | No retry/compensation for failed projection updates |
| CQR-231 | consistency | Assuming immediate consistency | error | Commands followed immediately by queries expecting updated data |
| CQR-232 | consistency | No consistency boundary | warning | Transactions spanning multiple aggregates |
| CQR-233 | consistency | Projection lag not handled | warning | UI not accounting for eventual consistency delays |
| CQR-234 | consistency | Missing idempotency | error | Projectors without duplicate event handling |

### Infrastructure Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-240 | infrastructure | Same database for read/write | warning | Commands and queries using same tables (may be valid for simple cases) |
| CQR-241 | infrastructure | No command/query routing | error | Direct aggregate access instead of command/query bus |
| CQR-242 | infrastructure | Missing projection rebuild | warning | No mechanism to rebuild read models from events |
| CQR-243 | infrastructure | Synchronous projections in write path | warning | Projection updates blocking command completion |
| CQR-244 | infrastructure | No monitoring of projection lag | warning | No metrics on event-to-projection delay |

### Complexity Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-250 | complexity | [CQRS for simple CRUD](https://martinfowler.com/bliki/CQRS.html) | error | Using CQRS for entities with only create/read/update/delete operations |
| CQR-251 | complexity | CQRS applied universally | error | Entire application using CQRS instead of [specific bounded contexts](https://github.com/slashdotdash/cqrs-best-practices) |
| CQR-252 | complexity | Over-engineered read models | warning | Separate read model for each query instead of shared projections |
| CQR-253 | complexity | Unnecessary event sourcing | warning | Using event sourcing just because CQRS is used |

### Anti-Pattern Detection

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CQR-260 | anti-pattern | [Value objects in events](https://github.com/slashdotdash/cqrs-best-practices) | error | Event classes containing value object instances instead of primitives |
| CQR-261 | anti-pattern | Chatty commands | warning | Multiple commands for what should be one operation |
| CQR-262 | anti-pattern | Fat events | warning | Events containing entire aggregate state instead of deltas |
| CQR-263 | anti-pattern | Query-command hybrid | error | Single endpoint/method doing both query and command |
| CQR-264 | anti-pattern | Read model as source of truth | error | Business logic depending on projection data |

## Allowed Exceptions

- **Same database (CQR-240):** Acceptable in early stages or simple systems.
  Separate databases can be introduced when scaling demands it.
- **Sync projections (CQR-243):** Valid when read-after-write consistency is
  critical (e.g., financial transactions). Ensure error handling doesn't break
  writes.
- **Simple CRUD (CQR-250):** Some bounded contexts may be genuinely CRUD-based.
  Apply CQRS only where the complexity is justified.
- **Query data in command response (CQR-201):** Returning generated IDs or
  version numbers is acceptable. Full domain objects are not.

## Cross-Reference

This doctrine pairs well with:
- **event-sourcing.md** — CQRS often uses event sourcing for the write model
- **ddd.md** — Commands should align with aggregate boundaries
- **saga.md** — Complex business processes spanning multiple aggregates
- **messaging.md** — Command/event buses and delivery guarantees

## Sources and Authority

Based on authoritative CQRS sources:

**Foundational Works:**
- [Greg Young - CQRS Documents](https://cqrs.files.wordpress.com/2010/11/cqrs_documents.pdf) — Original CQRS papers
- [Martin Fowler - CQRS](https://martinfowler.com/bliki/CQRS.html) — Definitive overview with warnings
- [Bertrand Meyer - CQS Principle](https://en.wikipedia.org/wiki/Command%E2%80%93query_separation) — Command-Query Separation foundation

**Implementation Guidance:**
- [Microsoft - CQRS Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs) — Azure architecture guidance
- [Microservices.io - CQRS](https://microservices.io/patterns/data/cqrs.html) — Microservices context
- [CQRS Best Practices Repository](https://github.com/slashdotdash/cqrs-best-practices) — Community-maintained guidance

**Anti-Patterns and Pitfalls:**
- [Common CQRS Problems](https://www.techtarget.com/searchapparchitecture/tip/Common-CQRS-pattern-problems-and-how-teams-can-avoid-them) — Data sync issues
- [CQRS Implementation Mistakes](https://medium.com/@opflucker/cqrs-pattern-common-implementation-mistakes-f99c6e43b00c) — Common pitfalls
- [Troubleshooting CQRS](https://reintech.io/blog/troubleshooting-cqrs-implementation-challenges) — Implementation challenges
