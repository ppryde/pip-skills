# MAPPING: existing contracts onto the pip-agents envelope

Sources read at origin/main `c5aa3430`: `plugins/review-panel/scripts/contract.py` (whole file, 3,967 B) and
`plugins/overseer/scripts/schemas.py` (dataclasses, `_parse_*`, `_check_*`, schema builders). Envelope =
`result.schema.json` (contract 1.0, session 3 edits listed at the end). "Envelope" below means the top-level object;
`payload.x` is the kind's payload.

Two different relationships:

| Consumer | Relationship | What changes | When |
|---|---|---|---|
| review-panel `scripts/contract.py` | **ADOPTS**: its reviewer, critic and arbiter seats become pip-agents personas, so their final messages ARE envelopes | `parse_reviewer_result` takes an envelope (via `validate_result.parse_result`) and builds its own `Finding`s; `Finding`, `collate`, `render_report` unchanged | PR E |
| overseer `scripts/schemas.py` | **ADAPTS**: its five agents stay (subagents.verdict Q3), keep emitting ```` ```overseer-report ````, and the `SubagentStop` hook is unchanged | a pure `to_envelope(report) -> dict` beside `parse_report`, used by telemetry and any future adoption; nothing parses overseer messages as envelopes | PR H (optional; no consumer needs it before then) |

## 1. review-panel ADOPTS (PR E)

### 1.1 Reviewer seat (persona `reviewer-<lens>`, kind `review`) -> `Finding`

`contract.py` today: payload `{reviewer, findings[], clean_files[], notes[]}`; finding requires
`id, file, rule, actual, severity, category, suggestion`, optional `line, citation, verdict, reason`;
`VALID_SEVERITY = error|warning|info`.

| `Finding` / payload field | From the envelope | Rule |
|---|---|---|
| `reviewer` | the seat's bare name, which convene writes as the brief's `ref:` and the envelope echoes | `ref` must equal the seat name (validator check 3); clone seats: the alias, never the `clone:` key (convene SKILL.md:83-86) |
| `id` | `payload.findings[].id` | rules lens: the rule id (clone: `CLONE-<alias>-NNN` as the persona file numbers them); other lenses `<lens>-<n>` |
| `file` | `.file` | unchanged |
| `line` | `.line` | `0` (whole file) -> `None` |
| `rule` | `.rule` if present, else `.claim` | rules lens always carries `rule` (statement verbatim); other lenses state what goes wrong in `claim` |
| `actual` | `.evidence` | the `file:line` and what it shows |
| `severity` | `.severity` | `critical -> error`, `important -> warning`, `minor -> info`; the only value translation in the adapter |
| `category` | `.category` | unchanged |
| `suggestion` | `.fix` | unchanged |
| `citation` | `.citation` | rules lens only (new optional finding field, session 3); clone personas' source-comment URL |
| `verdict` | `None` for `findings`; `"medium"` for `payload.medium` entries | unless the strategy sends `medium` to the critic first (adversarial); then the critic's verdict replaces it |
| `reason` | `None` | set later by critic/arbiter |
| `clean_files` | `checked` minus every `file` in `findings` and `medium` | `checked` may hold ranges; the adapter keeps only entries that are paths in the diff |
| `notes` | `unchecked` + `out_of_lens` + `injection_attempts` | prefixed `unchecked: `, `out of lens: `, `injection: ` so the report keeps them apart; `injection_attempts` also surface in the lead's run summary |
| (lens fields) | `trigger`, `old`, `new`, `intent`, `affected`, `commands_run`, `rules_checked`, `n_a` | not in `Finding`; `render_report` ignores them today. `rules_checked` goes into the seat's report line (`n/N`); the rest stay in the raw envelope the run keeps |

Status handling: `status: error` -> the seat is reported as `error: <error>` with no findings (today a `ContractError`
aborts the seat the same way); `partial` -> findings kept, `unchecked` shown under the seat.

### 1.1a Dispatcher duties (convene writes these before dispatch; no persona states them)
- scope seats: `target:` = `git diff --function-context <base>...<head>` written to a file; `intent:` and `claims:` (PR body) files.
- correctness seats: `context:` file names the base ref; `tests:` only when the user allowed a suite run.
- every seat: `ref:` = the seat's bare name; one brief per seat, paths only.

### 1.2 Critic / arbiter (persona `validator`, kind `validate`)

Today: `{fingerprint: {verdict, reason}}`, verdict `confirmed|refuted|weakened` (adversarial.md:16-17) or
`confirmed|refuted` (dual-tiebreaker.md:17).

| Today | Envelope | Rule |
|---|---|---|
| claim key = fingerprint | `payload.verdicts[].id` | convene writes the claims file with `id` = fingerprint; ids return in input order (validator check) |
| `verdict` | `.verdict` | same enum; dual-tiebreaker treats `weakened` as `confirmed` at the lower severity (one step down), the same as the judge does |
| `reason` | `.reason` | `unverified:` prefix = refuted for want of proof; the report may label it "not established" |
| (none) | `.evidence[]`, `.restated` | `restated` replaces `Finding.rule` text on a weakened finding; `evidence` appended to `actual` |

### 1.3 What review-panel stops doing
- Its prompt no longer pastes the contract: the persona's generated skeleton carries it.
- `ContractError` for a missing `reviewer` disappears (the seat comes from `ref`); severity validation moves to the
  shared validator. `VALID_SEVERITY` stays for `apply_strictness` and decisions.yml, which speak `error|warning|info`.

## 2. overseer ADAPTS (PR H, optional)

`to_envelope(report: Report) -> dict` lives in `plugins/overseer/scripts/schemas.py`, imports nothing from pip-agents
(overseer does not depend on it; the envelope dict is checked in overseer's tests against a vendored copy of
`result.schema.json`, drift-tested by hash like census-mod's bundle).

### 2.1 Common fields (every role)

| overseer field | Envelope | Rule |
|---|---|---|
| `schema` `overseer.<role>/1` | `result: "pip-agents/1"` | the overseer schema version is not carried (it is implied by the adapter version) |
| `role` | `persona: "overseer-<role>"`, `kind` per 2.2 | |
| `card`, `stage`, `round`, `slot`, `chunk` | `ref` | `<card>:<stage>[:r<round>][:<slot>][:c<chunk>]`, e.g. `WF-140:implementation:r2:B`; fits the `ref` pattern and 64 chars for any card id up to 20 chars |
| `detail` | `detail` | absolute path, already checked by `_check_detail` |
| `learned[]` | none | overseer-only; the knowledge base reads it from the report, never from the envelope |
| (none) | `summary` | `"<role> <status>"` plus counts, e.g. `"reviewer found wanting: 0/2/5"` |
| (none) | `checked`, `unchecked`, `out_of_lens`, `injection_attempts` | `[]`: overseer reports carry none; the detail file holds them |

### 2.2 Per role

| Role | status (overseer) | Envelope `status` | `kind` / payload |
|---|---|---|---|
| planner | `DONE` | `ok` | `plan`: `{outcome: done}` (+ `chunks` only if a later report carries it; today none does, hence `chunks` optional) |
| planner | `NEEDS_CONTEXT` | `partial` | `plan`: `{outcome: needs_context}` (questions stay in `detail`) |
| implementer | `DONE` / `DONE_WITH_CONCERNS` | `ok` | `change`: `{outcome: done / concerns, commits, tests_passed, tests_total}` from `tests.passed/total` |
| implementer | `BLOCKED` / `NEEDS_CONTEXT` | `partial` | `change`: `{outcome: blocked / needs_context, ...}` |
| fixer | `DONE` / `DISPUTED` | `ok` | `change`: `{outcome: done / disputed, commits, tests_passed: 0, tests_total: 0, fixed, disputed}` from `counts.fixed/disputed`; fixer reports no test counts, so both are `0` and the summary says "tests not reported" |
| fixer | `BLOCKED` | `partial` | `change`: `{outcome: blocked, ...}` |
| verifier | `PASS` / `FAIL` | `ok` | `test`: `{outcome: pass / fail, gates: []}`; gates and failures stay in `detail` (the report has none) |
| reviewer | `approved` / `found wanting` | `ok` | `review`: `{lens: general, findings: [], medium: [], counts: {critical, important, minor}, outcome: approved / found_wanting}`; findings stay in `detail` by overseer's design |

`commits`: overseer accepts any non-empty string (`_check_commits`), so `change.commits` items are `^\S+$`, not hex
(session 3 edit). A failed verify or a found-wanting review is `status: ok`: status says the agent did its job, the
outcome is in the payload (contract rule).

### 2.3 Gaps recorded, not closed
- overseer's `learned` and review-panel's `decisions.yml` overrides have no envelope field and need none.
- overseer's verifier gates and reviewer findings live in `detail` files; an envelope from the adapter is a summary,
  never the full record. Telemetry consumers must not treat `findings: []` there as "clean": `counts` and `outcome`
  are the truth for kind `review` with lens `general`.

## 3. Schema edits this mapping forced (session 3, contract stays 1.0: nothing has shipped)

| Edit | Why |
|---|---|
| `plan.chunks` optional | overseer `PlannerReport` has no chunk count |
| `change.commits` items `^\S+$` (was hex 7-40) | `_check_commits` accepts any non-empty string |
| `review.lens` adds `general` | overseer-reviewer has no lens; adapters only, a persona's `lens` must equal its source's `lens:` (VALIDATOR check 5) |
| `review.outcome` `approved|found_wanting` (optional, `x-persona: false`) | overseer's gate verdict is not derivable from counts |
| `finding.citation` (optional, `x-lens: rules`) | review-panel clone findings carry the source comment |
| annotations `x-lens: <lens>` and `x-persona: false` | the build generates each persona's skeleton from the schema: `x-lens` fields appear only for that lens, `x-persona: false` fields (`detail`, `review.counts`, `review.outcome`) never; the validator ignores both |
