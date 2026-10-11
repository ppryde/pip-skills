# Output file format (`--report`, Step 8)

Read this only when `--report` is set.

Path: `reports/optimise-orm/<target-slug>-<YYYYMMDD-HHMMSS>.md`. Create the directory if needed. If it cannot be created or written: `Cannot write report to <path>: <reason>` and stop.

This skill does not edit `.gitignore`. After writing the file, if `.gitignore` has no line covering `reports/optimise-orm/`, print one line: `Add reports/optimise-orm/ to .gitignore`.

**Frontmatter**
```yaml
target: apps/orders/views.py
target_resolved: /abs/path/apps/orders/views.py
generated_at: 2026-04-30T14:32:00Z
django_version: 5.0.4
db_engine: postgresql
explain_used: true
parallel: false
thorough: false
checks_run: 70
findings_count: { critical: 2, medium: 2, low: 2 }
total_savings_estimate_ms: { min: 770, max: 1665 }
suppressed: 0
```
`checks_run` is the number of live checks in `checks/INDEX.md` for the active groups. Correctness findings are not in `findings_count` or the savings total.

**Body sections, in order**
1. **Header banner**: info-level findings (audit framework, signal context, engine mismatch).
2. **Summary line**.
3. **Per-tier findings**, each with:
   - Header: `### N. CODE — title`
   - Location, savings, confidence
   - **Current code** block (excerpt from the target file)
   - **Suggested fix** block (template from the check's section)
   - **EXPLAIN evidence** block (if applicable)
   - **Audit caveat** block (if `signal_dependencies[model]` is non-empty)
4. **Correctness (outside the perf scope)**: findings from checks with `kind: correctness`, same per-finding layout, no tier.
