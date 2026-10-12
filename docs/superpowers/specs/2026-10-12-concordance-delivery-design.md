# concordance delivery redesign: shadow measurement and the full feature set (WF-273)

Date: 2026-10-12. Card: WF-273. Branch: `feat/concordance` (PR #165, bundled).
Builds on `2026-10-11-concordance-design.md` (phase 1).

## Why

Phase 1's bench (7 seeded cases, two runs) showed no proven catch-rate lift over a
plain Read/Grep reviewer and 9-14% more tokens per review. The `review-context` report
was purely additive: reviewers read the same files either way and drilled down in 1 of
28 reviews. The literature agrees: no independent study shows a code index cutting
tokens for a strong agent at equal accuracy; savings come only from *replacing*
reads, and structure helps most on large repos, un-diffed callers and weaker models.

So before dogfooding on a large work repo we build the whole feature set, and we build
the means to measure it honestly. We must be able to tell, per agent activity, what
the agent actually spent against what concordance would have cost to answer the same
need, without changing what the agent does.

## Goals

1. Measure, for every Read, Grep, Edit, test run, git-history command and review in a
   session, the agent's actual token cost and concordance's counterfactual cost, with
   real CLI latency, in pure shadow (nothing injected).
2. Ship all backlog features as CLI commands, each with a replay estimator.
3. Offer an inject mode, switchable per session, whose hooks add concordance output
   beside tool results, so shadow and inject sessions compare side by side.
4. Let chronicle report carried cost (tokens × turns in context, at cache price)
   without chronicle storing any tool input or content.

## Non-goals

- Never block, deny, rewrite or replace an agent tool call. Concordance runs side by side.
- No stored or bulk git history. History features run live from git, bounded.
- No change to chronicle's nature: it stays a statistics store (counts, sizes, tool
  types). It gains no tool inputs, paths of reads, patterns or content.
- No CodeQL dependency (licence), no free-form graph query language.

## Decisions (agreed in brainstorming)

| Decision | Choice |
|---|---|
| Mode | Pure shadow by default; inject switchable per session (`concordance mode`) |
| Measurement | Offline replay of transcripts after a session ends, not hooks |
| Replay mechanism | Run the real CLI per activity (subprocess), recording output tokens and latency; a `batch` entry point only if replay proves too slow |
| Data kept by replay | Numbers and labels only; transcripts are read in memory and dropped |
| Cost metrics | Size (concordance alone) and carried cost (chronicle) |
| Chronicle coupling | One way: chronicle calls concordance's CLI; concordance never reads chronicle |
| Delivery | Single rolling PR #165; built as four sub-projects, each its own plan |

## Sub-projects and order

Each sub-project gets its own implementation plan; all land on `feat/concordance`.

1. **Shadow measurement**: `--json` output for every query command, `replay`, the
   mode switch, `usage.db` replay rows, chronicle's optional reader and report, and
   estimators for the existing commands (`callers`, `tests`, `check`, `removed`,
   `sig-drift`, `literals`, `review-context`).
2. **Savers and labels**: `outline`, `show`, `check --since-edit`, `tests-for`,
   report-only-what-changed `review-context`, the exact/name-matched label, and the
   inject-mode hooks.
3. **New index facts**: override and subclass edges (`implementations`), read vs write
   refs (`writers`), import contracts and cycles (`imports-check`), pattern search
   (`match`).
4. **Live git and orchestration**: `bio`, `hotspot`, `route`.

Dogfooding starts when all four have landed.

## Design

### 1. Replay core

`concordance replay --session <id> [--transcript <path>] --json`

1. **Locate** the session transcript under `$CLAUDE_CONFIG_DIR/projects/<slug>/<id>.jsonl`
   and its subagent transcripts (reviews run as subagents). `--transcript` overrides.
   A session still being written (modified in the last 5 minutes, or with no final
   assistant turn) is refused with exit 2 unless `--force`.
2. **Walk** tool uses and pair each with its result, in memory. Inputs and results are
   never written anywhere.
3. **Match** each tool call to an estimator (section 2). A call no estimator matches is
   emitted as `covered: false`, never dropped.
