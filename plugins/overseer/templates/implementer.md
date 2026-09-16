# Implementation bundle — {{card_id}} chunk {{chunk_no}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Your chunk: chunk {{chunk_no}} of the card's plan. Read it with `{{cli}} show {{card_id}} --json` (field `sections["## Plan"]`). Do that chunk only.
- Worktree (work ONLY here): {{worktree}}
- Gate commands: {{gate_commands}}
- Binding constraints: {{constraints}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}

## Output
Write your report to `{{reply_path}}` in the format your agent definition gives, then reply with the `overseer-report` block it specifies.
