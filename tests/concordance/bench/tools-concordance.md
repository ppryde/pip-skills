## Tools

Read, Grep, Glob, `git -C {CASE} ...`, PLUS concordance, an index of this exact repo state.
Follow its review procedure exactly; every step is mandatory and ends in a finding or "clean":

    {CONCORDANCE_SKILL}

Run its CLI from inside the case repo, always with the PR's base:

    cd {CASE} && python {CLI} review-context --base HEAD~1

When the report says `+N more` or `omitted for budget`, fetch the rest with the matching
command (`removed`, `sig-drift`, `touched`, `literals`), each with `--base HEAD~1` and a larger
`--budget`. Only a `[BR-002]` verdict is proven (the call target was resolved exactly); an
undecided signature-drift row is a question for you, not a clean bill.

In your TOOL LOG, list each concordance command once with a one-word verdict
(useful / noise / wrong), and fill in the procedure's step log.
