# review-panel

Composable code review. A review is built from two axes bundled into a
named **profile**:

- **Reviewers** — *what* to examine (a lens: concern + voice).
- **Strategies** — *how* to orchestrate (committee, blind, informed,
  adversarial, dual-tiebreaker).

Reviewers come from `skills/reviewers/*.md` or a review-clone persona
(`clone:<alias>`). Configure via `.review-panel/config.yml`. Run with
`/review-panel [profile]`.

## Seats are pip-agents personas

A reviewer's seat is a [`pip-agents`](../pip-agents/README.md) persona (declared as a dependency): the reviewer file's
`lens:` frontmatter picks it (`rules` is the default, so `general` and every `clone:<alias>` run as
`pip-agents:reviewer-rules`; `security` runs as `pip-agents:reviewer-security`), and the critic and arbiter are
`pip-agents:validator`. `cli.py brief` writes each seat's brief, a rules seat is handed a generated rulebook of at most
30 rules, `cli.py ingest` validates the seat's `pip-agents-result` block and adapts it to the finding payload, and
`cli.py claims` builds the validator's claim files. The validator and contract are vendored in
`vendor/pip-agents/` (a skill cannot reach a dependency plugin's files); `python3 tools/sync_contract.py` refreshes the
copy and `tests/agents/test_sync_contract.py` fails on drift.

Adding a catalogue reviewer: drop `skills/reviewers/<name>.md` (sections as in `_template.md`); add
`---\nlens: <rules|security|scope|correctness>\n---` at the top for a lens other than `rules`. `security` ships beside
`general`.
