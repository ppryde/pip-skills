# Overseer token-cost audit — handover

**Date:** 2026-09-16
**Origin:** analysis session in `~/repos/warehouse` (Opus 5 orchestrator + a Fable audit subagent)
**Status:** analysis complete, no code written. All implementation is yours.
**Scope of evidence:** 15 overseer-driven sessions in one repo (`~/repos/warehouse`, a dbt/SQL warehouse repo), overseer 0.23.0, Jun–Sep 2026.

Read this instead of re-deriving. Every number below is measured, not estimated, unless marked as an estimate.

---

## 1. The finding in one paragraph

Overseer is not expensive because it reads large data into context. It is expensive because it generates a very large number of API round trips at a large context size. Across the 15 sessions, the **total unique content ever placed in context** — every tool result, every prompt, every line of model prose — is **~1.6 Mtok. Those sessions consumed 1,204 Mtok of cache reads.** That is a **~750× re-read amplification**. Overseer's own CLI is a perfect illustration: 703 calls returned **0.14 Mtok of text in total** (avg 0.9 kB/call) but cost **~143 Mtok of context re-reads** to make — a ~1000:1 overhead. The information is free; asking for it is what costs money.

Consequence for design: **the only two levers are turn count and per-turn context.** Payload size is already fine and should not be optimised further.

---

## 2. Verified measurements

Cost weighting used throughout: `cache_read ×0.1, cache_creation ×1.25, output ×5, input ×1` ("weighted Mtok" ≈ relative spend).

### Totals (15 overseer sessions)

| | turns | avg ctx | weighted |
|---|---|---|---|
| subagents | 3,230 | 175k | **105 Mtok (55%)** |
| orchestrator | 2,668 | 239k | **85 Mtok (45%)** |
| **total** | **5,898** | ~204k | **191 Mtok** |

- 105 subagents spawned; ~31 turns and 6.3 Mtok raw each.
- **33 of 73 agents ran >40 turns and account for 84% of all subagent cache reads.** The tail is the target, not the mean.
- Subagent turn-1 context averages **69k** (not 53k).
- Subagent reports are already tiny: `Agent` result median **72 tokens**, `SendMessage` median **79 tokens**. Do not optimise these.

### Comparison against non-overseer work in the same repo

| | sessions | avg turns | avg peak ctx | weighted/session |
|---|---|---|---|---|
| overseer | 15 | 393 | 383k | **12.7 Mtok** |
| everything else | 32 | 116 | 224k | 3.8 Mtok |

A 3.3× multiple, driven entirely by turn count (3.4×) and context size (1.7×).

Per-card baselines to plan against: **with-subagents card ≈ 19.4 Mtok** (6.2 orchestrator + 13.2 subagents); **no-subagent card ≈ 5.1 Mtok**.

### Context mechanics

- Fixed preamble (system prompt + tool schemas + MCP listing + CLAUDE.md + skill index) = **53k on turn 1 of every main session**, flat for weeks. Paid on all 5,898 turns = 313 Mtok raw / 31 Mtok weighted (**16%**).
- Context grows **~2,120 tok/turn** (range 1.1k–3.7k across 32 sessions). Decomposition: model output **984 (46%)**, of which thinking 423; tool results **678 (32%)**; user turns + system reminders + tool_use blocks **~460 (22%)**.
- **Output is 15% of weighted spend** (at ×5), thinking alone ~6.5%. Prose is not a rounding error.
- Tool batching: 9,986 calls over 9,606 turns = **1.04 per turn**; only 11% of turns issue >1 call; 11% issue none.
- Peak contexts observed **400k–741k**. 45% of all spend occurs above 300k context, from 23% of turns.
- **Cache is working correctly** — 39 cold turns in 9,606, zero compactions. Do not go looking for a cache bug.

### Overseer's own text is already lean — do not shrink it

`SKILL.md` 11.5kB · `references/` 8.4kB total · `templates/` 8kB · CLI output 0.9kB/call · context footer negligible. There is no win here.

### The budget meter is wrong by ~100×

