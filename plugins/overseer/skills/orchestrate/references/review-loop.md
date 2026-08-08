# Adversarial review loop (both review stages)

Applies to **plan-review** (over the plan text) and **impl-review** (over the
diff — write the diff to a file first; reviewers read files, not pasted walls).

1. Panel per policy.md (count, tiers, lenses; L round 1 = 3 then 2 with the
   strong reviewer retained). Dispatch in parallel with template `reviewer.md`;
   reviewers are independent — never share one reviewer's verdict with another
   before both have submitted.
2. Unanimous "approved" → stage passes. Otherwise ONE fix dispatch (template
   `fixer.md`) carrying ALL Critical/Important findings, to the same
   implementer; require covering-test evidence; then re-review.
3. `log-review <id> --stage <stage> --reviewers <n> --verdict "<one-liner>"`
   every round. Dedup findings against the card's review log — a rejected
   finding re-raised verbatim does not force a round.
4. Round cap per policy. Cap hit → `block <id> --reason "user: review
   deadlock — <summary>"` and summarise the dispute on the card.
5. Never tell a reviewer what NOT to flag. Never pre-rate severities.