4. **Ask the real CLI**: run `python <plugin>/scripts/cli.py <command> --json …` as a
   subprocess from the session's working directory (from the transcript's `cwd`),
   with `CONCORDANCE_DB` and `CONCORDANCE_USAGE_DB` inherited. Record output token
   count (the CLI's own `est_tokens` in its JSON), wall-clock latency and exit code.
   Replay's own subprocess calls are tagged `origin=replay` so they are excluded from
   ordinary usage stats.
5. **Judge answerable**: each estimator's rule (section 2) decides `yes`, `no` or
   `unknown` from what happened later in the same session. `unknown` is the default.
6. **Detect drift**: for a Read, compare the git blob hash of the content the agent saw
   (line-number prefixes stripped, whole-file reads only) with the file's current blob.
   A mismatch, or a partial read, sets `drifted: true` or `drift: unknown`. Drifted
   rows are always reported separately.
7. **Emit** one JSON object per tool call:

```json
{"session_id": "…", "tool_use_id": "toolu_…", "agent_id": "", "kind": "read",
 "estimator": "outline", "covered": true, "actual_tokens": 18400,
 "concordance_tokens": 620, "latency_ms": 1480, "exit_code": 0,
 "answerable": "yes", "drifted": false, "mode": "shadow"}
```

`actual_tokens` is the agent's tool result size (characters / 4, the same estimate
the usage log uses). No row carries a path, pattern, command line or content.

Rows are also appended to `usage.db` as `replay` events (one per tool call, payload =
the numeric fields above), so `concordance stats --replay` reports the size
comparison without chronicle. Replaying a session twice replaces its rows (keyed by
`session_id`, `tool_use_id`).

**Modules**: `scripts/replay/` package: `transcript.py` (locate, walk, pair; in
memory), `estimators/` (one module per estimator, each exporting `match(call) ->
Query | None` and `answerable(query, later_calls) -> str`), `runner.py` (subprocess,
timing), `drift.py`, `emit.py`. `cli.py` is split into a `scripts/commands/` package
(one module per command group) as part of sub-project 1, because it gains about
fifteen commands and is already the largest dispatcher.

### 2. Features and their estimators

Saver = could replace tokens the agent spent. Adder = a hook would push it on top;
we measure its cost and hit rate, not a saving.

| # | CLI command | Matches | Type | Answerable rule |
|---|---|---|---|---|
| 1 | `outline <file>`, `show <qualname>` | Read of an indexed file | Saver | yes if every later Edit or quoted line in that file falls within the symbols `show` would return; the counterfactual cost is `outline` + one `show` per such symbol |
| 2 | `callers <qualname>` | Grep whose pattern is exactly an indexed symbol's name | Saver | yes if the files the agent then opened from the Grep hits are a subset of the callers' files |
| 3 | `check --since-edit` | Edit/Write that removes, renames or changes the signature of a def | Adder | yes if the agent later edited a flagged call site or a test failed there; no if flagged sites were never touched and no test covers them |
| 4 | `tests-for --diff` | Bash running pytest or vitest | Saver | yes if the selected tests include every test that failed in the agent's own run; also records tests run vs selected and test-output tokens |
| 5 | `review-context` (report only what changed) | A review subagent's `review-context` call | Saver | compares old and new output size; yes if no BR-00x verdict the old output emitted is missing |
| 6 | exact / name-matched label | (column on 2, 3, 7, 8) | n/a | reported as the share of exact rows |
| 7 | `imports-check` | Edit that adds an import | Adder | yes if a flagged cycle or breach was later removed; unknown without a contracts file |
| 8 | `implementations <qualname>` | Grep for a method name across classes | Saver | as 2 |
| 9 | `writers <name>` | Grep for a field or setting name with an assignment | Saver | as 2 |
| 10 | `match '<pattern>'` | Grep with a call-shaped pattern | Saver | as 2 |
| 11 | `bio <qualname>` | Bash running `git log -L`, `git log -p` or `git blame` on a file | Saver | yes if the agent's command targeted lines within one symbol |
| 12 | `hotspot <file>` | First Read or Edit of a file in a session | Adder | always unknown; reports firing rate and cost |
| 13 | `route --diff` | A review-panel run that starts lens subagents | Saver | yes if each lens's Reads fall within its routed files |