`usage.jsonl` (per-repo state root) logs **6.9 Mtok** against an actual **~700 Mtok**. It records the dispatch prompt size once and never observes the agent's own loop. Consequence: the tripwire cannot fire, and every `calibration` figure fed to planners is ~100× low. Fixing this is a prerequisite for trusting any of overseer's own budget machinery.

---

## 3. Three structural findings (these dominate)

### F1 — Orchestrator-as-worker: 19% of all spend

**7 of 15 sessions spawned zero subagents** yet ran 109–308 orchestrator turns at 350–460k peak: 264 Snowflake queries, 683 Bash, 143 Edits, 62 Reads. That is **1,242 turns / 35.7 Mtok weighted / 19% of total.** The skill fired (`overseer:orchestrate` tagged on 152 turns) and then the main session did the implementation itself.

Cause: `skills/orchestrate/SKILL.md:15–20` says "the single writer of the card … dispatcher of every agent" but **never says the orchestrator does not Read source, run queries, or Edit anything but the card.** Most of the orchestrator's 45% is not orchestration.

These are also the sessions that hit 400k+, so F1 overlaps the "hand off at 150k" item — do not count both in full.

### F2 — Forks and fat dispatch prompts: 3–4%, zero-effort fix

- **3 agents were forks** — turn-1 `cache_read` 230k–374k with `cache_creation` <6k, i.e. they inherited the orchestrator's entire context. One (`aWF-014-meas`) then ran **112 turns at 230k+**: a single agent ≈ 30+ Mtok raw.
- **6 dispatches opened with 140k–253k of `cache_creation` on turn 1** — the plan/diff/findings were pasted inline. Three of those were 1-turn reviewers: ~0.25 Mtok weighted for one verdict.

Note this is already **against** `references/review-loop.md:4` ("write the diff to a file first; reviewers read files, not pasted walls") and `templates/reviewer.md:6` already takes `{{target_path}}`. The design is right; compliance is not. That is the argument for enforcing it mechanically rather than restating it.

### F3 — Hub overhead is ~75% of the dispatch it serves

Sessions with subagents: 1,426 orchestrator turns / 73 subagents = **19.5 orchestrator turns per dispatch**, at ~240k ≈ **4.7 Mtok raw**, against 6.3 Mtok for the subagent doing the actual work.

Composition: ~10 ledger CLI calls per dispatch (703/73); template filling (the orchestrator *emits* plan/findings/knowledge as output at ×5 weight); reading reports; adjudicating Learned lines; **214 SendMessage round trips** (112 out, 102 in) where every incoming progress ping is a full-context turn.

**The unit of cost is the orchestrator turn (~29k weighted at 240k ctx).** The CLI is only half of them.

### Also noted

Model mix was 60 sonnet, 6 opus, **no haiku** — despite the cheap tier existing in `policy.md`. That is a policy-compliance question, not a mechanism.

---

## 4. Original six-item list, corrected

The first list produced in the analysis session claimed 2–2.5×. Corrected, **as written it is ~1.5–1.6×**. Kept here so you don't re-propose the weak items.

| item | claimed | corrected | verdict |
|---|---|---|---|
| Cap subagent turns 31→15 | 26% | **8–12%** | overstated; must be *soft* |
| Hand off orchestrator at 150k | 22% | **10–14%** | direction right; overlaps F1 |
| Trim unused MCP servers | 16% | **4–8%** | **not fixable in-plugin** |
| Batch ledger CLI calls | 7% | **7–8%** | confirmed |
| Hard-cap review rounds at 2 | 5% | **1–3%** | **drop it** |
| Terser prose/thinking | 5% | **5–7%** | understated as output |

Why the corrections matter:

- **Turn cap:** cost per agent ≈ `P·n + g·n²/2` (P≈69k, g≈2.1k). Splitting a 44-turn agent into 3×15 saves ~25% of that agent but adds two re-dispatches × ~19 hub turns (F3), which eats most of the gain. Implementers here run dbt builds and Snowflake queries; a hard cap yields BLOCKED reports and re-dispatch. Use a **soft** rule: "over 25 turns → report `DONE_PARTIAL` with a handoff note".
- **MCP trim:** the 16% was the *whole* preamble, already at ×0.1 weight, and ~300 of those MCP tools are deferred *names* only — the schema cost is just the non-deferred ones. Do it in settings, measure by diffing turn-1 `cache_creation` with MCP off. Not an overseer change.
- **Round cap:** `policy.md`'s cap is a *deadlock* cap. Rounds ≥2 are 17% of dispatches; capping at 2 removes only rounds 3+. Trades review quality for ~0.2 Mtok/card. Don't.

