---
name: lean
description: Show this session's vital signs in six lean lines — context gauge, model, cost, branch/PR, rate-limit windows, time and tool count. Phone-sized. Use when the user runs /vitals:lean or asks for a quick status check.
disable-model-invocation: true
allowed-tools: Bash(python3:*)
---

# /vitals:lean

Six lines, emoji gauges, nothing wasted. The one to glance at from a phone.

## Reading

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style compact --session "${CLAUDE_SESSION_ID}" 2>&1`

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
entry, not a git repo, no `gh`) just leaves its lines out. If it prints
"no census reading yet", add one line after the fence: census is fed by the
status line, so a brand-new or headless session has none yet; if it never
appears, census's status-line hook is not installed (see the census README).
