# review-panel — Design Spec

**Date:** 2026-08-14
**Status:** Approved design, ready for implementation plan
**Author:** Pip (with Claude)

## 1. Summary

`review-panel` is a standalone Claude Code plugin that runs code review
through **composable, swappable lenses**. A review is built from two
orthogonal axes bundled into a named **profile**:

- **Reviewers** — *what* to examine (security, correctness, tests…). Each
  reviewer is a hybrid file: a concern catalogue + severity ladder + voice
  + the review techniques it employs.
- **Strategies** — *how* to orchestrate the review (committee, blind,
  informed, adversarial, dual+tiebreaker).

Both axes are markdown files discovered dynamically at runtime, so new
reviewers *and* new strategies drop in with no changes to the skill.

The plugin is deliberately **neutral in voice** and free of any
repo-specific hardcoding, so it is portable — usable in this repo and at
work unchanged.

### Why it exists / niche

The repo already has three review-adjacent tools; `review-panel` occupies
a distinct niche:

- **puritan** audits against *architectural doctrine* (fixed lens set,
  system-design focus).
- **review-clone** reviews as a *specific real person* cloned from their
  GitHub history.
- **tribunal** triages *PR comments*.
- **review-panel** reviews the *code itself* through a chosen *style and
  strategy* of review.

### Research grounding

Design informed by a survey of agent code-review patterns. Key findings:

- Review has two separable dimensions: **strategy** (how the review is
  orchestrated) and **technique** (how a reviewer inspects — data-flow,
  control-flow, change-impact, test-driven, etc.).
- **Committee review** (specialist reviewers in parallel + an orchestrator
  that merges structured output) is the strongest pattern for quality; it
  is our default.
- Other strategies trade quality for speed or bias-reduction: blind pass,
  informed review, adversarial pair, dual review with tiebreaker,
  self-review loop.
- Best practice is a **hybrid** — pick the strategy to match change risk.

## 2. Concepts

### Reviewer (lens)

One `skills/reviewers/<name>.md` file. Hybrid: fuses a concern with a
voice. Sections:

- **Concern** — what this reviewer cares about, in one paragraph.
- **When to seat / when not** — scope boundary.
- **Techniques employed** — from the research technique taxonomy
  (data-flow, control-flow, change-impact, checklist, test-driven,
  top-down/bottom-up, trace-based, use-case-driven, cross-referencing).
- **What to look for** — a catalogue table: `ID | category | rule |
  default severity | what to scan for`. This is the reviewer's ruleset.
- **Severity guidance** — how it grades error/warning/info.
- **Voice** — tone (default: neutral-professional, direct).
- **Allowed exceptions** — "what it lets go".
- **Sources** — authorities for the rules.

Reviewer IDs are prefixed per reviewer (e.g. `SEC-003`, `COR-011`) so
findings are traceable.

**Reviewer sources.** A reviewer on a panel comes from one of two places,
both producing the same finding contract (§7):

1. **Built-in** — `skills/reviewers/<name>.md`, referenced by bare name.
2. **Clone persona** — a review-clone persona at
   `~/.claude/review-clone/<alias>/PERSONA.md` (resolved under the active
   `CLAUDE_CONFIG_DIR`), referenced as `clone:<alias>`. The engine reads
   the persona's rules + voice and dispatches them as a normal reviewer
   subagent, **carrying over review-clone's non-negotiable gates**: the
   symbol/API reality check (skip a rule whose symbol is absent from the
   target repo), cite-or-refuse (every finding cites a real comment URL),
   and the persona's "what they let go" list. This lets any cloned
   reviewer be seated on any panel and run under any strategy. See §7a.

### Strategy (orchestration recipe)

One `skills/strategies/<name>.md` file. The orchestrator reads the selected
strategy and executes its recipe. Sections:

- **Summary** — one line.
- **When to use** — risk level it suits.
- **Context handling** — what context reviewers receive (diff only vs
  diff + spec/architecture).
- **Stages** — ordered dispatch: subagent roles, inputs per stage.
- **Reconciliation** — how findings are merged / confirmed / dropped.
- **Cost note** — relative speed/expense.

### Profile

A named bundle in `.review-panel/config.yml` that composes the two axes
plus scope and strictness. This is the unit a person "builds a review
from". Shipped defaults + user overrides.

### Scope

- `changed` (default) — `git diff` against the merge-base with the base
  branch.
- `full` — all files matching the profile's `targets:` globs (or repo
  default if unset).

### Strictness

Per-reviewer, one of `strict` / `pragmatic` / `aspirational`. Downgrades
severities exactly as puritan's inquisition does:

- `strict` — keep original severities.
- `pragmatic` — the reviewer's listed allowed-exceptions become warnings.
- `aspirational` — all findings become warnings.

## 3. Strategies (v1)

| Strategy | Shape | Best for |
|---|---|---|
| `committee` (default) | all reviewers in parallel → orchestrator collates | general, high quality |
| `blind` | committee, reviewers get only the diff + acceptance criteria | bias reduction, high-volume |
| `informed` | committee + `context:` files fed in | design-heavy changes |
| `adversarial` | reviewers find → critic challenges each → judge confirms/drops | high-risk, security / payment |
| `dual-tiebreaker` | two independent passes → arbiter resolves disagreements | medium-high risk |