These items compose multiplicatively, not additively: `0.90 × 0.87 × 0.94 × 0.98 × 0.94 ≈ 0.68`.

---

## 5. Recommended plan, ranked by tokens saved per card

Build cost is noted as information, not as a filter — the user's constraint is *token spend*, not implementation effort.

### #1 — Out-of-conversation stage driver: `overseer run-stage <card> <stage>`

**~6–8 Mtok/card on with-subagent cards (35–40%). Build ~700–1,000 lines.**

A Python dispatcher, launched from a single Bash call (daemon or blocking subprocess), runs each worker as a headless `claude -p` process in the card's worktree:

- `--model` per policy tier
- `--tools` / `--disallowedTools` to a minimal set
- `--strict-mcp-config --mcp-config <empty-or-snowflake-only>` to drop MCP schemas
- `--append-system-prompt` carrying the role charter
- `--output-format json` → real per-process usage

It composes prompts from the ledger (facts, calibration, prior findings, diff-to-file) and reads worker reports from files. **For review stages it runs the entire loop in one call**: N reviewers in parallel → verdict files → fixer if found wanting → re-review → cap → `log-review` each round → returns one line to the orchestrator, e.g. `impl-review: approved after 2 rounds; 3 Learned queued`.

What this buys, itemised:

| effect | saving |
|---|---|
| Hub turns per dispatch 19.5 → ~1–2 (a round-2 review card loses ~100 orchestrator turns) | ~3 Mtok |
| Worker preamble 53k+ → ~10–15k (no MCP, minimal tool schemas), ~20% off every worker turn | ~2.5 Mtok |
| Forks and fat prompts become structurally impossible (F2) | ~0.6 Mtok |
| `usage.jsonl` becomes accurate for free from the process's own JSON | fixes the 100× undercount |

**Decision required from the user before building:** headless workers need `--permission-mode acceptEdits` (or bypass) scoped to the worktree, and **they disappear from the interactive UI** — supervision moves to the dashboard (which already exists and could carry progress). This changes how a card is watched. It was explicitly flagged to the user and **not yet decided**.

Build risks to design for: process pool, stream parsing, timeout/unresponsive watchdog, failure modes, and a stage-loop state machine.

### #2 — Hard-block orchestrator work

**~1.5–2.5 Mtok/card averaged. Build ~50 lines `cli.py` + a `hooks.json` entry.**

A `PreToolUse` hook returning `decision: deny` with reason `"card <id> in flight — dispatch instead"` for `Read|Edit|Write|mcp__.*Snowflake.*|Bash(not cli.py/git)` **when the calling session is the one holding the claim / in-flight card**. Store the orchestrator session id on the card at pickup; the hook payload carries `session_id`. Workers under #1 are separate sessions and so are untouched.

Pair it with the two rule lines in `SKILL.md` (see anchors below) so the intent is stated as well as enforced.

> ⚠️ **Verify before enabling:** in Agent-tool (in-conversation) mode, confirm the `PreToolUse` payload distinguishes a subagent from the orchestrator session on this Claude Code build. If it does not, the hook will also block in-conversation workers.

### #3 — Attack the worker turn tail (the n² term)

**~1.5–2 Mtok/card.**

33/73 agents over 40 turns = 84% of subagent reads.

- **(a)** `templates/planner.md` must emit chunks sized to ≤ ~15 tool calls, and the driver runs each chunk as a **fresh process** — context resets for free, with no handoff prose to write or re-read. Trivial once #1 exists.
- **(b)** A `PreToolUse` hook that rewrites `Read` without a `limit` to `limit: 200` via `updatedInput`, for worker sessions only. 868 subagent Reads averaged 11k chars, and every one is re-read on every later turn of that agent. ~30 lines.

