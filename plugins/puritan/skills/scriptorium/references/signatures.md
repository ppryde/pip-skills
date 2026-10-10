# Scriptorium Step 8: Detection Signatures

Every doctrine must include a `## Detection Signatures` section for Covenant discover mode. It enables lightweight pattern fingerprinting without a full audit. Covenant owns the scoring thresholds; the section lists signals only and states no numbers.

**Structure (always three subsections in this order):**

```markdown
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Directory signals (counted by Covenant):
- `specific/sub/path/` — what its presence implies
- `another/path/` — what its presence implies
[typically 3–7 entries]

### File signals
File signals (counted by Covenant):
- Files named `*PatternSpecific.*` in [layer] directories
- Configuration files: `pattern-config.yml`
[typically 2–5 entries]

### Anti-signals
Suggest [Pattern] is NOT in use:
- [Structural absence or alternative structure that rules this out]
- [Reference to adjacent pattern it might be confused with]
[typically 2–4 entries]
```

**Rules for writing good signals:**

| Rule | Why |
|------|-----|
| Use specific sub-paths (`infrastructure/event_store/`), not bare parent dirs (`infrastructure/`) | Parent dirs appear in many patterns; sub-paths discriminate |
| Put the path or glob first, in backticks, then ` — meaning`; keep each entry short | The generated INDEX drops everything after the spaced dash (em dash, en dash or hyphen, ` — `) and copies the rest of the entry whole (never truncated), so every glob Covenant must match has to sit before the dash |
| Do not state a count threshold in the preamble | Covenant scores signals (a file signal is stronger than a directory signal); a second threshold here would conflict |
| Anti-signals must name the pattern they point toward (`leans DDD`, `leans Microservices`) | Lets Covenant present a scored comparison rather than a yes/no |
| Generic dirs (`services/`, `domain/`, `shared/`) must be qualified with required context | `services/` alone fires on Layered, Microservices and Modular Monolith |
| If your pattern co-exists legitimately with another (DDD + CQRS), do NOT add the other as an anti-signal | Anti-signals are for genuine exclusions only |

**Crossover awareness — avoid these known collisions:**

| Signal | Also fires on | Resolution |
|--------|--------------|------------|
| `domain/events/` | DDD, ES, CQRS, Saga | Only use as a signal in DDD and ES; exclude from Messaging/Saga |
| `services/` directory | Layered, Microservices, Modular Monolith | Qualify with 3+ subdirs + per-service Dockerfiles for Microservices; require `modules/` for Modular Monolith |
| `infrastructure/` bare | Hexagonal, ES, CQRS, Messaging, Resilience | Always use a specific sub-path |
| `shared/` or `common/` | Layered N-Tier, Modular Monolith | Require `modules/` context for Modular Monolith; require `persistence/` context for Layered |
| `*Handler.*` files | CQRS, Messaging, Saga | Qualify with directory context |
