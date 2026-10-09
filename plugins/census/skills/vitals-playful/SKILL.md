---
name: vitals-playful
description: Show this session's vital signs as the Witchfinder's reading — the breath (context), the mind (model), the sanctum (repo), the vigil (time) and the gates (rate limits), closed by a verdict. Use when the user runs /census:vitals-playful.
disable-model-invocation: true
allowed-tools: Bash(python3:*)
---

# /census:vitals-playful

The same vital signs, read aloud by the Witchfinder. The closing verdict is real: it turns *wanting* at 80% context or 90% of a rate limit, and venial at 50% / 70% or 20+ dirty files.

## Reading

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --style playful --session "${CLAUDE_SESSION_ID}" 2>&1`

## What to do

Reply with the reading above **verbatim** inside one ```text fence — no
preamble, no commentary, no reformatting (it is pre-sized for a phone screen;
re-wrapping breaks the gauges). Nothing else in the reply.

If the Reading section is empty or shows a shell error (the plugin root was not
substituted), run it yourself from this skill's base directory and print the
result the same way:

```bash
python3 <skill base directory>/../../scripts/vitals.py --style playful
```

The script is read-only and never fails loudly: a missing source (no census
entry, not a git repo) just leaves its lines out. If it prints
"no census reading yet", add one line after the fence: census is fed by its
status-line hook or by the census-mod mod, so a brand-new or headless session has none
yet; if it never appears, neither is installed (see the census README).