### #4 — Minimal-preamble agent definitions — *only if #1 is not built*

**~1.4 Mtok/card. Build: 4 markdown files.** #1 subsumes this entirely.

Plugin `agents/overseer-{implementer,reviewer,fixer,planner}.md` with a `tools:` allowlist and `model:`. **Evidence it works:** the single `Explore`-type agent in the data opened at **17k** versus 53k+ for everything else. Cannot strip CLAUDE.md or the base system prompt this way.

### #5 — Orchestrator handover at 150k

**~1.3 Mtok/card standalone, but mostly subsumed by #1+#2** — a thin orchestrator rarely reaches 150k. One line in `SKILL.md` plus the vigil threshold. Caveat: vigil's auto-`/clear` only works under tmux; otherwise it is a manual ask.

### #6 — `dispatch-prep` / `dispatch-close` verbs + path-only templates — *fallback if #1 is not built*

**~1.5 Mtok/card. Build ~150 lines + 4 template edits.**

- `cli.py dispatch-prep <card> --role X --stage Y [--round n]` → does `calibration` + fact selection + diff-to-file + prior-findings from the review log + template fill; writes `<state_root>/dispatch/<card>-<stage>-<round>-<role>.md`; **prints the path**. Orchestrator turns per dispatch ~5 → 1.
- `cli.py dispatch-close <card> --report <path>` → parses a structured header (Status/Commits/Tokens/Learned) and performs `log-progress` + `log-usage` + `log-review` + Learned queueing **in one call**. Replaces `review-loop.md` steps 2–3.
- Every template placeholder listed in §6 collapses to a single `{{bundle_path}}`.
- The fixer reads reviewer verdict files directly; the orchestrator never sees findings text, only `found wanting, 2 Critical 3 Important`.
- Also: `cli.py set-section <card> --section Plan --file <path>`, callable by planner/verifier, so plan and verification text never transit the orchestrator (today `SKILL.md` routes both through it and back out as Edit output).

### #7 — Kill polling

**~0.5 Mtok/card; irrelevant under #1. Build: 3 lines.**

`templates/implementer.md:20` ("report progress every ~`{{cadence_tokens}}` tokens") and `SKILL.md` Comms ("every peer message CC'd to you") both convert worker chatter into 240k-context orchestrator turns. In subagent mode the `Agent` result *is* the report. Progress goes to `log-progress` written by the worker (SQLite single-writer is fine) or to a file the unresponsive watchdog checks by mtime. **CC to the ledger, not to the orchestrator.**

A `SubagentStop` hook (~60 lines) can sum the agent's transcript usage → `log-usage` with real numbers and auto-run `dispatch-close`, at zero context cost since the hook emits nothing.

> ⚠️ **Verify before building:** confirm the `SubagentStop` payload carries the agent transcript path on this Claude Code build.

### #8 — Output and thinking

Output is 15% of weighted spend, thinking ~6.5%. Under #1 the driver may be able to set effort for headless workers via settings/env. **Uncertain — verify whether `claude -p` honours an effort setting on this build.** ~0.8 Mtok/card if it does, ~0.4 from prose rules otherwise.

### #9 — Round cap at 2

~0.2 Mtok/card. **Dropped** — not worth the quality trade.

### Recommended order

**#1 (with #3a folded in) → #2 → #3b → #8 if available.**

Expected outcome: with-subagent cards **19.4 → ~7–8 Mtok**, no-subagent cards **5.1 → ~3** (the work moves to cheap-context workers). **Roughly 2.5–3× overall** — and structurally enforced rather than dependent on wording a future session may not follow.