`committee`, `blind` and `informed` share a base recipe and differ only in
context handling. `adversarial` and `dual-tiebreaker` add reconciliation
stages. `self-review-loop` is noted as a future strategy, not shipped v1.

## 4. Reviewers

### Starter (Epic 1)

- `general` — a single broad-spectrum reviewer with a generalist rubric:
  obvious correctness bugs, unclear code, glaring security/perf issues,
  missing tests. Enough to exercise every strategy end-to-end, and a
  genuinely useful default that **remains** in the catalogue after Epic 2
  as the catch-all lens (the research's "single-pass reviewer with a
  rubric" pattern). Ships with `_template.md`.

### Specialist catalogue (Epic 2)

Core six, plus fast-follows:

- `security` — injection, authz, secrets, unsafe deserialization.
  Techniques: data-flow (taint), change-impact, checklist (OWASP).
- `correctness` — logic errors, edge cases, off-by-one, nullability.
  Techniques: control-flow, use-case-driven, trace-based.
- `test-coverage` — missing tests, weak assertions, untested edges.
  Techniques: test-driven.
- `readability` — naming, cohesion, complexity, comment rot.
  Techniques: top-down, checklist.
- `minimalist` — YAGNI, dead code, needless abstraction, over-engineering.
  Techniques: change-impact, bottom-up.
- `api-design` — contracts, breaking changes, backward compatibility.
  Techniques: cross-referencing, change-impact.

Fast-follow reviewers (one-file adds, not blocking v1): `error-handling`
(silent failures), `staff-engineer` (blast-radius/ops), `mentor`
(teaches the why).

## 5. Configuration

`.review-panel/config.yml` (shipped with defaults; user-editable):

```yaml
defaults:
  strategy: committee
  scope: changed
  voice: neutral

profiles:
  pre-merge:
    strategy: committee
    scope: changed
    reviewers: { security: strict, correctness: strict, test-coverage: pragmatic }
  payment-change:
    strategy: adversarial
    reviewers: { security: strict, correctness: strict }
  design-heavy:
    strategy: informed
    context: [docs/spec.md, docs/architecture.md]
    reviewers: { staff-engineer: pragmatic, api-design: strict }
  quick-pass:
    strategy: blind
    reviewers: { minimalist: pragmatic, readability: aspirational }
  senior-eyes:                 # mix built-in + a cloned persona
    strategy: committee
    reviewers: { general: pragmatic, "clone:danvk": strict }

output:
  default: report              # report | inline | interactive
  file: .review-panel/last-review.md
```

Reviewer keys are either a built-in name (`general`, `security`, …) or a
`clone:<alias>` reference to a review-clone persona (§7a).

Optional `.review-panel/decisions.yml` overrides individual findings by ID
(severity + reason), mirroring puritan's decisions file.

## 6. Invocation

| Command | Effect |
|---|---|
| `/review-panel` | default profile, its scope |
| `/review-panel <profile>` | named profile |
| `/review-panel <profile> full` | override scope to whole repo |
| `/review-panel <profile> interactive` | interactive walk |
| `/review-panel <profile> inline` | post inline to the PR |
| `/review-panel <reviewer> [<reviewer>…]` | ad-hoc committee of named reviewers over changed files (no config edit) |
| `/review-panel reviewers` | list available reviewers (built-in + `clone:<alias>` personas found under the config dir) |
| `/review-panel strategies` | list available strategies |

Pre-flight size check (from inquisition): if scope exceeds ~100 files,
warn / prompt before dispatching subagents.

## 7. Execution & finding contract

Every reviewer subagent is dispatched with `model: sonnet` (per standing
rule; never Fable) and returns one shared JSON contract:

```json
{
  "reviewer": "security",
  "files_scanned": 8,
  "findings": [
    {
      "id": "SEC-003",
      "file": "src/auth/login.py",
      "line": 42,
      "rule": "User input reaches SQL without parameterization",
      "actual": "cursor.execute(f\"...{username}...\")",
      "severity": "error",
      "category": "injection",
      "suggestion": "Use parameterized query"
    }
  ],
  "clean_files": ["src/auth/session.py"],
  "notes": ["Could not parse src/legacy.py"]
}
```

Multi-stage strategies extend each finding with a `verdict`
(`confirmed` / `refuted` / `weakened`) plus a reason, produced by the
critic/judge (adversarial) or arbiter (dual-tiebreaker) stage before
collation. Refuted findings are dropped; weakened ones are downgraded.

## 7a. Clone-persona adapter

When a profile names a `clone:<alias>` reviewer:

1. Resolve `<config-dir>/review-clone/<alias>/PERSONA.md`. If it is
   missing, warn and skip the reviewer (do not error) — same policy as a
   missing built-in reviewer.
2. Load the persona: frontmatter (filters, output prefs — informational)
   and the body (rules + voice). The rule list is the reviewer's
   catalogue; the voice section drives tone.
3. Dispatch a reviewer subagent seeded with the persona body, instructed
   to return the standard finding contract (§7). Each finding's `id` is
   `CLONE-<alias>-NNN`; its `rule` is the persona rule; its `actual` is
   the offending code; the cited comment URL goes in a `citation` field.
4. Apply review-clone's gates inside that subagent before emitting:
   - **Symbol/API reality check** — if a rule names a symbol absent from
     the target repo, silently skip that rule.
   - **Cite-or-refuse** — a finding must cite a real persona comment URL;
     if it cannot, drop it.
   - **Let-go check** — drop anything matching the persona's "what they
     let go" section.
5. From here the persona's findings are indistinguishable from any other
   reviewer's and flow through the selected strategy (committee critic,
   dual arbiter, etc.) unchanged.

