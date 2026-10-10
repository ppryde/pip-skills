# Audit-framework escalation and signal-context caveats

Read this only when Step 2 set `audit_framework=true` or the `{model → signal_dependencies}` map is non-empty.

## Audit-framework escalation (WRITE group)

When `easyaudit`, `auditlog`, `simple_history`, or `reversion` is detected (PAT-070 fires):
- WRITE-006, WRITE-007: escalate from `medium` → `critical` (WRITE-009 does not: `QuerySet.delete()` still sends `pre_delete`/`post_delete`).
- WRITE-008: stays at `medium` (may escalate to `critical` depending on what the raw SQL touches).
- `pghistory`: `signals_safe=true`. It records history through Postgres triggers, not Django signals, so it does **not** trigger escalation and no signal-bypass caveat is appended (`.update()`, `bulk_create` and `qs.delete()` still fire those triggers).

## Signal-context caveats (WRITE group)

When `signal_dependencies[<Model>]` is non-empty, the fix templates of WRITE-001/002/003/020 **append a structured caveat block** listing each bypassed listener (file:line, what it does, and 2–3 mitigations). The severity of the perf finding stays unchanged. A finding carrying a `signals_caveat` shows the caveat inline whether or not the user has approved the bulk bypass.

Which checks read the signal map: WRITE-001/002/003/005/006/007/008/020. WRITE-009 depends instead on the model overriding `Model.delete()`.
