# Telemetry (automatic)

The `SubagentStop` report hook (`hooks/report.sh` → `cli.py report-hook`) runs
when any `overseer:overseer-*` agent finishes. It:

1. parses the agent's one-line reply (card, stage, round/slot/chunk come from
   the dispatch file path);
2. totals real usage from the agent's own transcript (`agent_transcript_path`),
   counting each message once;
3. appends to `usage.jsonl`: `tokens` (raw total) plus `input`, `cache_read`,
   `cache_creation`, `output`, `budget_tokens`, `reply_words`, `overrun`,
   `agent_id`, `source: "hook"`;
4. writes the card: reviewer → `## Review log` entry; implementer/fixer →
   `## Progress log` + budget; planner → `## Plan`; verifier → `## Verification`;
5. queues `Learned:` lines as pending facts.

**Budget:** only implementer and fixer spend feeds `budget_actual` (so the S/M/L
bands and the 2× tripwire keep their meaning), counted as
`input + cache_creation + output`. Cache reads are the re-read amplification and
are excluded from the budget; the raw figure stays in `usage.jsonl`.

**Never blocks.** A reply that does not parse is recorded as `unparsed` with the
raw line; one over 25 words as `overrun`. `usage` prints a warning for both.
There is no retry — the cap is stated in the agent definition instead.

`log-usage` remains for manual entries (e.g. an orchestrator overhead figure at
card completion) but is not part of the dispatch loop.
