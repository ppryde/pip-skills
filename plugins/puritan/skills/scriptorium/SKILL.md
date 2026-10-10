---
name: scriptorium
description: Use when creating a new architecture doctrine, updating an existing one, or converting informal architecture rules into an auditable format. Triggers on "write a new doctrine", "create a rule set", "add a doctrine", or "update the X doctrine".
disable-model-invocation: true
---

# Scriptorium — Doctrine Writer

Writes a new architecture doctrine, or updates an existing one, to `<plugin-root>/skills/doctrines/<pattern-name>.md`. The structure is `<plugin-root>/skills/doctrines/_template.md`, the single structural source: copy its sections, order and wording. `<plugin-root>` and doctrine discovery: `../_shared/config.md`.

## When NOT to Use

- Auditing code against existing doctrines: Inquisition
- Planning which patterns to adopt: Covenant
- Project conventions (naming, folder structure): CLAUDE.md or a project README
- A pattern too niche for reusable rules ("how we use Redis in this one service"): that is project config, not a doctrine

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Vague detection patterns | "Poor separation of concerns" is unauditable; write "Controller >200 LOC or >10 dependencies" |
| Skipping failure-case research | Every doctrine needs at least one anti-pattern source |
| Too many or too few rules | 3-8 per category; 20-50 in total (fewer is too shallow to be useful) |
| Forgetting allowed exceptions | Undocumented pragmatic edge cases become false positives |
| Not claiming a unique ID prefix | Overlapping prefixes break audit reporting |
| Rules that need runtime analysis | "What to scan for" must be detectable via grep/AST/regex |

## Workflow

### Step 1: Identify the Pattern
Ask what architectural pattern or principle needs a doctrine (technical patterns such as CQRS or Saga, quality attributes, domain patterns such as Repository, infrastructure patterns such as Message Bus).

### Step 2: Research Authoritative Sources
Search for: `"[pattern]" [original author]`; `"[pattern]" best practices <current year>`; `"[pattern]" anti-patterns common mistakes`; `"[pattern]" [language/framework]`. Minimum sources: 1 primary (original author or paper), 2 recognised practitioners, 1 failure case or anti-pattern article.

**Cite only sources you actually fetched.** If you cannot fetch one (offline, blocked), mark the citation `(unverified)` or omit it. Never invent a URL, title or quote.

### Step 3: Discover Existing Doctrines
Read `<plugin-root>/skills/doctrines/INDEX.md` (generated; do not open doctrine files unless needed):
1. Claimed ID prefixes and ranges come from the INDEX; do not rely on a hard-coded list
2. Identify cross-reference opportunities; new doctrines should link to related existing ones
3. If an existing doctrine already covers your pattern, update it instead

**Cross-referencing:** reference doctrines that *should* pair with yours, even if they do not exist yet (use the filename they would have). Inquisition handles missing doctrines gracefully. List every referenced doctrine that does not exist under "Planned" in `doctrines/README.md`. After writing, check existing doctrines for stale or missing cross-references back to yours and update them. After adding or editing a doctrine, regenerate the INDEX: `python3 tools/build_index.py doctrines` (in the pip-skills repo).

### Step 4: Structure the Doctrine
Use `_template.md` with ALL its sections, in order. Header: pattern name, a 1-2 sentence summary and a **Language Scope** declaration (`Language-agnostic`; `Language-specific: <language>`; or `Language-specific: <lang1>, <lang2>`). If language-specific, "What to scan for" must use that language's idioms explicitly. When to Use must include when NOT to use. Pros and Cons has 5+ rows. Applicable Directories use relative paths without `src/` (`domain/`, not `src/domain/`). Cross-references use **bold** with `.md` (`**ddd.md**`). Sources are grouped under bold labels.

### Step 5: Categorize Violations
You SHOULD have 5-9 categories; fewer than 5 is too narrow, more than 9 slices too thin. Archetypes: Structural, Behavioral, Naming, Dependencies, State, Performance, Anti-patterns, Testing/Testability. Each category has 3-8 violations; total 20-50. Count your rules before moving on.

