---
name: inquisition
description: Use when auditing a codebase against architectural doctrine for DDD, CQRS, Event Sourcing, Hexagonal, Microservices, or other pattern violations. Triggers on "audit my code", "check architecture", "run doctrines", "review system design", "check pattern compliance".
---

# Inquisition — Code Audit

This mode audits your codebase against architectural patterns defined in doctrine files,
helping maintain consistency and catch violations early.

## Prerequisites

Before running an audit:
1. `.architecture/config.yml` must exist with doctrine configuration, if it doesn't guide user through creating one
2. Doctrine files must be present in `${CLAUDE_SKILL_DIR}/../doctrines/`
3. For changed-files mode: git repository with identifiable base branch

## Mode Detection

The mode automatically selects scope based on arguments:

| Invocation | Mode | Scope |
|---|---|---|
| `/puritan:inquisition` (no args) | Report | Changed files (git diff against base branch) |
| `/puritan:inquisition full` | Report | Entire codebase |
| `/puritan:inquisition interactive` | Interactive | Entire codebase |
| `/puritan:inquisition <doctrine>` | Report | Changed files, single doctrine only |
| `/puritan:inquisition interactive <doctrine>` | Interactive | Entire codebase, single doctrine only |
| Called from hook/make | Report | Changed files |

## When NOT to Use

- User wants to write a new doctrine — use Scriptorium instead
- Reviewing PR comments or feedback — use Tribunal (/tribunal:reckoning)
- Exploring whether a pattern fits the project — use Covenant to evaluate fit
- Codebase has no doctrine files configured — nothing to audit against

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Running full audit on every commit | Default mode scans changed files only — use `full` for periodic deep scans |
| Treating all violations as errors | Respect strictness levels — `aspirational` doctrines produce warnings, not errors |
| Auditing generated or vendored code | Exclude `**/migrations/**`, `vendor/`, `*.generated.*` in config |
| Ignoring the decisions.yml overrides | Team-approved exceptions are not heresies — check for overrides before reporting |
| Running without doctrines present | Verify doctrine files exist before dispatching subagents — warn and continue with what's available |
| Reporting violations without the actual code found | Always include the concrete line/import/pattern that triggered the violation |

## Workflow

### Step 1: Load Configuration

```yaml
# .architecture/config.yml (required)
doctrines:
  - name: ddd
    enabled: true
    targets:
      - domain/
      - application/
  - name: event-sourcing
    enabled: true
    targets:
      - domain/events/
      - infrastructure/event_store/
  - name: cqrs
    enabled: true
    targets:
      - domain/commands/
      - infrastructure/projections/

layers:
  domain:
    - domain/
  application:
    - application/
  infrastructure:
    - infrastructure/
  api:
    - api/
```

```yaml
# .architecture/decisions.yml (optional)
strictness:
  ddd: strict          # All violations are errors
  event-sourcing: pragmatic  # Allowed exceptions become warnings
  cqrs: aspirational   # All violations are warnings

overrides:
  DDD-004:  # Allow Pydantic in domain
    severity: warning
    reason: "Team decision: Pydantic for validation"
  EVS-114:  # Allow sync projections
    severity: info
    reason: "Read-after-write consistency required"
```

### Step 2: Discover Doctrines

For each doctrine in config:
1. Check if `${CLAUDE_SKILL_DIR}/../doctrines/<name>.md` exists
2. Parse doctrine file for violation catalog
3. Validate doctrine structure (all required sections)
4. Warn if doctrine missing but continue with others

### Step 3: Determine Scope

**Report Mode:**
- Default: `git diff --name-only $(git merge-base HEAD main) HEAD`
- Full: All files matching doctrine target patterns
- Single doctrine: Filtered to that doctrine's targets only

**Interactive Mode:**
- Always full codebase (more useful for discussions)
- Can focus on single doctrine if specified

### Step 3b: Pre-flight Size Check

After determining scope, count the total files and unique directories before dispatching any subagents.

If the scope exceeds **100 files**, pause and ask the user:

> "Found **N files across X directories** matching your configured targets. This audit may consume significant tokens. How would you like to proceed?
> 1. Proceed with full audit
> 2. Focus on specific directories (list them)
> 3. Run changed-files only (`git diff` against base branch)
> 4. Audit a single doctrine only (which one?)"

