# Stage gates (hard)

Read on a `GATE:` refusal (exit 3) from `set-stage`, `dispatch-prep` or `bootstrap`.

The CLI refuses a forward move when its evidence is missing — exit 3, one
`GATE: <rule> - <what to run>` line per problem. Run what the line says; do not
route around it.
- `-> implementation`: a real `## Plan` and a clean plan-review round (skipped
  only for an S `--brief` card).
- `-> verification`: a clean impl-review round, every size.
- `-> awaiting-merge`: a verifier `PASS` the report hook recorded (prose in
  `## Verification` is not evidence).
- `dispatch-prep`: reviewer round n needs a fixer report for round n-1 and
  n <= the cap; a fixer at the cap is refused (block the card instead).
- A reviewer or verifier that was dispatched but never reported blocks its
  gate: an absent verdict is not an approval.
Evidence is written by the report hook; you never record it. Escape, only when
the user says to proceed anyway: `--force-gate "user: <why>"` on `set-stage` or
`dispatch-prep` (recorded in `## Decisions`, shown on the card); an empty reason
is refused. Cards created before the gates shipped only warn. Repo config
`"gates": "warn"|"off"` or `OVERSEER_GATES=warn|off` softens them.

