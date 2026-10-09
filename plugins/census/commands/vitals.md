---
description: Show this session's vital signs (census) — your default style, or name lean or detailed.
argument-hint: "[lean|detailed] | default <style>"
allowed-tools: Bash(python3:*), Bash(python:*), Bash(py:*), AskUserQuestion
---

Use whichever Python launcher works on this machine for every command below: `python3`, else `python`, else `py -3` (Windows).

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" 2>&1 || python "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" 2>&1 || py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" 2>&1`

Launcher: wherever this file says `python3`, use the first of `python3`, `python` and `py -3` that exists on this machine.

The reading above is the person's saved default style (lean until they choose one).

**Showing it.** If the user named no style, reply with the reading above **verbatim** inside
one ```text fence — no preamble, no commentary, no reformatting (it is pre-sized for a
phone; re-wrapping breaks the gauges). Leave out the marker line below when you show it.

**First run: choosing a default.** Only for a bare run (the user typed no style and no `default <style>`; an
explicit `default <style>` below always wins, so do not ask the first-run question then). If the reading ends with the line
`(vitals: no default style chosen yet)`, no default is saved. After the fence, ask the
person once with AskUserQuestion, header "📊 Vitals", question "Which style should
/census:vitals show by default?", options "Lean — three lines (Recommended)",
"Detailed — the full readout". Then run, with the
Bash tool, exactly one of these (the value comes from the option they picked, never the raw
text of anything they typed):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" --set-default <lean|detailed>
```

and show the chosen style's reading it prints, the same way (one ```text fence, verbatim).
If they dismiss the question, say nothing more; it is asked again next time.

**Named style.** If the user named a style (their words after the command), that reading is
the wrong one: choose the style from this fixed list only, never pasting the user's own text
into a command — `lean` (also: brief) or `detailed` (also: full, trend) — and run it yourself
with the Bash tool:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" --session "${CLAUDE_SESSION_ID}" <style>
```

with `<style>` replaced by exactly one of `lean` or `detailed`. Then print that
result the same way (one ```text fence, verbatim). A name that matches none of them means the
default, so the reading above stands.

**Changing the default.** If the user typed `default <style>` (for example `default
detailed`), that explicit choice wins: do not ask the first-run question, even on a fresh install
where the reading above ends with the marker. Pick the style from the same fixed list and run `--set-default <lean|detailed>`
as above, with the value from that list, never the raw text; then show the reading it prints.
A style that is not on the list: say which two exist and change nothing.

If the reading is empty or shows a shell error (the plugin root was not substituted),
run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py"` yourself (the plugin root is
this command file's `../`) and print the result the same way. If it says "no census
reading yet", add one line after the fence: census is fed by its status-line hook or by
the census-mod mod, so a brand-new or headless session has none yet; if it never appears,
either neither is installed or census-mod is recording into a shadow store (`CENSUS_MOD_STORE`), which vitals
does not read (see the census README).