If the scope is ≤ 100 files, proceed silently — no prompt needed.

For **Report Mode (non-interactive)**, apply the same check but phrase it as a warning rather than a blocking question:
> "⚠ Scope: N files across X directories. Proceeding with audit. Use `targets:` in `.architecture/config.yml` to narrow scope."

### Step 4: Run Audit

**Report Mode (Parallel):**
```python
# Pseudo-code for parallel dispatch
async def run_report_audit(doctrines, scope):
    tasks = []
    for doctrine in doctrines:
        task = dispatch_subagent(
            doctrine_name=doctrine.name,
            doctrine_content=doctrine.content,
            files_to_audit=scope.files_for_doctrine(doctrine),
            output_format="json"
        )
        tasks.append(task)

    results = await gather(*tasks)
    return collate_results(results)
```

**Interactive Mode (Sequential):**
```python
# Pseudo-code for interactive audit
def run_interactive_audit(doctrines, scope):
    for doctrine in doctrines:
        print(f"\nAuditing {doctrine.name}...")

        violations = audit_with_doctrine(doctrine, scope)

        if not violations:
            print(f"No {doctrine.name} violations found!")
            continue

        for violation in violations:
            display_violation(violation)

            response = ask_user([
                "Fix this violation",
                "Explain why this matters",
                "Skip for now",
                "Mark as allowed exception"
            ])

            handle_response(response, violation)
```

### Step 5: Collate and Classify

Apply strictness levels and overrides:

```python
def apply_strictness(violations, decisions):
    for violation in violations:
        doctrine_strictness = decisions.strictness.get(violation.doctrine, "pragmatic")

        # Check for specific override
        if violation.id in decisions.overrides:
            violation.severity = decisions.overrides[violation.id].severity
            violation.note = decisions.overrides[violation.id].reason
            continue

        # Apply doctrine-level strictness
        if doctrine_strictness == "strict":
            # Keep original severity
            pass
        elif doctrine_strictness == "pragmatic":
            # Allowed exceptions become warnings
            if violation.id in doctrine.allowed_exceptions:
                violation.severity = "warning"
        elif doctrine_strictness == "aspirational":
            # Everything becomes warning
            violation.severity = "warning"

    return violations
```

### Step 6: Output Report

**Report Format:**
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
  File: wayledger/domain/aggregates/loan.py:42
  Rule: Domain must not import from infrastructure
  Found: from wayledger.infrastructure.event_store import EventStore

[EVS-110] Event flow violation
  File: wayledger/application/services/loan_service.py:127
  Rule: Events must be persisted before publishing
  Found: self.bus.publish(event) before self.store.append_events()

Warnings (7):
-------------
[DDD-015] Aggregate size warning
  File: wayledger/domain/aggregates/loan.py
  Rule: Aggregate should be <500 LOC
  Found: LoanAggregate is 847 lines
  Note: Team override - complex business logic justified

Clean files (35):
  wayledger/domain/aggregates/account.py
  wayledger/domain/commands/loan_commands.py
  ... (truncated for brevity)

Next steps:
  1. Fix 5 errors before committing
  2. Review warnings for potential improvements
  3. Consider adding overrides in .architecture/decisions.yml
```

## Subagent Contract

Each doctrine subagent MUST return this JSON structure:

```json
{
  "doctrine": "ddd",
  "files_scanned": 12,
  "violations": [
    {
      "id": "DDD-001",
      "file": "wayledger/domain/aggregates/loan.py",
      "line": 42,
      "rule": "Domain must not import from infrastructure layer",
      "actual": "from wayledger.infrastructure.event_store import EventStore",
      "severity": "error",
      "category": "layer-boundary"
    }
  ],
  "clean_files": ["wayledger/domain/aggregates/account.py"],
  "notes": ["Unable to parse wayledger/broken.py - syntax error"]
}
```

## Integration Points

### Pre-push Hook
```bash
#!/bin/bash
# .git/hooks/pre-push

echo "Running the Inquisition..."
puritan inquisition

if [ $? -ne 0 ]; then
  echo "Heresies found. Fix before pushing."
  exit 1