The engine only *reads* persona files; it never scrapes GitHub or
refreshes them — that stays review-clone's job. If review-clone is not
installed or no personas exist, `clone:` reviewers simply warn and skip,
and the rest of the panel proceeds.

## 8. Output modes

- **report** (default) — collated ruling grouped by reviewer → severity,
  emitted to chat and written to `.review-panel/last-review.md`.
- **inline** — confirmation-gated, batched `gh api …/pulls/<n>/reviews`
  posting, reusing review-clone's inline-posting pattern (one comment per
  anchorable finding, un-anchorable findings bundled into the summary).
  Never auto-posts.
- **interactive** — walk findings one at a time: fix / explain / skip /
  accept-exception, like inquisition's interactive mode.

## 9. Directory structure

```
plugins/review-panel/
  .claude-plugin/plugin.json
  README.md
  commands/review-panel.md          # /review-panel slash command
  skills/
    convene/SKILL.md                # orchestrator + auto-trigger
    reviewers/
      _template.md
      security.md
      correctness.md
      test-coverage.md
      readability.md
      minimalist.md
      api-design.md
    strategies/
      _template.md
      committee.md
      blind.md
      informed.md
      adversarial.md
      dual-tiebreaker.md
```

Reviewers and strategies live under `skills/` as siblings of the
orchestrator skill, mirroring puritan's `skills/doctrines/` layout.
Discovery excludes any file whose basename starts with `_`.

## 10. Portability

- No hardcoded paths to this repo; all config lives in the target repo's
  `.review-panel/`.
- Neutral voice by default; no Witchfinder persona.
- Reviewers and strategies are self-contained files that travel with the
  plugin.
- Only external dependency is `gh` (for `inline` output only); `report`
  and `interactive` need only git.

## 11. Error handling

- **Missing config** — offer to write a starter `.review-panel/config.yml`
  from the shipped defaults; do not hard-error.
- **Missing reviewer/strategy file** — warn and continue with what is
  available (a profile naming an absent reviewer skips it with a warning).
- **Subagent failure** — surface the error, continue with other reviewers,
  never silently drop a reviewer.
- **No open PR** (inline mode) — fall back to `report`, nothing lost.

## 12. Out of scope (v1)

- `self-review-loop` strategy (documented as future).
- Fast-follow reviewers (`error-handling`, `staff-engineer`, `mentor`) —
  easy adds, not blocking.
- CI wiring examples (can follow puritan's hook/Makefile/CI section later).
- Cross-model dual review (dual-tiebreaker v1 uses two independent passes
  of the same model; different models is a future enhancement).

## 13. Epic decomposition

The work splits into two epics with independent spec → plan → build cycles.
The engine is the risk; it ships and is proven first.

### Epic 1 — Strategy engine (get it working)

The full orchestration spine, proven end-to-end:

- Plugin scaffold: `plugin.json`, `README.md`, `commands/review-panel.md`,
  `skills/convene/SKILL.md`.
- Config: `.review-panel/config.yml` loading, profiles, scope resolution,
  strictness, `decisions.yml` overrides.
- Strategies + `_template`: `committee`, `blind`, `informed`,
  `adversarial`, `dual-tiebreaker`.
- Shared finding contract + collation.
- Output modes: `report` (+ file), `interactive`, `inline`.
- Invocation + pre-flight size check.
- **Starter reviewer:** a single `general` reviewer (+ `reviewers/_template.md`)
  — enough to run every strategy, and a keeper.
- **Clone-persona adapter (§7a):** seat `clone:<alias>` reviewers from
  review-clone personas, carrying over their gates.

**Exit criteria:** every strategy runs against a real diff and produces a
collated ruling in all three output modes, using the `general` reviewer
and/or a clone persona.

### Epic 2 — Reviewer catalogue (fold in)

The specialist lenses, on top of the working engine:

- Core six: `security`, `correctness`, `test-coverage`, `readability`,
  `minimalist`, `api-design` — full catalogues, techniques, sources.
- Fast-follows: `error-handling`, `staff-engineer`, `mentor`.

**Exit criteria:** shipped profiles run against their full reviewer sets.

## 14. Open questions

- Exact reviewer ID prefixes (e.g. `SEC`, `COR`, `TST`, `RDB`, `MIN`,
  `API`) — finalise during authoring.
- Whether `voice:` should offer named tone presets beyond `neutral`, or
  stay a single neutral default for v1.
