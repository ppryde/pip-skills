# Puritan shared reference: config, decisions, doctrine discovery

Not a skill (no SKILL.md). Covenant, Inquisition and Scriptorium each point here instead of restating it.

## Plugin root

Every skill lives at `<plugin-root>/skills/<skill>/SKILL.md`. The doctrines are the `doctrines/` sibling inside the same `skills/` directory: `<plugin-root>/skills/doctrines/`. This file is `<plugin-root>/skills/_shared/config.md`.

## Doctrine discovery

Never use a hardcoded or memorised list. A doctrine is any `*.md` in `<plugin-root>/skills/doctrines/` whose basename does not start with `_` and is not `INDEX.md` or `README.md`; its filename without `.md` is its name. New doctrines participate with no change to any skill.

`doctrines/INDEX.md` is generated (`python3 tools/build_index.py doctrines`, in the pip-skills repo) and summarises every doctrine: ID prefix and range, `when`/`when not`, detection signals, cross-refs (`planned` = file not written yet) and `audit: L<a>-<b>`, the line span of the sections an auditor needs. Read the INDEX rather than the doctrine files unless a step says otherwise.

**Stale or missing row.** The INDEX is regenerated only where `tools/build_index.py` exists (the pip-skills repo), so an installed plugin, or a doctrine added or edited by hand, may be missing from it or have a stale `audit:` span. A doctrine file with no INDEX row is read directly: Covenant reads its `## When to Use` and `## Detection Signatures`; Inquisition's subagent reads from `## Applicable Directories` through `## Allowed Exceptions`. A stale `audit:` span is caught by the auditing subagent, which checks that the first line of its range is `## Applicable Directories`; if not, it locates the heading itself and reports `span_relocated: true`. Find files with no row by Globbing `doctrines/*.md` and comparing with the INDEX.

## `.architecture/config.yml` (consumed keys only)

```yaml
doctrines:
  - name: ddd              # doctrine filename without .md
    enabled: true
    targets:               # directories (relative, no src/ prefix) to audit
      - domain/
      - application/

exclude:                   # optional globs, never audited
  - "**/migrations/**"
  - "**/vendor/**"
  - "**/*.generated.*"
  - "**/node_modules/**"
```

Unknown keys (for example an old `layers:` or `severity_mapping:`) are ignored.

## `.architecture/decisions.yml` (optional)

```yaml
strictness:
  ddd: strict              # strict | pragmatic (default) | aspirational
overrides:
  DDD-004:                 # a violation id; ids are stable keys, never renumbered or reused
    severity: warning      # error | warning | info
    reason: "Team decision: Pydantic for validation"
```

- `strict`: keep each rule's severity. `pragmatic`: allowed exceptions become warnings. `aspirational`: every violation becomes a warning.
- An `overrides` entry on an id wins over the doctrine strictness.
