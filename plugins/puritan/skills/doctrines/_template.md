# [Pattern Name] Doctrine

[1-2 sentence summary: what this doctrine audits and why it matters.]

## When to Use

[Describe the problem context where this pattern applies. Be specific about
project characteristics, team size, domain complexity, and business needs.
Also state when NOT to use it — every pattern has a scope boundary.]

## Why Use It

[Value proposition — what does this pattern give you that alternatives don't?
Use bullet points for concrete benefits:]
- Benefit one — with brief explanation
- Benefit two — with brief explanation
- Benefit three — with brief explanation

## Pros and Cons

| Pros | Cons |
|---|---|
| [Concrete advantage] | [Honest trade-off or cost] |
| [Concrete advantage] | [Honest trade-off or cost] |
| [Concrete advantage] | [Honest trade-off or cost] |
| [Concrete advantage] | [Honest trade-off or cost] |
| [Concrete advantage] | [Honest trade-off or cost] |

[Minimum 5 rows. Include inline citations for controversial claims, e.g.
([Fowler: "beware risky complexity"](link))]

## Applicable Directories

Primary targets (mapped via `.architecture/config.yml`).
Use relative paths without `src/` prefix (e.g. `domain/` not `src/domain/`):
- `path/to/scan/` — what lives here and why it matters
- `another/path/` — scoped explanation

## Violation Catalog

### [Category Name] Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| XXX-001 | category-slug | One-line rule statement | error | Describe the pattern to detect — NOT a shell command |
| XXX-002 | category-slug | One-line rule statement | warning | e.g. `from <pkg>.infrastructure` in domain/ files |

[Add a brief "Scanning approach" note after each category table if the
detection method isn't obvious from the "What to scan for" column.]

[You MUST have 5-8 categories, 3-8 violations per category, 20-50 total.
Count your rules before finishing. Fewer than 20 = too shallow.]

### [Category Name] Violations

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| XXX-010 | category-slug | Rule | error/warning | Detection pattern |

## Allowed Exceptions

- **[Exception name]:** Explanation of when this violation is acceptable
  and why. Be specific — vague exceptions become loopholes.
- **[Exception name]:** Another pragmatic edge case with justification.

## Cross-Reference

Reference doctrines that pair with this one — even if they don't exist yet.
Use the filename they would have. Inquisition handles missing doctrines
gracefully. When the doctrine is eventually written, the cross-references
are already wired up.

This doctrine pairs well with:
- **[other-doctrine].md** — brief explanation of relationship
- **[other-doctrine].md** — brief explanation of relationship

## Sources and Authority

**Foundational Works:**
- [Author - Title (Year)](url) — Brief note on relevance
- [Author - Title (Year)](url) — Brief note on relevance

**Practitioner Guidance:**
- [Author - Title](url) — Brief note on relevance

**Anti-Patterns / Failure Cases:**
- [Author - Title](url) — What goes wrong without this pattern

[Minimum: 1 primary source, 2 practitioners, 1 failure case study.]
