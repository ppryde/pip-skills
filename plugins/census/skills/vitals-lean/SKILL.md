---
name: vitals-lean
description: Show this session's vital signs in three lean lines — context gauge, model and cost; branch, PR and uncommitted work; rate-limit windows (a fourth line only when the reading may not be live). Phone-sized. Use when the user runs /census:vitals-lean or asks for a quick status check.
disable-model-invocation: true
allowed-tools: Bash(python3:*), Bash(python:*), Bash(py:*)
---

# /census:vitals-lean

Three lines, emoji gauges, nothing wasted. The one to glance at from a phone.

## Reading

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style compact --session "${CLAUDE_SESSION_ID}" 2>&1 || python "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style compact --session "${CLAUDE_SESSION_ID}" 2>&1 || py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style compact --session "${CLAUDE_SESSION_ID}" 2>&1`

Launcher: wherever this file says `python3`, use the first of `python3`, `python` and `py -3` that exists on this machine.

## What to do

Reply with the reading above **verbatim** inside one ```text fence — no
preamble, no commentary, no reformatting (it is pre-sized for a phone screen;
re-wrapping breaks the gauges). Nothing else in the reply.

If the Reading section is empty or shows a shell error (the plugin root was not
substituted), run it yourself from this skill's base directory and print the
result the same way:

```bash
python3 <skill base directory>/../../scripts/vitals.py --style compact
```

The script is read-only and never fails loudly: a missing source (no census
entry, not a git repo) just leaves its lines out. If it prints
"no census reading yet", add one line after the fence: census is fed by its
status-line hook or by the census-mod mod, so a brand-new or headless session has none
yet; if it never appears, either neither is installed or census-mod is recording into a shadow
store (`CENSUS_MOD_STORE`), which vitals does not read (see the census README).
