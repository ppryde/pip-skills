# Messaging & Async Communication Doctrine

This doctrine audits message-driven architecture, ensuring reliable async communication,
proper error handling, and correct implementation of messaging patterns.

## When to Use

Use messaging patterns when you need to decouple components, handle async workflows,
integrate distributed systems, or scale processing independently. Essential for
event-driven architectures, microservices communication, background job processing,
and systems requiring resilience to partial failures. Not recommended for simple
synchronous request-response where latency is critical or when strong consistency
is required immediately.

## Why Use It

Messaging enables resilient, scalable architectures by decoupling producers from
consumers. This provides:
- **Temporal decoupling** — producers and consumers don't need to be online simultaneously
- **Load leveling** — queues absorb traffic spikes, protecting downstream services
- **Scalability** — add/remove consumers independently based on load
- **Resilience** — messages survive crashes, network partitions heal automatically
- **Integration** — connect heterogeneous systems via common message formats

## Pros and Cons

| Pros | Cons |
|---|---|
| Components can evolve independently without breaking contracts | Eventually consistent — no immediate confirmation of processing |
| Natural retry and error handling via dead letter queues | Debugging is harder — must trace messages through multiple systems |
| Elastic scaling — add workers to handle load spikes | Message ordering is complex and often not guaranteed |
| Survives partial failures — messages queue until consumer recovers | Additional infrastructure to monitor and maintain |
| Fire-and-forget reduces latency for producers | Poison messages can block entire queues |
| Built-in audit trail of all messages | Increased complexity vs direct synchronous calls |

## Applicable Directories

Primary targets (typical locations):
- `infrastructure/messaging/` — publishers, consumers, configuration
- `infrastructure/celery/` — Celery tasks and beat schedules
- `application/services/` — orchestration and saga patterns
- `domain/events/` — event definitions and contracts
- `api/webhooks/` — async API handlers
- `workers/` — background job processors

## Violation Catalog

