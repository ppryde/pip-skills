---
description: Show this session's vital signs (census) — lean by default; name detailed or playful for the other styles.
argument-hint: "[lean|detailed|playful]"
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" 2>&1`

If the user named no style, reply with the reading above **verbatim** inside one
```text fence — no preamble, no commentary, no reformatting (it is pre-sized for a
phone; re-wrapping breaks the gauges). Nothing else in the reply.

If the user named a style (their words after the command), that reading is the wrong
one: choose the style from this fixed list only, never pasting the user's own text into
a command — `lean` (also: brief), `detailed` (also: full, trend), `playful` (also: drama,
witchfinder) — and run it yourself with the Bash tool:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" <style>
```

with `<style>` replaced by exactly one of `lean`, `detailed` or `playful`. Then print
that result the same way (one ```text fence, verbatim). A name that matches none of
them means lean, so the reading above stands.

If the reading is empty or shows a shell error (the plugin root was not substituted),
run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py"` yourself (the plugin root is
this command file's `../`) and print the result the same way. If it says "no census
reading yet", add one line after the fence: census is fed by its status-line hook or by
the census-mod mod, so a brand-new or headless session has none yet; if it never appears,
neither is installed (see the census README).
