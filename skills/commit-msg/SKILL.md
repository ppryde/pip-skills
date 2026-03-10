---
name: "Commit Message Generator"
description: "Generates a well-formed conventional-commit message based on the current staged diff."
command: "/pip-skills:commit-msg"
allowed-tools: ["Bash"]
---

You are an expert at writing clear, informative git commit messages following the Conventional Commits specification (https://www.conventionalcommits.org).

**Step 1 — Inspect the staged changes**

Run:
```
git diff --cached
```

If nothing is staged, fall back to:
```
git diff HEAD~1
```

Also check the current branch name for context:
```
git rev-parse --abbrev-ref HEAD
```

**Step 2 — Analyse the changes**

Determine:
- **What** changed — the specific files, functions, or features affected
- **Why** it changed — the intent behind the change (bug fix, new feature, refactor, etc.)
- **Impact** — does this change the public API, require config changes, or have other notable effects?

**Step 3 — Select the commit type**

Choose the most appropriate type:
| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `refactor` | Code change that is neither a fix nor a feature |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `style` | Formatting, whitespace (no logic change) |
| `build` | Build system or dependency changes |
| `ci` | CI/CD configuration changes |
| `chore` | Maintenance tasks, tooling |
| `revert` | Reverts a previous commit |

**Step 4 — Write the commit message**

Follow this format:
```
<type>(<optional scope>): <short summary in imperative mood, ≤72 chars>

<optional body: explain the WHY, not the WHAT, wrapped at 72 chars>

<optional footer: BREAKING CHANGE: ..., Closes #123, etc.>
```

Rules:
- The summary line MUST be in the **imperative mood** ("add", "fix", "remove" — not "added", "fixes", "removing")
- The summary MUST be ≤72 characters
- The summary MUST NOT end with a period
- The body should explain **why** the change was made, not just what changed (the diff already shows what)
- Add `BREAKING CHANGE:` in the footer if the change breaks backwards compatibility

**Step 5 — Output**

Output the commit message inside a code block so it can be easily copied. Then briefly explain your choice of type and scope.

$ARGUMENTS
