# pip-skills

A personal collection of Claude Code skills for serious engineering work — from PR review to architectural auditing. Built for real workflows, shared because they might help yours.

## What's in here

Two plugins, each with a distinct purpose:

| Plugin | Purpose |
| --- | --- |
| [**Puritan**](https://github.com/ppryde/pip-skills/blob/main/plugins/puritan) | Architectural doctrine enforcement — plan patterns, audit code, author rules |
| [**Tribunal**](https://github.com/ppryde/pip-skills/blob/main/plugins/tribunal) | PR review workflow — fetch, triage, validate, action, and resolve GitHub PR comments |

## Installing

### Marketplace Installation (Recommended)

1. Open Claude.ai in your browser
2. Go to **Settings** → **Plugins**
3. Click **Browse marketplace**
4. Search for **Puritan** or **Tribunal**
5. Click **Install**
6. The skills are now available in your chat

### Claude Code CLI Installation

You can also install via Claude Code's plugin commands. From within a Claude Code session:

```
/plugin marketplace add ppryde/pip-skills
/plugin install puritan@ppryde/pip-skills
/plugin install tribunal@ppryde/pip-skills
```

Or from the terminal CLI:

```
# Install both plugins
claude plugin install puritan@ppryde/pip-skills
claude plugin install tribunal@ppryde/pip-skills
```

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

```
cp settings.snippets.json ~/.claude/settings.snippets.json
```

If you already have a `settings.snippets.json`, merge the `spinnerVerbs` block into it manually.

> The `mode: "replace"` setting replaces all default spinner verbs with these. If you'd prefer to add them alongside the defaults, change it to `"append"`.

## Contributing

Issues and PRs welcome. If you extend a doctrine or add a new one, the [Scriptorium](https://github.com/ppryde/pip-skills/blob/main/plugins/puritan) skill can help you author it to the required standard.

## About

A personal collection of Claude Code skills for serious engineering work — from PR review to architectural auditing. Built for my own workflows, shared because they might help yours.

### License

[MIT license](./LICENSE)