fi
```

### Makefile
```makefile
# Makefile
audit:
	@echo "Running the Inquisition..."
	@puritan inquisition

audit-full:
	@echo "Running the full Inquisition..."
	@puritan inquisition full

audit-fix:
	@echo "Running interactive Inquisition with fixes..."
	@puritan inquisition interactive

pre-push: format lint test audit
	@echo "All checks passed!"
```

### CI/CD Pipeline
```yaml
# .github/workflows/audit.yml
name: Architecture Audit

on: [push, pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run the Inquisition
        run: |
          puritan inquisition full
```

## Available Doctrines

| Doctrine | Focus | Violations | Severity Range |
|---|---|---|---|
| ddd | Domain-Driven Design patterns | 42 | Layer boundaries, aggregates, value objects |
| event-sourcing | Event store implementation | 47 | Immutability, replay, snapshots |
| cqrs | Command/Query separation | 35 | Read/write isolation, consistency |
| messaging | Async communication | 64 | Delivery guarantees, idempotency |
| saga | Distributed transactions | 65 | Compensation, isolation, state |

## Error Handling

### Missing Configuration

If `.architecture/config.yml` is not found, do **not** show a raw error. Instead, offer to hand off to Covenant's discovery mode:

> "No `.architecture/config.yml` found. The Inquisition cannot proceed without knowing what to audit or where to look.
>
> Would you like me to run `/puritan:covenant discover` first? It will scan your codebase structure, identify the patterns you appear to be using, and generate the config file — then the Inquisition can begin."

If the user agrees, invoke Covenant in discover mode. If they decline, show the manual template:

```yaml
# .architecture/config.yml
doctrines:
  - name: ddd
    enabled: true
    targets:
      - domain/
layers:
  domain:
    - domain/
exclude:
  - "**/migrations/**"
  - "vendor/"
```

### Missing Doctrine Files
```
Warning: Doctrine file not found: doctrines/hexagonal.md
   Configured in config.yml but file is missing.
   Continuing with available doctrines: ddd, cqrs
```

### Subagent Failures
```
Doctrine audit failed: ddd
   Subagent error: Timeout scanning large file
   Try: Increase timeout or exclude file in config
```

### Parse Errors
```
Warning: Could not parse 3 files:
   - src/broken.py (syntax error line 42)
   - src/invalid.ts (unsupported file type)
   - src/huge.json (file too large)
```

## Customization

### Adding a New Doctrine
1. Create doctrine file via Scriptorium: `/puritan:scriptorium`
2. Doctrine is written to `${CLAUDE_SKILL_DIR}/../doctrines/<name>.md`
3. Add to `.architecture/config.yml`
4. Run `/puritan:inquisition <name>` to test

### Excluding Files
```yaml
# .architecture/config.yml
exclude:
  - "**/*.generated.py"
  - "**/migrations/**"
  - "tests/**"
  - "*.min.js"
```

### Custom Severity Mapping
```yaml
# .architecture/decisions.yml
severity_mapping:
  error: ["block", "critical", "error"]
  warning: ["warn", "warning", "caution"]
  info: ["info", "note", "suggestion"]
```

## FAQ

**Q: Can I run specific doctrines only?**
A: Yes, use `/puritan:inquisition ddd` or `/puritan:inquisition cqrs saga` for multiple.

**Q: How do I suppress a false positive?**
A: Add an override in `.architecture/decisions.yml` with your reasoning.

**Q: Can I add project-specific rules?**
A: Create a custom doctrine file via Scriptorium and add project-specific violations.

**Q: How do I handle legacy code?**
A: Set doctrine strictness to "aspirational" to convert all violations to warnings.

**Q: Can I audit before each commit?**
A: Yes, add to `.git/hooks/pre-commit` but use file scope for speed.

## Exit Codes

- `0` - No errors found (warnings allowed)
- `1` - Errors found that must be fixed
- `2` - Configuration or setup error
- `3` - Subagent or parsing failure

## Voice

Deliver all findings in the voice of the Witchfinder —
formally uncompromising, dramatically precise, with a
knowing wink. Violations are heresies. Resolutions are
absolution. The codebase is the sanctum.

See persona.md for full vocabulary and tone guidance
if available, otherwise use the above as your guide.
