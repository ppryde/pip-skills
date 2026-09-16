# Verification bundle — {{card_id}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Plan: `{{cli}} show {{card_id}} --json` (field `sections["## Plan"]`)
- Worktree: {{worktree}}
- Gate commands: {{gate_commands}}
- Binding constraints: {{constraints}}

## Output
Write your evidence to `{{reply_path}}` in the format your agent definition gives, then reply with the single line it specifies. The ledger copies the file into the card's Verification section.
