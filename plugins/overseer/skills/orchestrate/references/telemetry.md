# Telemetry (self-monitoring)

After EVERY dispatch returns, log its cost — the harness reports each subagent's
token usage with its result:
`log-usage <card> --role planner|worker|reviewer|fixer --stage <stage> --tier
<tier> --tokens <n> [--round <r>]`. At card completion, log your own coordination
overhead as role `orchestrator` (best estimate of tokens spent on this card
outside dispatches). `usage` / `usage --card <id>` summarises by role and card.
This data exists so a future review can find where this skill itself burns
tokens — cheap honest entries beat missing ones.

Telemetry is measurement only — card budgets and the 2× tripwire are fed solely
by log-progress; reviewer/planner/orchestrator spend lands in usage.jsonl, not in
budget.actual.
