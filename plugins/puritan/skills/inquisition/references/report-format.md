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

## Subagent span check

Paste into each subagent prompt: "The first line of your Read range must be `## Applicable Directories`. If it is not (the INDEX row is stale), locate that heading and read from there through `## Allowed Exceptions`, and report `span_relocated: true`."

## Subagent JSON contract

Each doctrine subagent MUST return this JSON structure:

```json
{
  "doctrine": "ddd",
  "files_scanned": 12,
  "violations": [
    {
      "id": "DDD-001",
      "file": "<pkg>/domain/aggregates/loan.py",
      "line": 42,
      "rule": "Domain must not import from infrastructure layer",
      "actual": "from <pkg>.infrastructure.event_store import EventStore",
      "severity": "error",
      "category": "layer-boundary"
    }
  ],
  "clean_files": ["<pkg>/domain/aggregates/account.py"],
  "span_relocated": false,
  "notes": ["Unable to parse <pkg>/broken.py - syntax error"]
}
```
