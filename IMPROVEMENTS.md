# Improvements

Tracked improvements for pip-skills. Each entry notes the problem, the affected
component, and the proposed resolution.

---

## Language Agnosticism in Doctrines

**Status:** Open — overhaul required
**Affects:** `plugins/puritan/skills/doctrines/ddd.md` (confirmed); other doctrines not fully audited

### Problem

The DDD doctrine presents itself as a general architectural audit but is silently
Python-specific. Its violation catalog is not usable against TypeScript, Go, Java,
or any other language without a full rewrite.

Specific heresies in `ddd.md`:

- **Import detection patterns** (DDD-001–004) scan for Python import syntax:
  `from <pkg>.infrastructure`, `import sqlalchemy`, `import fastapi`, etc.
- **Framework deny-list** is Python-only: SQLAlchemy, FastAPI, Celery, aiohttp,
  httpx, requests.
- **Structural rules** reference Python-specific constructs: `__slots__`, `__eq__`,
  `__hash__`, `model_config = {"frozen": True}`, Pydantic frozen models.
- **UTC rule** (DDD-090) checks for `date.today()` and `datetime.now()` —
  Python stdlib API, not a language-agnostic temporal pattern.
- **Allowed domain imports** list is Python stdlib (`uuid`, `datetime`, `decimal`,
  `typing`, `abc`, `collections`, `re`, `json`, `os`, `copy`).

A TypeScript or Go team running `puritan:inquisition` against this doctrine would
receive false positives on legitimate code and miss real violations because none
of the detection patterns apply.

### Proposed Resolution

**Option A — Language-scoped variants**
Split language-specific doctrines at the file level:
`ddd-python.md`, `ddd-typescript.md`, `ddd-go.md`. Each shares the conceptual
rules but provides language-appropriate detection patterns. The framework
(Inquisition, config.yml) already supports referencing any doctrine file by name,
so no structural changes required.

**Option B — Language-agnostic core with per-language detection tables**
Keep a single `ddd.md` that separates *what the rule means* from *how to detect
it*. Each violation row would include a detection block per language:

```markdown
| DDD-001 | layer-boundary | Domain must not import from infrastructure | error |
  Python: `from <pkg>.infrastructure` or `import <pkg>.infrastructure` in domain/ files
  TypeScript: `import ... from '../../infrastructure'` in domain/ files
  Go: `"<module>/infrastructure"` in imports within `domain/` packages
```

**Option C — Declare language scope in the doctrine header**
If a doctrine is intentionally language-specific, it should declare this
explicitly so Inquisition can warn when applied to a non-matching codebase.
Minimal change; does not fix the detection gaps but at least makes the
assumption visible.

**Recommendation:** Option A for existing doctrines (clear separation, no
ambiguity), Option C as a mandatory header field going forward (enforced via
Scriptorium — see below).

---

## Scriptorium: Enforce Language Scope Declaration

**Status:** Done
**Affects:** `plugins/puritan/skills/scriptorium/SKILL.md`

### Change Made

Added **Language Scope** as a required header field in Step 4, with explicit
guidance in Step 6 that detection patterns must match the declared scope (no
implicit language assumptions), and two new checklist items in Step 9. New
doctrines written via Scriptorium will now be required to declare their language
scope before writing any violation rules.

---

## Skill Permission Pre-Approval

**Status:** Open — documentation / DX improvement
**Affects:** All skills (puritan, tribunal)

### Problem

Running skills like `tribunal:reckoning` requires repeated "yes" clicking for
every tool call (`gh api`, `Read`, `Edit`, etc). This friction discourages
use and slows workflows, especially for skills that make many API calls.

### Proposed Resolution

Document recommended `allowedTools` entries per skill so users can pre-approve
the tools each skill needs. Add guidance to each plugin's `README.md`.

**Tribunal (reckoning):**
```json
{
  "permissions": {
    "allow": [
      "Bash(gh:*)",
      "Read",
      "Edit"
    ]
  }
}
```

**Puritan (inquisition, covenant, scriptorium):**
```json
{
  "permissions": {
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "Edit",
      "Write"
    ]
  }
}
```

These go in `.claude/settings.local.json` (project-level, not committed) or
`~/.claude/settings.json` (user-level). Alternatively pass `--allowedTools`
on the CLI for one-off sessions.

Consider adding a "Recommended Permissions" section to each plugin's
`README.md` and/or `SKILL.md` frontmatter if Claude Code ever supports
permission declarations in skill metadata.
