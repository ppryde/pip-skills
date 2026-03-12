---
name: scriptorium
description: Use when creating a new architecture doctrine, updating an existing one, or converting informal architecture rules into an auditable format. Triggers on "write a new doctrine", "create a rule set", "add a doctrine", or "update the X doctrine".
disable-model-invocation: true
---

# Scriptorium — Doctrine Writer

## When NOT to Use

- Auditing code against existing doctrines — use Inquisition
- Planning which patterns to adopt — use Covenant
- Documenting project-specific conventions (naming, folder structure) — put those in CLAUDE.md or a project README
- The pattern is too niche for reusable rules (e.g. "how we use Redis in this one service") — that's project config, not a doctrine

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Writing vague detection patterns | "Poor separation of concerns" is unauditable — write "Controller >200 LOC or >10 dependencies" |
| Skipping the failure case research | Every doctrine needs at least one anti-pattern source — without it, rules lack grounding |
| Too many violations per category | 3-8 per category — more than that is cognitive overload for the auditor |
| Too few violations total | Aim for 20-50 rules — fewer means the doctrine is too shallow to be useful |
| Forgetting allowed exceptions | Real patterns have pragmatic edge cases — undocumented exceptions become false positives |
| Not claiming a unique ID prefix | Overlapping prefixes (e.g. two doctrines both using DDD-xxx) break audit reporting |
| Writing rules that require runtime analysis | "What to scan for" must be detectable via grep/AST/regex — not "run the test suite and check" |

## Step 1: Identify the Pattern

Ask: What architectural pattern or principle needs a doctrine?

Examples:
- Technical patterns: CQRS, Hexagonal, Microservices, Saga
- Quality attributes: Performance, Security, Testability
- Domain patterns: Repository, Specification, Factory
- Infrastructure patterns: Caching, Message Bus, API Gateway

## Step 2: Research Authoritative Sources

Search for:
1. `"[pattern name]" [original author]` — Find who invented/formalized it
2. `"[pattern name]" best practices 2024 2025` — Current consensus
3. `"[pattern name]" anti-patterns common mistakes` — What goes wrong
4. `"[pattern name]" [language/framework]` — Language-specific adaptations

Minimum required sources:
- 1+ primary source (original author/paper)
- 2+ recognized practitioners
- 1+ failure case study or anti-pattern article

## Step 3: Discover Existing Doctrines

Before writing, read what already exists:

1. List files in `${CLAUDE_SKILL_DIR}/../doctrines/` (skip `_template.md`)
2. Note which ID prefixes and ranges are already claimed
3. Identify cross-reference opportunities — new doctrines should link to related existing ones
4. Check for overlap — if an existing doctrine already covers your pattern, update it instead

**Optimistic cross-referencing:** Always reference doctrines that *should* pair
with yours, even if they don't exist yet. Use the filename they would have
(e.g. `hexagonal.md`, `testing.md`). Inquisition already handles missing
doctrines gracefully. When the doctrine is eventually written, the
cross-references are already waiting. After writing a new doctrine, check
existing doctrines for stale or missing cross-references back to yours and
update them.

## Step 4: Structure the Doctrine

Use the standard template with ALL required sections:

### Header
- Pattern name and 1-2 sentence summary
- **Language Scope** — declare one of:
  - `Language-agnostic` — detection patterns work for any language
  - `Language-specific: <language>` — patterns only apply to one language (e.g. `Language-specific: Python`)
  - `Language-specific: <lang1>, <lang2>` — patterns cover multiple but not all languages
  If language-specific, the "What to scan for" column must use that language's
  idioms explicitly. Do not write `from <pkg>.infrastructure` and leave the
  language implicit.
- When to Use (problem context — MUST include when NOT to use)
- Why Use It (value proposition, 4-6 bullet points)
- Pros and Cons table (**minimum 5 rows** — honest trade-offs with inline
  citations for controversial claims)

### Body
- Applicable Directories (where to scan — use relative paths without `src/`
  prefix, e.g. `domain/` not `src/domain/`)
- Violation Catalog (5-8 categories, 20-50 rules total)
- Allowed Exceptions (pragmatic flexibility)
- Cross-Reference (use **bold** with `.md` suffix: `**ddd.md**`)
- Sources and Authority (grouped under bold H3-style labels)

## Step 5: Categorize Violations

**You MUST have 5-8 categories. Fewer than 5 means you haven't thought
broadly enough. More than 8 means you're slicing too thin.**

Common category archetypes (pick 5-8 that fit your pattern):

1. **Structural** — How components connect
2. **Behavioral** — How components interact
3. **Naming** — Conventions and terminology
4. **Dependencies** — What can import what
5. **State** — Mutability and data flow
6. **Performance** — Efficiency concerns
7. **Anti-patterns** — Known bad practices
8. **Testing / Testability** — What the pattern demands for verification

Each category: 3-8 violations. Total across all categories: **20-50 rules
minimum.** If you have fewer than 20, you're missing categories or being
too conservative within them. Count your rules before moving to Step 6.