Estimator 2 also covers the existing `tests`, `removed`, `sig-drift` and `literals`
when the agent's activity matches them.

**Feature notes**

- `outline` lists a file's symbols with line ranges and caller counts; `show` returns
  one symbol's source plus a one-line callers/tests note.
- `check --since-edit` compares the worktree view before and after the last change to
  a file (incremental index), emitting only exact rows, at most 5 plus a command.
- `tests-for` walks refs from changed symbols to `is_test` symbols (bounded hops) and
  prints test IDs. Fix the known false positive first: framework-invoked code
  (pydantic validators, decorators registering handlers) has no call edge, so BR-005
  must treat such symbols as reached when their class is constructed in a test.
- `review-context` reports only changed symbols with callers or tests outside the
  diff; prints nothing but a one-line "no un-diffed callers" when the change is
  diff-local. The default budget stays 4000 until dogfooding data says otherwise.
- The label: `refs` gains `resolution TEXT` (`exact` | `inferred` | `ambiguous`),
  already computed at resolve time, now stored and printed on every row.
- Overrides: Python class bases and TypeScript `extends`/`implements` produce
  `refs.kind = 'overrides'` (method level) and `'extends'` (class level), with a
  derived root.
- Read vs write: Python `ast.Store` / `ast.Load` contexts and TS assignment targets
  produce `refs.kind = 'write'` vs `'read'` for attributes and module names.
- `imports-check` reads `.importlinter` or `tach.toml` when present; cycles need no
  config. Reports only violations new against the base view (freeze pattern).
- `match` compiles a small pattern language (call name, `...`, keyword=literal,
  metavariables) to queries over `refs.args_json` and `literals`, alias-aware via
  `alias_of`.
- `bio` runs `git log -L<start>,<end>:<file> --since=90.days -n 20 -s` and
  `git blame -L` over the symbol's range from the index; labelled approximate. No
  history is stored.
- `hotspot` = commit count for the file in 90 days (`git log --since=90.days
  --format=%H -- <file>`) × the symbol's cyclomatic complexity, computed at parse time
  and stored on `symbols` as `complexity INTEGER`.
- `route` maps each review-panel lens to the files it needs (diff files plus exact
  callers and guarding tests within one hop) and prints a per-lens file list.

Every query command gains `--json`: `{"command", "est_tokens", "rows": [...],
"coverage": {...}}`. Text output stays the default and is unchanged.

### 3. Inject mode (hooks)

- `concordance mode inject|shadow [--session <id>]` writes a flag under
  `$CLAUDE_CONFIG_DIR/concordance/modes/` (per session, or the repo default for new
  sessions). Default is shadow.
- The plugin registers command hooks once (`plugins/concordance/hooks/hooks.json`).
  Each hook reads the session's mode first and exits silently in shadow mode.

| Hook | Fires on | Adds beside the tool result | Cap |
|---|---|---|---|
| SessionStart | session start | index stale, if it is | 1 line |
| PostToolUse | first Read of an indexed file per path | `outline` note and a `show` pointer | 5 lines |
| PostToolUse | Edit/Write touching a def | `check --since-edit`, exact rows only | 5 rows + command |
| PostToolUse | Edit adding an import | `imports-check` findings | 3 lines |
| PreToolUse (context only) | Bash running pytest or vitest | "`tests-for` selects N tests" + IDs | 1 line + IDs |
| Stop | end of turn | symbols left with no callers; changed behaviour no test reaches | 5 rows |

Rules: never deny, never exit 2, never rewrite input; any exception is caught, logged
and silent; hard 2 s timeout (silent, logged); report only what is new against the base
view; once per path per session; every injection logged to `usage.db` with
`tool_use_id`, tokens and latency. In inject sessions replay counts injected tokens as
concordance's actual cost.

First task of sub-project 2: confirm against the current hook documentation and a
live probe that PostToolUse and PreToolUse can return additional context to the model,
and which input fields (notably `tool_use_id`) hooks receive.

