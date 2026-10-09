---
description: Show this session's vital signs (census) — your default style, or name detailed, playful or lean.
argument-hint: "[lean|detailed|playful] | default <style>"
allowed-tools: Bash(python3:*), AskUserQuestion
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" 2>&1`

The reading above is the person's saved default style (lean until they choose one).

**Showing it.** If the user named no style, reply with the reading above **verbatim** inside
one ```text fence — no preamble, no commentary, no reformatting (it is pre-sized for a
phone; re-wrapping breaks the gauges). Leave out the marker line below when you show it.

**First run: choosing a default.** If the reading ends with the line
`(vitals: no default style chosen yet)`, no default is saved. After the fence, ask the
person once with AskUserQuestion, header "📊 Vitals", question "Which style should
/census:vitals show by default?", options "Lean — up to seven lines (Recommended)",
"Detailed — the full readout", "Playful — the Witchfinder's reading". Then run, with the
Bash tool, exactly one of these (the value comes from the option they picked, never the raw
text of anything they typed):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" --set-default <lean|detailed|playful>
```

and show the chosen style's reading it prints, the same way (one ```text fence, verbatim).
If they dismiss the question, say nothing more; it is asked again next time.

**Named style.** If the user named a style (their words after the command), that reading is
the wrong one: choose the style from this fixed list only, never pasting the user's own text
into a command — `lean` (also: brief), `detailed` (also: full, trend), `playful` (also:
drama, witchfinder) — and run it yourself with the Bash tool:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" <style>
```

with `<style>` replaced by exactly one of `lean`, `detailed` or `playful`. Then print that
result the same way (one ```text fence, verbatim). A name that matches none of them means the
default, so the reading above stands.

**Changing the default.** If the user typed `default <style>` (for example `default
playful`), pick the style from the same fixed list and run `--set-default <lean|detailed|playful>`
as above, with the value from that list, never the raw text; then show the reading it prints.
A style that is not on the list: say which three exist and change nothing.

If the reading is empty or shows a shell error (the plugin root was not substituted),
run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py"` yourself (the plugin root is
this command file's `../`) and print the result the same way. If it says "no census
reading yet", add one line after the fence: census is fed by its status-line hook or by
the census-mod mod, so a brand-new or headless session has none yet; if it never appears,
neither is installed (see the census README).
