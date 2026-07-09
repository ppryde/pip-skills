# Fix Dispatch — {{card_id}} {{stage}} round {{round_no}}

You are fixing review findings. You are (or continue) the implementer of
this work; your context of it survives.

## Inputs
- Complete findings list (fix ALL Critical and Important; Minors only where
  trivial alongside): {{findings}}
- Worktree: {{worktree}}
- Test/gate commands: {{gate_commands}}

## Rules
- One dispatch fixes the whole round's findings — do not cherry-pick.
- Every fix carries covering-test evidence: name the test, run it, show the
  result. A fix without a covering test is not done.
- If you believe a finding is wrong, say so with evidence instead of
  "fixing" it badly — the orchestrator adjudicates.
- Commit as `fix({{scope}}): <what>` after gates pass.

## Report (final message, under 12 lines)
- Status, commit SHA(s), per-finding disposition (fixed / disputed with
  reason), test evidence, tokens spent.