### 4. Chronicle's side

- **Discovery**: chronicle looks for concordance via the installed plugin's scripts or
  `CONCORDANCE_CLI`. Absent: nothing in this section runs, nothing errors.
- **Replay at sync**: for each session ingested since the last run, in a repo with a
  concordance store, and finished, chronicle runs `concordance replay --session <id>
  --json`. A per-session cursor prevents repeats; failures are marked and retried next
  sync; chronicle's main sync never fails because of concordance.
- **Storage**: new table `concordance_rows(session_id, tool_use_id, agent_id, kind,
  estimator, covered, concordance_tokens, latency_ms, answerable, drifted, mode)`,
  primary key `(session_id, tool_use_id)`. Numbers and labels only.
- **Carried cost**: for each tool result, tokens × assistant turns after it until the
  session ends, is cleared or compacts, priced at the model's cache-read rate from
  chronicle's ratebook. Computed for actual and concordance figures alike.
- **Report**: `chronicle report --concordance [--repo …] [--since …] [--json]`: per
  kind, actual vs concordance size and carried cost, answerable rate, drift rate,
  coverage share; adders show firing rate, cost and hit rate; shadow and inject
  sessions side by side. A dashboard page is out of scope for now.

### 5. Testing

- **Isolation**: every test pins `CLAUDE_CONFIG_DIR`, `CONCORDANCE_DB` and
  `CONCORDANCE_USAGE_DB` (and chronicle's store) to `tmp_path`.
- **Replay fixtures**: hand-built `.jsonl` sessions under `tests/concordance/fixtures/`
  against tiny fixture repos: one per estimator, plus not covered, drifted, partial
  read, crashed CLI, still-running session, inject session, subagent transcript.
- **Numbers only**: a test scans replay JSON and `usage.db` for every path, pattern,
  command and content line in the fixtures and fails on any hit.
- **Parity**: each row's `concordance_tokens` equals the `est_tokens` the CLI reports
  for the same query run directly.
- **Answerable boundaries**: edits just inside, just outside and on the edge of a
  symbol's range; Grep hit subsets; failing test in and out of the selected set.
- **Hooks**: shadow exit under 100 ms; timeout gives no output and a log row; no hook
  ever denies or exits 2; caps enforced; once per path per session.
- **Features**: unit tests per command on Python and TypeScript fixture repos where the
  language applies; `bio` and `hotspot` against a fixture git history built in
  `tmp_path`.
- **Chronicle**: unchanged sync without concordance; failed replay retried; carried cost
  against a fixture session with known turns and prices.

### 6. Dogfooding and success criteria

1. Week 1, pure shadow on pip-skills and the work repo; replay runs at each
   `chronicle sync`.
2. Validate the estimators first: coverage, answerable rate and drift. Fix estimators
   before trusting savings.
3. Week 2, inject mode on alternate sessions in the same repos; compare per-session
   Read tokens, carried cost and how often injections were acted on.
4. Latency budget: any feature whose replayed p95 latency on the work repo exceeds
   2 s stays on demand only.
5. Keep, tune or drop each feature from the numbers; settle the `review-context`
   budget (closes WF-275's budget item).

Success:
- replay covers at least 80% of Read, Grep, Edit and test-run calls;
- a saver stays if inject sessions show lower carried cost with no drop in task outcome;
- an adder stays if its hit rate shows its flags were acted on;
- drifted rows are always reported apart from clean ones.

## Risks

| Risk | Mitigation |
|---|---|
| Replay is slow on long sessions (about 1.5 s per call) | Runs after sessions, never inline; add `concordance batch` only if needed |
| Answerable rules are wrong, so savings are overstated | `unknown` default; week 1 validates estimators before any savings claim |
| Code changed since the session | Drift flag; replay soon after sessions end |
| Hooks too slow on a large repo | 2 s hard timeout, silent; p95 from replay decides hook eligibility |
| Hook API cannot add context where needed | Probed first in sub-project 2; fall back to Stop-hook summaries |
| Scope (13 features) | Four sub-projects, each its own plan and review |
