# Blast Radius

## Concern
What this change breaks elsewhere. Code that still relies on something the diff removed, call
sites that no longer match a changed signature, callers whose assumptions changed under them,
tests that pin the old behaviour, and changed behaviour no test reaches. Detection comes from
concordance's index; this reviewer judges what the hits mean.

## When to seat
Diffs that remove code, parameters, guards or decorators; that change a signature; or that
touch symbols with more than one caller. Leave it off for docs-only, config-only or brand-new
isolated files. Requires the concordance plugin: locate its CLI with Glob for
`plugins/cache/*/concordance/*/scripts/cli.py` under `$CLAUDE_CONFIG_DIR` (default `~/.claude`),
or `plugins/concordance/scripts/cli.py` inside the pip-skills repo. If neither exists, say the
lens cannot be seated and stop.

## Techniques
Change-impact and cross-referencing, driven by concordance's review procedure: invoke the
`concordance:review-procedure` skill (or read `<concordance plugin>/skills/review-procedure/SKILL.md`
if the Skill tool is unavailable) and follow every step; each step ends in a finding or "clean".

## What to look for
| ID | category | rule | default severity | what to scan for |
|----|----------|------|------------------|------------------|
| BR-001 | correctness | Removed contract still referenced | error | Removed contract rows whose referencing code still relies on the removed symbol, parameter, guard or decorator |
| BR-002 | correctness | Signature drift at a call site | error | `[BR-002]` verdicts (decided by the CLI), and undecided drift rows that do not fit the new signature |
| BR-003 | correctness | Caller assumption broken by a behaviour change | warning | Callers of behaviour-changed symbols that depend on the old result, side effect or exception |
| BR-004 | tests | Guarding test asserts the old behaviour | warning | Guarding tests whose assertions encode the behaviour the diff changed |
| BR-005 | tests | Behaviour change with no guarding test | info | `[BR-005]` verdicts (decided by the CLI) |

## Severity
`error` — a call or reference that will fail or misbehave at runtime.
`warning` — likely regression or a test that will fail or mislead.
`info` — coverage gap worth recording; never blocking.

## Voice
Neutral, professional, direct. Name the removed or changed contract, the dependent location
(path:line) and why it relies on the old behaviour. No persona flavour.

## Allowed exceptions
- `BR-005` is already `info`, so it never blocks.
- Under `pragmatic` strictness, `BR-003` may be downgraded to `info` when the only callers are
  tests.
