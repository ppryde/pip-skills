# Adversarial review loop (both review stages)

Applies to **plan-review** (over the card's plan) and **impl-review** (over the
diff). `dispatch-prep` snapshots the plan or writes the diff for you; reviewers
read files, never pasted walls.

1. **Round n reviewers.** Panel per `policy.md` (count, tiers, lenses; L round 1
   = 3 then 2 with the strong reviewer retained). For each slot A, B, C:
   `dispatch-prep <id> --stage <stage> --role reviewer --slot <X> --round <n>
   --lens <lens>`, then dispatch every `overseer:overseer-reviewer` **in one
   turn**. Reviewers are independent: none sees another's current-round verdict.
2. **Read the lines.** All `approved` → stage passes. Any `found wanting` with
   C or I > 0 → step 3. Minors never force a round.
3. **One fixer.** `dispatch-prep <id> --stage <stage> --role fixer --round <n>`
   (it lists this round's verdict files) → dispatch `overseer:overseer-fixer`,
   the same implementer lineage. You do not read the findings.
4. **Re-review.** Round n+1 bundles list every earlier verdict and fix report;
   reviewers must WITHDRAW or MAINTAIN (with new evidence) each DISPUTED finding.
   A dispute maintained after that re-review is yours: open only that verdict
   file and fix report, decide, and record the ruling in `## Decisions`.
5. **Round cap per policy.** Cap hit → `block <id> --reason "user: review
   deadlock — <summary>"`.
6. The report hook logs every verdict under the round's header in `## Review
   log` — you never call `log-review` in this loop.
7. Never tell a reviewer what NOT to flag. Never pre-rate severities.
