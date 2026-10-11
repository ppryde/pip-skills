# What to report

Give the numbers as measured, and record predictions before measuring so they can be shown wrong — a prediction that was off is information about where the cost really was.

Take the wall-clock row from `time` around the pytest run, not from the script, which sums per-test time.

```
                    before     after
wall-clock          506.0s   →  220.1s   (−56.5%)
integration         347.3s   →  198.7s   (−42.8%)
unit                141.8s   →   14.4s   (−89.9%)
tests removed / status-changed:  0 / 0
scaling of the fixed path:  4.0x → 2.0x per doubling
tests skipped:  12, all by an always-true guard (see below)
adversarial review:  subagent, 3 findings, 2 fixed / 1 declined (see below)
paid for with:  330 setups no longer drive the real seed path; one guard still does
```

The last three lines are the ones a reader cannot reconstruct from the first three, and they are the ones that distinguish a real fix from a flattering number. Report them even when they are unremarkable — "scaling unchanged, nothing quadratic here", "no skips" and "review found nothing" are all useful, and their absence is what lets a constant-factor win pass as a fix. A report with no review line reads as a report that skipped Phase 6.

Report the skips whether or not the user asked about coverage. Someone believes those tests are running.
