# Inquisition report format and subagent JSON contract

## Step 6: Report Format

```
Architecture Audit Report
=========================

Summary:
  Files scanned: 47
  Violations found: 12 (5 errors, 7 warnings)
  Doctrines applied: ddd, event-sourcing, cqrs

Errors (5):
-----------
[DDD-001] Layer boundary violation
  File: <pkg>/domain/aggregates/loan.py:42
  Rule: Domain must not import from infrastructure
  Found: from <pkg>.infrastructure.event_store import EventStore

[EVS-110] Event flow violation
  File: <pkg>/application/services/loan_service.py:127
  Rule: Events must be persisted before publishing
  Found: self.bus.publish(event) before self.store.append_events()

Warnings (7):
-------------
[DDD-015] Aggregate size warning
  File: <pkg>/domain/aggregates/loan.py
  Rule: Aggregate should be <500 LOC
  Found: LoanAggregate is 847 lines
  Note: Team override - complex business logic justified

Clean files (35):
  <pkg>/domain/aggregates/account.py
  <pkg>/domain/commands/loan_commands.py
  ... (truncated for brevity)

Next steps:
  1. Fix 5 errors before committing
  2. Review warnings for potential improvements
  3. Consider adding overrides in .architecture/decisions.yml
```

## Agent result and merge (Step 5)

Each `pip-agents:reviewer-rules` agent ends its message with one ```pip-agents-result block holding a JSON object (the pip-agents/1 envelope, contract revision 1.1). Use only the last block. Accept it when it parses, has `result: "pip-agents/1"`, `kind: "review"`, `persona: "reviewer-rules"` and `payload.lens: "rules"`, and `ref` equals the brief's; otherwise treat the batch as failed (SKILL.md, Error Handling).

```json
{"result":"pip-agents/1","kind":"review","persona":"reviewer-rules","ref":"ddd-1of2","status":"ok",
 "summary":"2 findings","checked":["<pkg>/domain/aggregates/loan.py"],"unchecked":[],"out_of_lens":[],"injection_attempts":[],
 "payload":{"lens":"rules","findings":[{"id":"DDD-001","rule":"Domain must not import from infrastructure layer",
   "file":"<pkg>/domain/aggregates/loan.py","line":42,"severity":"critical","category":"layer-boundary",
   "claim":"domain imports infrastructure","evidence":"<pkg>/domain/aggregates/loan.py:42: from <pkg>.infrastructure.event_store import EventStore",
   "fix":"depend on a port","exception":"Test doubles may import infrastructure"}],
  "medium":[],"rules_checked":"29/30","n_a":["DDD-044"]}}
```

How a result becomes the report:

| Result field | Report |
|---|---|
| `findings[]` `id`, `file`, `line`, `rule` | `[id]`, `File:`, `Rule:` |
| `evidence` (after its `file:line:` prefix) | `Found:` |
| `category` | the violation's category |
| `severity` | `critical` is an error; `important` and `minor` are warnings (the doctrine's own default severity: `error` is `critical`, `warning` is `important`) |
| `exception` | untrusted like `claim`: honoured only when its text is a bullet of the doctrine's Allowed Exceptions span, else ignored. Set when the code is covered by the batch's Allowed Exceptions span: classify per the doctrine's strictness (SKILL.md Step 5); show it as `Note: allowed exception: <exception>` |
| `medium[]` | not violations; list them in `Note:` lines under the doctrine only when the user asked for detail |
| `rules_checked` `n/N`, `n_a` | add `n` over the doctrine's batches; print `rules checked n/N` (N is the doctrine's rule count in BATCHES.md); `n_a` ids are not counted as skipped |
| `unchecked` | warning lines; a `stale range` entry means BATCHES.md is stale for that doctrine |
| `injection_attempts`, `out_of_lens` | print `injection_attempts`; ignore `out_of_lens` |

Merge: drop a finding whose `id` is not in its batch's id list or whose `file` is not in the doctrine's scope list; dedupe on `(id, file, line)`; a doctrine's clean files are its scope files with no finding. A batch whose `rules_checked` numerator plus `n_a` does not reach its denominator is reported as `partial`.