## Step 6: Write Auditable Rules

For EACH violation, specify:

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| XXX-001 | category | One-line rule | error/warning | Concrete pattern to detect |

The "What to scan for" MUST be:
- Concrete file patterns or code signatures
- Detectable via grep/AST/regex
- Specific enough to avoid false positives
- **Describe the pattern to detect, NOT the shell command**

Bad: "Poor separation of concerns"
Bad: `grep -r "import .*infrastructure" src/domain/`
Good: `from <pkg>.infrastructure` or `import <pkg>.infrastructure` in domain/ files
Good: Controller classes with >200 LOC or >10 dependencies

**Language scope in detection patterns:** If the doctrine declared
`Language-specific`, the "What to scan for" column must use that language's
syntax explicitly (e.g. `import sqlalchemy` for Python, `require('express')` for
Node). If declared `Language-agnostic`, detection patterns must describe
structural intent without language syntax — e.g. "imports from infrastructure
layer" not "from <pkg>.infrastructure". If a rule genuinely cannot be expressed
in language-agnostic terms, either restrict the doctrine's Language Scope or
split it into per-language variants.

## Step 7: Add Inline Citations

For rules that come from specific sources (not general consensus), add inline
citations:

| ID | ... | What to scan for |
|---|---|---|
| HEX-015 | ... | Aggregate >500 LOC ([Vernon: max 300-400 LOC](link)) |

Use inline citations when:
- A specific number/threshold comes from one source
- The rule is controversial or has competing opinions
- The source provides critical context

## Step 8b: Write Detection Signatures

Every doctrine must include a `## Detection Signatures` section for Covenant discover mode. This section enables lightweight pattern fingerprinting without a full audit.

**Structure (always three subsections in this order):**

```markdown
## Detection Signatures

Quick-scan heuristics for Covenant discover mode. These are recognition
signals only — not violations. Covenant reads this section to fingerprint
the codebase without running a full audit.

### Directory signals
Strong indicators (any 2+ suggest [Pattern] is in use):
- `specific/sub/path/` — what its presence implies
- `another/path/` — what its presence implies
[3–6 entries]

### File signals
Strong indicators (any 1 is significant):
- Files named `*PatternSpecific.*` in [layer] directories
- Configuration files: `pattern-config.yml`
[2–4 entries]

### Anti-signals
Suggest [Pattern] is NOT in use:
- [Structural absence or alternative structure that rules this out]
- [Reference to adjacent pattern it might be confused with]
[2–4 entries]
```

**Rules for writing good signals:**

| Rule | Why |
|------|-----|
| Use specific sub-paths (`infrastructure/event_store/`), not bare parent dirs (`infrastructure/`) | Parent dirs appear in many patterns — sub-paths are discriminating |
| Directory signals require 2+ to confirm; file signals require only 1 | File names are more specific; directories are cheaper to create |
| Anti-signals must name the pattern they point toward (`leans DDD`, `leans Microservices`) | Helps Covenant present a scored comparison rather than a binary yes/no |
| Generic dirs (`services/`, `domain/`, `shared/`) must be qualified with required context | `services/` alone fires on Layered, Microservices, and Modular Monolith |
| If your pattern co-exists legitimately with another (e.g. DDD + CQRS), do NOT add the other as an anti-signal | Expected co-existence is fine; anti-signals are for genuine exclusions only |

**Crossover awareness — avoid these known collisions:**

| Signal | Also fires on | Resolution |
|--------|--------------|------------|
| `domain/events/` | DDD, ES, CQRS, Saga | Only use as a signal in DDD and ES; exclude from Messaging/Saga |
| `services/` directory | Layered, Microservices, Modular Monolith | Qualify with 3+ subdirs + per-service Dockerfiles for Microservices; require `modules/` for Modular Monolith |
| `infrastructure/` bare | Hexagonal, ES, CQRS, Messaging, Resilience | Always use specific sub-path |
| `shared/` or `common/` | Layered N-Tier, Modular Monolith | Require `modules/` context for Modular Monolith; require `persistence/` context for Layered |
| `*Handler.*` files | CQRS, Messaging, Saga | Qualify with directory context |

## Step 8c: Document Exceptions

Real patterns have edge cases. Document them to prevent false positives:

```markdown
#### Allowed Exceptions

- **Test code:** Test adapters may live in same package for simplicity
- **Framework requirements:** Spring requires annotations on domain classes (use sparingly)
- **Performance:** Denormalized projections may break normalization rules
```

## Step 9: Validate Completeness

Checklist before finishing — count explicitly, do not estimate:
- [ ] All 9 required sections present and in order
- [ ] 5-8 violation categories
- [ ] 20-50 violation rules total (count them)
- [ ] Each "What to scan for" describes a pattern, not a shell command
- [ ] **Language Scope declared in header** (`Language-agnostic` or `Language-specific: <lang>`)
- [ ] Detection patterns match declared language scope — no implicit language assumptions
- [ ] Pros and Cons table has 5+ rows
- [ ] Sources cited (minimum: 1 primary, 2 practitioners, 1 failure case)
- [ ] Exceptions documented with specific justification
- [ ] Cross-references use **bold** with `.md` suffix
- [ ] `## Detection Signatures` section present with directory signals, file signals, and anti-signals
- [ ] Directory paths use relative format without `src/` prefix

