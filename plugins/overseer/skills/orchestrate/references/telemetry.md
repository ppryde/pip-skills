# Telemetry (automatic)

The `SubagentStop` report hook (`hooks/report.sh` → `cli.py report-hook`) runs
when any `overseer:overseer-*` agent finishes. It:

1. extracts the LAST `overseer-report` fenced JSON block from the agent's
   final message and parses it against that role's schema (`scripts/schemas.py`
   — card, stage, round/slot/chunk, status, counts and `detail` all travel as
   typed fields, not a parsed line);
2. totals real usage from the agent's own transcript (`agent_transcript_path`),
   counting each message once;
3. appends to `usage.jsonl`: `tokens` (raw total) plus `input`, `cache_read`,
   `cache_creation`, `output`, `budget_tokens`, `agent_id`, `source: "hook"`;
4. writes the card: reviewer → `## Review log` entry; implementer/fixer →
   `## Progress log` + budget; planner → `## Plan`; verifier → `## Verification`;
5. queues the block's `learned` array as pending facts.

**Budget:** only implementer and fixer spend feeds `budget_actual` (so the S/M/L
bands and the 2× tripwire keep their meaning), counted as
`input + cache_creation + output`. Cache reads are the re-read amplification and
are excluded from the budget; the raw figure stays in `usage.jsonl`.

**Bounded retry, not silent record-only.** A missing block, invalid JSON, or a
block that fails its role's schema gets exactly ONE bounce: the hook prints
`{"decision": "block", "reason": "<every problem found> ... <the expected
shape>"}`, guarded by Claude Code's own `stop_hook_active` so this can never
loop — the second attempt either parses, or is recorded as `unparsed` (with
the full error list) and the hook falls silent. `usage` prints a warning for
any unparsed reports.

`log-usage` remains for manual entries (e.g. an orchestrator overhead figure at
card completion) but is not part of the dispatch loop.
