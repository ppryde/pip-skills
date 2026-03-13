# pip-skills

A personal collection of Claude Code skills for serious engineering work — from PR review to architectural auditing. Built for real workflows, shared because they might help yours.

## What's in here

Two plugins, each with a distinct purpose:

| Plugin | Purpose |
|--------|---------|
| [**Puritan**](plugins/puritan/) | Architectural doctrine enforcement — plan patterns, audit code, author rules |
| [**Tribunal**](plugins/tribunal/) | PR review workflow — fetch, triage, validate, action, and resolve GitHub PR comments 

## Installing

Both plugins are available directly through the Claude marketplace. Choose righteousness through GUI:

### Quick Path to Virtue (Recommended)

1. **Open Claude.ai** in thy blessed browser
2. **Settings** → **Plugins** (or use the plugins panel)
3. **Browse marketplace** 
4. Search for **Puritan** or **Tribunal**
5. **Install** the skill(s) that speak to thy soul
6. Return to chat, and lo—they shall be available

### Alternative: Claude Code CLI Installation

Both plugins are also installable via the Claude Code plugin system. From the Claude Code CLI:

```
/install-github-app ppryde/pip-skills
```

Or install individually:

```
# Puritan only
/install-github-app ppryde/pip-skills/plugins/puritan

# Tribunal only
/install-github-app ppryde/pip-skills/plugins/tribunal
```

### The Skills, Once Installed

After installing, the skills are available as slash commands:

```
/puritan:covenant     — architecture planning and pattern selection
/puritan:inquisition  — audit codebase against configured doctrines
/puritan:scriptorium  — author new architecture doctrines

/tribunal:reckoning   — triage and action GitHub PR review comments
```


## Philosophy

These skills are built around two ideas:

**1. Architecture should be codified, not tribal knowledge.**
Architectural decisions that live only in people's heads — or in an ADR doc nobody reads — don't survive team turnover or code reviews. Puritan turns those decisions into auditable doctrine files that Claude can check your code against, commit by commit.

**2. PR review is a workflow, not a scroll.**
Bot reviewers and human reviewers leave dozens of comments across multiple rounds. Tribunal treats this as a structured workflow: fetch everything, categorise by source and type, validate each comment against the actual current code, propose fixes, apply them with your approval, and resolve the threads.

## The Witchfinder

Both plugins operate in the voice of a deeply principled but self-aware Puritan inspector. Violations are heresies. Fixes are absolution. The codebase is the sanctum.

The persona is flavour, not a barrier to clarity — every verdict is technically precise and actionable. The Witchfinder is dramatic, not obscure.

## Optional: Witchfinder spinner verbs

`settings.snippets.json` at the repo root contains custom spinner verbs that replace Claude Code's default "Thinking…" messages with in-character Witchfinder flavour while the skills are running.

To use them, copy the file into your Claude Code settings directory:

```bash
cp settings.snippets.json ~/.claude/settings.snippets.json
```

If you already have a `settings.snippets.json`, merge the `spinnerVerbs` block into it manually.

> The `mode: "replace"` setting replaces all default spinner verbs with these. If you'd prefer to add them alongside the defaults, change it to `"append"`.

## Contributing

Issues and PRs welcome. If you extend a doctrine or add a new one, the [Scriptorium](plugins/puritan/) skill can help you author it to the required standard.