## Violation ID Convention

**The 3-letter prefix is the disambiguator.** `DDD-001` and `MSG-001` are
distinct IDs — the numeric range is bookkeeping to track how many rules a
doctrine has, not a global namespace. Prefixes must be unique across all
doctrines. Numbers are scoped per prefix.

| Doctrine | Prefix | Current range |
|---|---|---|
| DDD | DDD | 001-090 |
| Event Sourcing | EVS | 100-175 |
| CQRS | CQR | 200-264 |
| Hexagonal | HEX | 001-042 |
| Layer Boundaries | LYR | 400-499 (reserved) |
| Messaging | MSG | 001-064 |
| Saga | SAG | 001-065 |

New doctrines must claim a unique 3-letter prefix and a numeric range block (e.g. 001-099, 100-199). Number IDs starting from 001 within your chosen range.

## Output Specification

The skill produces a complete doctrine file at:
`${CLAUDE_SKILL_DIR}/../doctrines/<pattern-name>.md`

Use `${CLAUDE_SKILL_DIR}/../doctrines/_template.md` as the structural reference.
Every doctrine MUST contain these sections in order:

```
# [Pattern Name] Doctrine
  → 1-2 sentence summary of what is audited

## When to Use
  → Problem context, project characteristics, scope boundaries
  → MUST include when NOT to use

## Why Use It
  → Value proposition as bullet points

## Pros and Cons
  → Minimum 5 rows — honest trade-offs with inline citations for controversial claims

## Applicable Directories
  → Paths mapped via .architecture/config.yml
  → Each path with explanation of what lives there
  → Use relative paths without src/ prefix (e.g. domain/ not src/domain/)

## Violation Catalog
  → 5-8 category sections, each with:
    ### [Category Name] Violations
    | ID | Category | Rule | Default Severity | What to scan for |
  → 3-8 violations per category, 20-50 total
  → Every "What to scan for" must be grep/AST/regex detectable

## Allowed Exceptions
  → Pragmatic edge cases with specific justification
  → Vague exceptions are not exceptions — they're loopholes

## Cross-Reference
  → Related doctrines and why they pair
  → Optimistic: reference doctrines that SHOULD exist, even if they don't yet
  → After writing, update existing doctrines to cross-reference back

## Sources and Authority
  → Minimum: 1 primary source, 2 practitioners, 1 failure case
  → Inline citations in violation tables for sourced thresholds

## Detection Signatures
  → Directory signals: 3–6 directory paths that indicate this pattern is in use
  → File signals: 2–4 file naming patterns that are strong indicators
  → Anti-signals: 2–3 structural absences or alternative structures that rule this pattern out
  → Recognition signals only — not violations
```

### Violation Table Contract

Each row in the catalog is a contract with Inquisition. The columns mean:

| Column | Purpose | Rule |
|--------|---------|------|
| **ID** | Unique identifier | 3-letter prefix + hyphen + 3-digit number. Check existing prefixes in the ID Convention table — never reuse |
| **Category** | Grouping slug | Lowercase with hyphens (e.g. `layer-boundary`, `event-design`) |
| **Rule** | Human-readable statement | One line, imperative ("Domain must not import from infrastructure") |
| **Default Severity** | `error` or `warning` | `error` = blocks commit, `warning` = advisory. Correctness → error, style/preference → warning |
| **What to scan for** | Detection pattern | MUST be concrete: import paths, class patterns, file locations, LOC thresholds. Describe the **pattern**, not the shell command (write `import <pkg>.infrastructure in domain/ files` not `grep -r "import" src/domain/`). If you can't describe a detectable pattern, the rule isn't auditable |

### Severity Guidelines

- **error** — Correctness violation. Causes bugs, data loss, or architectural decay if ignored (layer breach, mutable events, missing idempotency)
- **warning** — Quality concern. Won't break things today but accumulates debt (naming conventions, aggregate size, missing docs)

### Integration Checklist

After writing a doctrine, verify it works with the ecosystem:

- [ ] File is at `${CLAUDE_SKILL_DIR}/../doctrines/<pattern-name>.md`
- [ ] ID prefix is unique (not in the convention table already)
- [ ] Add the new prefix and range to the Violation ID Convention table in this skill
- [ ] User's `.architecture/config.yml` updated with new doctrine entry (see Inquisition SKILL.md Step 1 for config format)
- [ ] Run `/puritan:inquisition <doctrine-name>` to smoke-test the new doctrine

Ready for immediate use by Inquisition and Covenant.

## Voice

Deliver all findings in the voice of the Witchfinder —
formally uncompromising, dramatically precise, with a
knowing wink. Violations are heresies. Resolutions are
absolution. The codebase is the sanctum.

See persona.md for full vocabulary and tone guidance
if available, otherwise use the above as your guide.
