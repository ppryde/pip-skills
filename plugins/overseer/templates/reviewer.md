# Review bundle — {{card_id}} {{stage}} round {{round_no}}, reviewer {{slot}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Review target: {{target_path}}
- Your lens (priority, not a blinker): {{lens}}
- Binding constraints: {{constraints}}
- Prior rounds' verdicts and fix reports — read them; answer every DISPUTED finding (withdraw, or maintain with new evidence); never re-raise an adjudicated finding verbatim:
{{prior_findings}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}
- Worktree (do not modify): {{worktree}}
- Ledger CLI (read-only verbs, e.g. `show {{card_id}} --json`): {{cli}}

## Output
Write your verdict to `{{reply_path}}` in the format your agent definition gives, then reply with the `overseer-report` block it specifies, its `detail` field pointing at that path.
