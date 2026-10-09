---
description: Show this session's vital signs (census) — lean by default; pass detailed or playful for the other styles.
argument-hint: "[lean|detailed|playful]"
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" -- "$ARGUMENTS" 2>&1`

Reply with the reading above **verbatim** inside one ```text fence — no
preamble, no commentary, no reformatting (it is pre-sized for a phone; re-wrapping
breaks the gauges). Nothing else in the reply.

If it is empty or shows a shell error, run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" -- "$ARGUMENTS"` yourself (the plugin
root is this command file's `../`) and print the result the same way. If it says
"no census reading yet", add one line after the fence: census is fed by its
status-line hook or by the census-mod mod, so a brand-new or headless session has none
yet; if it never appears, neither is installed (see the census README).
