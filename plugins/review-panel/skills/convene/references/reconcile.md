# Reconcile, strictness, decisions (convene Step 5)

Write the reviewers' payloads (a JSON list) to a temp file and run
`cli.py parse --findings <file>`. Critic and arbiter verdicts are keyed by the
fingerprints it prints. No findings file is ever trusted: every command
recomputes fingerprints and ignores any `verdict`, `reason`,
`severity_before`, `fingerprint` or `_source` in its input, so the same
payloads always give the same fingerprints, and a verdict reaches a finding
only through `--verdicts`, a file you build from the critic and arbiter
output (for dual-tiebreaker, plus the `verdicts` that `match` prints for the
findings both passes agreed on). Then run
`cli.py reconcile --findings <the same payloads file, or the match output> --strictness <reviewer>=<level> ...`
(one flag per resolved reviewer; add `--verdicts <file>` and
`--require-verdicts` when the strategy produced critic/arbiter verdicts, and
`--decisions .review-panel/decisions.yml` if that file exists). Code does the
rest in a fixed order: verdicts (`refuted` dropped from the findings and
listed in the report's Refuted section, `weakened` lowered one step, a
missing verdict kept and noted), then strictness with each reviewer's
`allowed-exceptions` block, then decisions (keyed by the finding's
`fingerprint`; an old per-run-id key still matches, with a migrate note). The
strictness and exception maps are keyed by the bare `reviewer` name. The
output holds `findings`, `dropped`, `notes` and `counts`; mention any notes.