### Step 6: Write Auditable Rules
For EACH violation: `| ID | Category | Rule | Default Severity | What to scan for |`. "What to scan for" MUST be a concrete file pattern or code signature, detectable via grep/AST/regex, specific enough to avoid false positives, and **describe the pattern, NOT the shell command**.

Bad: "Poor separation of concerns" · Bad: `grep -r "import .*infrastructure" src/domain/`
Good: `from <pkg>.infrastructure` in domain/ files · Good: Controller classes with >200 LOC or >10 dependencies

Language scope: a `Language-specific` doctrine uses that language's syntax (`import sqlalchemy`, `require('express')`). A `Language-agnostic` doctrine describes structural intent without syntax ("imports from infrastructure layer"). If a rule cannot be expressed that way, restrict the Language Scope or split into per-language variants.

### Step 7: Add Inline Citations
For rules from a specific source rather than general consensus, cite inline in "What to scan for", e.g. `Aggregate >500 LOC ([Vernon: max 300-400 LOC](link))`. Cite when a number or threshold comes from one source, the rule is controversial, or the source gives critical context.

### Step 8: Write Detection Signatures
Every doctrine needs a `## Detection Signatures` section for Covenant discover mode (three subsections: directory signals, file signals, anti-signals). Read `references/signatures.md` for the exact structure, rules and known signal collisions.

### Step 9: Document Exceptions
Real patterns have edge cases; document them with specific justification (vague exceptions are loopholes), for example: test code may keep adapters in the same package; a framework may require annotations on domain classes; denormalised projections may break normalisation.

### Step 10: Validate Completeness
Verify against `_template.md`, counting explicitly: all sections present and in order; categories and rule counts within the SHOULD limits above; Language Scope declared and detection patterns consistent with it; 5+ Pros/Cons rows; sources (1 primary, 2 practitioners, 1 failure case); exceptions justified; cross-references bold with `.md`; non-existent cross-referenced doctrines listed under "Planned" in `doctrines/README.md`; Detection Signatures present with relative `src/`-less paths; INDEX regenerated.

## Violation ID Convention

**The 3-letter prefix is the disambiguator.** `DDD-001` and `MSG-001` are distinct; numbers are scoped per prefix. Prefixes must be unique across all doctrines: take the claimed prefixes from `doctrines/INDEX.md` (Step 3). Numbers start at 001; **never renumber or reuse an id, even a retired one**. Ids are stable keys: Inquisition overrides in `.architecture/decisions.yml` target them, so renumbering silently retargets or orphans an override.

## Violation Table Contract

Each catalog row is a contract with Inquisition:

| Column | Rule |
|--------|------|
| **ID** | 3-letter prefix + hyphen + 3-digit number; never reuse |
| **Category** | Lowercase slug with hyphens (`layer-boundary`, `event-design`) |
| **Rule** | One line, imperative ("Domain must not import from infrastructure") |
| **Default Severity** | `error` (correctness: bugs, data loss, architectural decay, e.g. layer breach, mutable events) or `warning` (quality: naming, aggregate size, missing docs) |
| **What to scan for** | Concrete pattern (import paths, class patterns, file locations, LOC thresholds), never a shell command. If you cannot describe a detectable pattern, the rule is not auditable |

## Integration Checklist

- [ ] File is at `<plugin-root>/skills/doctrines/<pattern-name>.md`; ID prefix unique
- [ ] User's `.architecture/config.yml` has a new doctrine entry (format: `../_shared/config.md`)
- [ ] Optional smoke test: `/puritan:inquisition <doctrine-name>`. Warning: `<plugin-root>` is the plugin cache when installed from a marketplace, and files written there are lost when the plugin updates. Commit new doctrines to the plugin's source repository.

## Reference

| Read | When |
|---|---|
| `references/signatures.md` | Step 8 |

## Voice

Deliver all findings in the voice of the Witchfinder —
formally uncompromising, dramatically precise, with a
knowing wink. Violations are heresies. Resolutions are
absolution. The codebase is the sanctum.
