---
name: vitals-detailed
description: Show this session's vital signs in full — context headroom and cache warmth, cost and token totals, git sync and lines changed, tool breakdown, and each rate-limit window with its reset time and a pace forecast. Use when the user runs /census-mod:vitals-detailed or wants the full session analytics.
disable-model-invocation: true
allowed-tools: Bash(sh:*), Bash(python3:*), Bash(python:*), Bash(py:*)
---

# /census-mod:vitals-detailed

Sectioned readout with the figures behind the gauges. The rate-limit **pace** line projects usage at reset from the rate so far this window (shown once 5% of the window has elapsed).

## Reading

!`sh "${CLAUDE_PLUGIN_ROOT}/bin/pyrun.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style detailed --session "${CLAUDE_SESSION_ID}" 2>&1`

Launcher: `bin/pyrun.sh` runs the script with the first of `python3`, `python` and `py -3` that works, and says nothing about the others; run every command below through it.

## What to do

Reply with the reading above **verbatim** inside one ```text fence — no
preamble, no commentary, no reformatting (it is pre-sized for a phone screen;
re-wrapping breaks the gauges). Nothing else in the reply.

If the Reading section is empty or shows a shell error (the plugin root was not
substituted), run it yourself from this skill's base directory and print the
result the same way:

```bash
sh <skill base directory>/../../bin/pyrun.sh <skill base directory>/../../scripts/vitals.py --style detailed
```

The script is read-only and never fails loudly: a missing source (no census
entry, not a git repo) just leaves its lines out. If it prints
"no census reading yet", add one line after the fence: census-mod records a session
from inside Claude Code, so a brand-new or headless session has none yet; if it never
appears, census-mod may be recording into a shadow store (`CENSUS_MOD_STORE`), which vitals does not read,
or is not recording at all (run /census-setup).