If the user declines the headless driver (#1), the fallback stack is **#2 → #6 → #4 → #3b → #7**, worth roughly 1.8–2×.

---

## 6. Exact file anchors

All paths relative to `plugins/overseer/` in this repo. (The analysis read the installed copy at `~/.claude/plugins/cache/pip-skills/overseer/0.23.0/`; the trees are identical.)

| What | Where |
|---|---|
| Orchestrator role paragraph — add the no-work / no-fork rules | `skills/orchestrate/SKILL.md:15–20` |
| Stage playbook (bootstrap prescribes 7+ separate CLI calls) | `skills/orchestrate/SKILL.md`, "Stage playbook" |
| "you write it via Edit on the card — prose exception" (planning) | `skills/orchestrate/SKILL.md`, planning bullet |
| Verification evidence routed through orchestrator | `skills/orchestrate/SKILL.md`, verification bullet |
| Comms / peer-cc rule | `skills/orchestrate/SKILL.md`, "## Comms" |
| Context stewardship — add the 150k number (it currently has none) | `skills/orchestrate/SKILL.md:152` |
| Review loop steps 2–3 → replace with `dispatch-close` | `skills/orchestrate/references/review-loop.md:10–15` |
| "reviewers read files, not pasted walls" — the rule F2 violates | `skills/orchestrate/references/review-loop.md:4` |
| Round cap (a deadlock cap — leave it alone) | `skills/orchestrate/references/review-loop.md:16–17` |
| Cadence pings to drop | `templates/implementer.md:20` |
| Inline placeholders → `{{bundle_path}}` | `templates/implementer.md:6–10`, `reviewer.md:6–14`, `fixer.md:8–11`, `planner.md:7–12` |
| `{{target_path}}` — already file-mediated by design | `templates/reviewer.md:6` |
| New CLI verbs register here | `scripts/cli.py` (2,064 lines; `cmd_*` + subparser pattern) |
| Hook registration | `hooks/hooks.json` (existing: claim-prompt, claim-stop, checklist-sync, dashboard-refresh, prepush-snapshot) |
| Cheap tier that was never used | `skills/orchestrate/policy.md` |
| Inaccurate budget log | `<state_root>/usage.jsonl`, written by `scripts/usage.py` |

---

## 7. Boundaries — not fixable from inside the plugin

State these rather than working around them with wishful mechanisms.

- **Per-turn context resend** is the API model. The API is stateless; every turn reships the transcript, and `cache_read` is just the 10% price for the unchanged part. Only turn count and per-turn context are levers. Everything in §5 is one of those two.
- **Main-session preamble (53k)** — system prompt, tool schemas, MCP listing, CLAUDE.md, skill index — is harness and user settings. The plugin can only *recommend* a settings profile (e.g. `--strict-mcp-config`) for orchestrator sessions. Headless workers under #1 escape it because they get their own flags.
- **In-conversation subagent inheritance:** the Agent tool inherits the parent's system prompt and CLAUDE.md. Agent definitions trim tool schemas (17k vs 53k evidence) but not the rest. Fork inheritance is avoidable only by not forking.
- **Compaction thresholds and thinking effort for in-conversation subagents** are not settable from a plugin (0 compactions observed at 400–741k).
- **Model price:** workers are already sonnet. The unused haiku tier is policy compliance, not a mechanism.

---

## 8. Open questions to resolve before building

1. **User decision, blocking #1:** permission mode for headless workers (`acceptEdits` scoped to the worktree vs bypass), and acceptance that workers leave the interactive UI.
2. **Verify:** does the `PreToolUse` payload distinguish an Agent-tool subagent from the orchestrator session on this Claude Code build? (Blocks #2 in in-conversation mode.)
3. **Verify:** does the `SubagentStop` payload carry the agent transcript path? (Blocks the #7 hook.)
4. **Verify:** does `claude -p` honour a thinking-effort setting? (Decides #8's size: ~0.8 vs ~0.4 Mtok/card.)

### Resolved 2026-09-16 — probed on Claude Code 2.1.273 (pip-skills session)

Probe: hook logging raw stdin for `PreToolUse` + `SubagentStop`, headless `claude -p` run that Reads a file itself then spawns an Agent-tool subagent to Read it.

- **Q2 — YES, but not by `session_id`.** The subagent's hook payload carries the **same `session_id`** as the orchestrator. It is distinguished by **`agent_id` + `agent_type`**, which are present only on subagent calls and absent on orchestrator calls. ⚠️ This corrects #2 as written: keying on `session_id` alone *would* block in-conversation workers. Deny rule must be `session_id == card.orchestrator_session AND "agent_id" not in payload`.
- **Q3 — YES.** `SubagentStop` carries `agent_transcript_path` (`…/<session>/subagents/agent-<agent_id>.jsonl`) plus `agent_id`/`agent_type`. The #7 hook is buildable.
- **Q4 — YES.** `claude -p --effort low|high` is honoured: the hook payload echoes `effort.level`, and the same prompt produced 12 vs 121 thinking tokens (137 vs 282 output). Every hook payload also carries `effort`. #8 is a driver feature (~0.8 Mtok/card), not prose rules.

Bonus measurement for #1 — headless turn-1 context for a trivial prompt (sonnet):

| flags | turn-1 ctx |
|---|---|
| none | 41.8k |
| `--strict-mcp-config` | 37.5k |
| + `--tools Read,Edit,Write,Bash,Grep,Glob` | 20.3k |
| + `--setting-sources ""` | **17.2k** |

`--bare` would go lower but **refuses OAuth** (API key / apiKeyHelper only) — unusable on the Max-plan account. `--setting-sources ""` also stops user plugins' hooks firing in workers (observed: agent-ui `SessionEnd` hook fired without it). Plan for ~17k, not 10–15k.

---

## 9. How to reproduce the measurements

Store: `~/.claude/chronicle/sessions.db` (SQLite, ~100 MB; **read-only** — it is chronicle's ingest target). Tables: `sessions`, `turns` (per-API-call tokens; cols `input_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `output_tokens`, `thinking_tokens`, `agent_id`, `agent_type`, `skill`, `model`, `cache_5m_tokens`, `cache_1h_tokens`), `tool_calls` (`tool_name`, `result_chars`), `file_edits`, `events`, `artifacts`.

Caveats: data ran to **2026-09-14** at time of audit (sync for newer); `turns.skill` is only populated while a skill is active, so skill-level attribution understates; `tool_calls.qualifier` is not populated for Bash, so command text must come from the transcripts under `~/.claude/projects/<slug>/*.jsonl`.

Orchestrator vs subagent split:

```sql
WITH os AS (SELECT DISTINCT session_id FROM turns WHERE skill LIKE 'overseer%')
SELECT CASE WHEN t.agent_id='' THEN 'orchestrator' ELSE 'subagent' END who,
       COUNT(*) turns,
       ROUND(SUM(t.cache_read_tokens)*1.0/COUNT(*)/1000) avg_ctx_k,
       ROUND((SUM(t.input_tokens)+SUM(t.cache_creation_tokens)*1.25
             +SUM(t.cache_read_tokens)*0.1+SUM(t.output_tokens)*5)/1e6,1) weighted_m
FROM turns t JOIN sessions s USING(session_id)
WHERE s.repo_root LIKE '%warehouse%' AND t.session_id IN (SELECT session_id FROM os)
GROUP BY 1;
```

Fork / fat-prompt detection (F2) — forks show high turn-1 `cache_read` with near-zero `cache_creation`; fat prompts show 140k+ `cache_creation` on turn 1:

```sql
WITH first AS (SELECT session_id, agent_id, MIN(ts) mn FROM turns WHERE agent_id<>'' GROUP BY 1,2)
SELECT t.agent_id, t.cache_read_tokens, t.cache_creation_tokens
FROM turns t JOIN first f
  ON f.session_id=t.session_id AND f.agent_id=t.agent_id AND f.mn=t.ts
WHERE t.cache_read_tokens > 150000 OR t.cache_creation_tokens > 100000;
```

Unique content placed in context (the 1.6 Mtok figure) requires parsing the transcript JSONL and summing `tool_result` text lengths plus assistant `text` blocks plus user content — chronicle's `result_chars` covers tool results only.

---

## 10. What not to do

- Do not shrink `SKILL.md`, the references, the templates, or CLI output. All measured lean; zero available win.
- Do not optimise subagent report size (already 72 tokens median).
- Do not chase a caching bug (39 cold turns in 9,606; cache is healthy).
- Do not cap review rounds for cost reasons.
- Do not treat MCP trimming as an overseer change — it is a settings change, and measure it before claiming a number.
