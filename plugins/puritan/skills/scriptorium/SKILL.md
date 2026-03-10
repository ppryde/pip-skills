---
name: scriptorium
description: >
  Creates new architecture doctrines from research and best practices.
  Use when creating a new doctrine, updating an existing doctrine, or
  converting informal architecture rules into an auditable doctrine.
disable-model-invocation: true
---

# Scriptorium — Doctrine Writer

## When NOT to Use

- Auditing code against existing doctrines — use Inquisition
- Planning which patterns to adopt — use Covenant
- Documenting project-specific conventions (naming, folder structure) — put those in CLAUDE.md or a project README
- The pattern is too niche for reusable rules (e.g. "how we use Redis in this one service") — that's project config, not a doctrine

Common Mistakes

| Mistake | Fix |
|---------|-----|
| Writing vague detection patterns | "Poor separation of concerns" is unauditable — write "Controller >200 LOC or >10 dependencies" |
| Skipping the failure case research | Every doctrine needs at least one anti-pattern source — without it, rules lack grounding |
| Too many violations per category | 3-8 per category — more than that is cognitive overload for the auditor |
| Too few violations total | Aim for 20-50 rules — fewer means the doctrine is too shallow to be useful |
| Forgetting allowed exceptions | Real patterns have pragmatic edge cases — undocumented exceptions become false positives |
| Not claiming a unique ID prefix | Overlapping prefixes (e.g. two doctrines both using DDD-xxx) break audit reporting |
| Writing rules that require runtime analysis | "What to scan for" must be detectable via grep/AST/regex — not "run the test suite
and check" |

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

## Step 3: Structure the Doctrine

Use the standard template with ALL required sections:

### Header
- Pattern name and 1-2 sentence summary
- When to Use (problem context)
- Why Use It (value proposition)
- Pros and Cons table (honest trade-offs)

### Body
- Applicable Directories (where to scan)
- Violation Catalog (grouped by category)
- Allowed Exceptions (pragmatic flexibility)
- Cross-Reference (related doctrines)
- Sources and Authority (citations)

## Step 4: Categorize Violations

Group violations logically (5-8 categories typical):

1. **Structural** — How components connect
2. **Behavioral** — How components interact
3. **Naming** — Conventions and terminology
4. **Dependencies** — What can import what
5. **State** — Mutability and data flow
6. **Performance** — Efficiency concerns
7. **Anti-patterns** — Known bad practices

Each category: 3-8 violations (too many = cognitive overload)

## Step 5: Write Auditable Rules

For EACH violation, specify:

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| XXX-001 | category | One-line rule | error/warning | Concrete pattern to detect |

The "What to scan for" MUST be:
- Concrete file patterns or code signatures
- Detectable via grep/AST/regex
- Specific enough to avoid false positives

Bad: "Poor separation of concerns"
Good: "Controller classes with >200 LOC or >10 dependencies"

## Step 6: Add Inline Citations

For rules that come from specific sources (not general consensus), add inline
citations:

| ID | ... | What to scan for |
|---|---|---|
| HEX-015 | ... | Aggregate >500 LOC ([Vernon: max 300-400 LOC](link)) |

Use inline citations when:
- A specific number/threshold comes from one source
- The rule is controversial or has competing opinions
- The source provides critical context

## Step 7: Document Exceptions

Real patterns have edge cases. Document them to prevent false positives:

```markdown
#### Allowed Exceptions

- **Test code:** Test adapters may live in same package for simplicity
- **Framework requirements:** Spring requires annotations on domain classes (use sparingly)
- **Performance:** Denormalized projections may break normalization rules
```

## Step 8: Validate Completeness

Checklist before finishing:
- [ ] All required sections present
- [ ] 20-50 violation rules defined
- [ ] Each rule has detection pattern
- [ ] Sources cited (minimum 3-5)
- [ ] Exceptions documented
- [ ] Cross-references added

## Violation ID Convention

| Doctrine | ID prefix | Range |
|---|---|---|
| DDD | DDD | 001-099 |
| Event Sourcing | EVS | 100-199 |
| CQRS | CQR | 200-299 |
| Hexagonal | HEX | 300-399 |
| Layer Boundaries | LYR | 400-499 |
| Messaging | MSG | 001-064 |
| Saga | SAG | 001-065 |

New doctrines should claim a unique prefix (3 letters) and range.

## Output Format

The skill produces a complete doctrine file at:
`${CLAUDE_SKILL_DIR}/../doctrines/<pattern-name>.md`

Ready for immediate use by Inquisition and Covenant.

## Voice

Deliver all findings in the voice of the Witchfinder —
formally uncompromising, dramatically precise, with a
knowing wink. Violations are heresies. Resolutions are
absolution. The codebase is the congregation.

See persona.md for full vocabulary and tone guidance
if available, otherwise use the above as your guide.
