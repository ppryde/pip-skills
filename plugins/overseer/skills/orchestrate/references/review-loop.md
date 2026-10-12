# Review loop: disputes, deadlock, L panels

The steps themselves (panel, fixer, re-review, round cap, no pre-rated
severities) are in `SKILL.md`; this is the part an S/M card rarely reaches.

- **L round 1** is 3 reviewers (one strong tier, lenses per `policy.md`), then 2
  from round 2 with the strong reviewer retained.
- **A maintained dispute.** Round n+1 reviewers must WITHDRAW or MAINTAIN (with
  new evidence) each DISPUTED finding. One still maintained after that
  re-review is yours: open only that verdict file and the fix report, decide,
  and record the ruling in `## Decisions`. Do not open the other findings.
- **Deadlock.** When the round cap hits with critical/important findings still
  open, there is no further fixer: `block <id> --reason "user: review deadlock
  — <summary>"` naming the findings that remain and the disputed ruling.
- `dispatch-prep` for a fixer lists this round's verdict files and writes the
  round n+1 bundles with every earlier verdict and fix report; you do not paste
  them.