### Message Design Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-001 | message-design | Messages must be immutable | error | Message classes with setters, mutable fields, or `dataclass` without `frozen=True` |
| MSG-002 | message-design | Messages need unique identifiers | error | Messages without ID field (UUID, ULID, or correlation_id) |
| MSG-003 | message-design | Message size must be bounded | warning | Message classes with unbounded collections or >100KB typical payload |
| MSG-004 | message-design | Avoid sensitive data in messages | error | Messages containing passwords, tokens, SSN, credit cards (scan for field names/patterns) |
| MSG-005 | message-design | Messages must be versioned | warning | Message classes without version field or schema registry |
| MSG-006 | message-design | Use correlation IDs for tracing | warning | Messages without correlation_id for distributed tracing |
| MSG-007 | message-design | [Avoid entity-based events](https://www.ben-morris.com/event-driven-architecture-and-message-design-anti-patterns-and-pitfalls/) | warning | Events named like `UserUpdated` instead of business events like `UserRegistered`, `EmailChanged` |

### Delivery Guarantee Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-010 | delivery | [Handlers must be idempotent](https://blog.bytebytego.com/p/message-brokers-101-storage-replication) | error | Message handlers without idempotency checks (no dedup by message_id) |
| MSG-011 | delivery | Missing acknowledgement handling | error | Consumers not calling ack/nack explicitly (auto_ack=True in production) |
| MSG-012 | delivery | No retry configuration | warning | Publishers/consumers without retry logic or exponential backoff |
| MSG-013 | delivery | Missing dead letter queue | warning | Queue declarations without DLQ configuration for failed messages |
| MSG-014 | delivery | [Unbounded retries](https://medium.com/@erickzanetti/rabbitmq-a-complete-guide-to-message-broker-performance-and-reliability-3999ee776d85) | error | Retry loops without max attempts or without backing off |
| MSG-015 | delivery | No timeout configuration | warning | RPC-style messaging without timeout (can block forever) |
| MSG-016 | delivery | [Guaranteed delivery not configured](https://www.enterpriseintegrationpatterns.com/patterns/messaging/GuaranteedMessaging.html) | warning | Critical messages without persistence (delivery_mode=2 in RabbitMQ) |

### Error Handling Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-020 | error-handling | No poison message handling | error | Consumers without try/catch around processing or DLQ for failures |
| MSG-021 | error-handling | Swallowing exceptions | error | Catch blocks that don't log/rethrow/nack messages |
| MSG-022 | error-handling | Missing circuit breaker | warning | Consumers without circuit breaker for downstream service calls |
| MSG-023 | error-handling | No compensation logic | warning | [Saga participants without compensating transactions](https://microservices.io/patterns/data/saga.html) |
| MSG-024 | error-handling | Synchronous error propagation | error | Publishing error messages synchronously in catch blocks (blocks recovery) |
| MSG-025 | error-handling | Missing monitoring/alerting | warning | No metrics for queue depth, consumer lag, or failure rates |

### Ordering and Concurrency Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-030 | ordering | [Assuming message order](https://www.ben-morris.com/event-driven-architecture-and-message-design-anti-patterns-and-pitfalls/) | error | Logic that depends on message order without explicit sequencing |
| MSG-031 | ordering | [Race conditions in saga](https://medium.com/@joudwawad/microservices-pattern-distributed-transactions-saga-92b5e933cea1) | error | Saga steps that can execute out of order without guards |
| MSG-032 | ordering | Missing version checks | warning | Updates without optimistic concurrency control |
| MSG-033 | ordering | Competing consumers issues | warning | [Shared state modified by multiple consumers](https://bytebytego.com/guides/top-6-cloud-messaging-patterns/) without locking |
| MSG-034 | ordering | No sequence numbers | warning | Related messages without sequence/version for ordering |

### Infrastructure Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-040 | infrastructure | Hardcoded broker URLs | error | Connection strings in code instead of environment variables |
| MSG-041 | infrastructure | No connection pooling | warning | Creating new connections per message instead of reusing |
| MSG-042 | infrastructure | Missing heartbeat config | warning | Long-running consumers without heartbeat configuration |
| MSG-043 | infrastructure | No graceful shutdown | error | Consumers without signal handlers for clean shutdown |
| MSG-044 | infrastructure | Synchronous publishing in transaction | warning | Publishing messages inside database transactions (2PC issues) |
| MSG-045 | infrastructure | [No outbox pattern](https://medium.com/@mahmoudsallam2111/inbox-outbox-patterns-and-saga-pattern-in-microservices-df65b66bf41d) | warning | Direct publishing without outbox table (dual write problem) |
| MSG-046 | infrastructure | Queue/topic name collisions | error | Hardcoded queue names without environment/tenant prefixes |

### Pattern Implementation Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-050 | patterns | [Sync over async antipattern](https://tsh.io/blog/message-broker) | error | Blocking waiting for async response (request-reply with timeout) |
| MSG-051 | patterns | [Chatty messaging](https://microservices.io/patterns/communication-style/messaging.html) | warning | Multiple messages for single logical operation |
| MSG-052 | patterns | [Fat messages](https://www.designgurus.io/answers/detail/best-practices-for-message-brokers) | warning | Messages >1MB or containing full entities instead of IDs |
| MSG-053 | patterns | Missing saga orchestrator | error | Distributed transactions without coordinator |
| MSG-054 | patterns | [Two-phase commit over messaging](https://akfpartners.com/growth-blog/microservices-saga-pattern) | error | XA transactions spanning message broker and database |
| MSG-055 | patterns | Temporal coupling | warning | Expecting immediate response from async operations |

### Performance Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| MSG-060 | performance | No batching | warning | Publishing/consuming one message at a time in loops |
| MSG-061 | performance | Prefetch not configured | warning | Consumers without prefetch limit (can overwhelm worker) |
| MSG-062 | performance | No async I/O | warning | Blocking I/O in message handlers (use async/await or threads) |
| MSG-063 | performance | Unbounded queues | warning | No max length or TTL on queues (memory issues) |
| MSG-064 | performance | No consumer scaling | warning | Fixed number of consumers regardless of queue depth |

## Allowed Exceptions

- **Message ordering (MSG-030):** Some brokers (Kafka, Kinesis) provide ordering
  within partitions. Document reliance on this.
- **Same database (MSG-044):** Outbox pattern alternative: use transactional
  outbox or CDC (Change Data Capture).
- **Sync publishing (MSG-044):** Acceptable if using outbox pattern where messages
  are written to DB then published async.
- **Auto-ack (MSG-011):** May be acceptable for non-critical monitoring/metrics
  messages where loss is tolerable.
- **No DLQ (MSG-013):** Acceptable for ephemeral messages like heartbeats or
  metrics that can be dropped.
- **Request-reply (MSG-050):** Valid for RPC-style APIs with explicit timeout and
  error handling.

## Cross-Reference

This doctrine pairs well with:
- **event-sourcing.md** — event publishing and subscription patterns
- **cqrs.md** — command buses and async projections
- **saga.md** — distributed transaction patterns (if separate)
- **resilience.md** — circuit breakers, retries, timeouts
- **monitoring.md** — metrics, tracing, alerting for async systems
- **strategy.md** — background job runners (inline vs. queued) are strategies over messaging infrastructure; strategy.md governs the interface design and wiring of those runner implementations.

## Sources and Authority

Based on authoritative messaging sources:

**Foundational Works:**
- [Enterprise Integration Patterns (Hohpe & Woolf)](https://www.enterpriseintegrationpatterns.com/praise.html) — The definitive messaging patterns book
- [Microservices.io - Messaging Patterns](https://microservices.io/patterns/communication-style/messaging.html) — Chris Richardson's patterns
- [Message Brokers 101 - ByteByteGo](https://blog.bytebytego.com/p/message-brokers-101-storage-replication) — Delivery guarantees explained

**Anti-Patterns & Pitfalls:**
- [Messaging Anti-patterns in Event-Driven Architecture](https://www.ben-morris.com/event-driven-architecture-and-message-design-anti-patterns-and-pitfalls/) — Common mistakes
- [Saga Pattern Implementation](https://microservices.io/patterns/data/saga.html) — Distributed transaction management
- [Inbox & Outbox Patterns](https://medium.com/@mahmoudsallam2111/inbox-outbox-patterns-and-saga-pattern-in-microservices-df65b66bf41d) — Solving dual write problem

**Broker-Specific Guidance:**
- [RabbitMQ Complete Guide](https://medium.com/@erickzanetti/rabbitmq-a-complete-guide-to-message-broker-performance-and-reliability-3999ee776d85) — Performance and reliability
- [Message Broker Best Practices](https://www.designgurus.io/answers/detail/best-practices-for-message-brokers) — Implementation patterns
- [Top 6 Cloud Messaging Patterns](https://bytebytego.com/guides/top-6-cloud-messaging-patterns/) — Modern patterns

**Delivery Guarantees:**
- [Guaranteed Delivery Pattern](https://www.enterpriseintegrationpatterns.com/patterns/messaging/GuaranteedMessaging.html) — Enterprise Integration Patterns
- [Message Delivery Guarantees](https://yurimelo.substack.com/p/message-delivery-guarantees-in-distributed) — Distributed systems perspective

## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest async Messaging is in use):
- `infrastructure/messaging/` — message broker integration and configuration
- `workers/` or `consumers/` — background message consumer processes
- `publishers/` or `producers/` — message publishing logic
- `queues/` or `topics/` — queue and topic definitions
- `api/webhooks/` — async inbound webhook handlers

### File signals
Strong indicators (any 1 is significant):
- Files named `*Consumer.*` or `*Subscriber.*`
- Files named `*Publisher.*` or `*Producer.*`
- Files named `*MessageHandler.*` or `*EventHandler.*`
- Broker configuration files: `celery.py`, `kafka_config.*`, `rabbitmq.*`, `sqs_config.*`, `nats_config.*`
- Files named `*MessageBus.*` or `*EventBus.*`

### Anti-signals
Suggest async Messaging is NOT in use:
- No message broker configuration files anywhere in the project
- All inter-service or inter-component communication via synchronous HTTP only
- No consumer, worker, subscriber, or publisher directories
