---
name: vitals-detailed
description: Show this session's vital signs in full — context headroom and cache warmth, cost and token totals, git sync and lines changed, tool breakdown, and each rate-limit window with its reset time and a pace forecast. Use when the user runs /census:vitals-detailed or wants the full session analytics.
disable-model-invocation: true
allowed-tools: Bash(python3:*), Bash(python:*), Bash(py:*)
---

Use whichever Python launcher works on this machine for every command below: `python3`, else `python`, else `py -3` (Windows).

# /census:vitals-detailed

Sectioned readout with the figures behind the gauges. The rate-limit **pace** line projects usage at reset from the rate so far this window (shown once 5% of the window has elapsed).

## Reading

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style detailed --session "${CLAUDE_SESSION_ID}" 2>&1 || python "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style detailed --session "${CLAUDE_SESSION_ID}" 2>&1 || py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style detailed --session "${CLAUDE_SESSION_ID}" 2>&1`

Launcher: wherever this file says `python3`, use the first of `python3`, `python` and `py -3` that exists on this machine.

## What to do

Reply with the reading above **verbatim** inside one ```text fence — no
preamble, no commentary, no reformatting (it is pre-sized for a phone screen;
re-wrapping breaks the gauges). Nothing else in the reply.

If the Reading section is empty or shows a shell error (the plugin root was not
substituted), run it yourself from this skill's base directory and print the
result the same way:

```bash
python3 <skill base directory>/../../scripts/vitals.py --style detailed
```

The script is read-only and never fails loudly: a missing source (no census
entry, not a git repo) just leaves its lines out. If it prints
"no census reading yet", add one line after the fence: census is fed by its
status-line hook or by the census-mod mod, so a brand-new or headless session has none
yet; if it never appears, either neither is installed or census-mod is recording into a shadow
store (`CENSUS_MOD_STORE`), which vitals does not read (see the census README).
