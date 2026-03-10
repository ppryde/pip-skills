---
name: "Changelog Generator"
description: "Generates a changelog entry from recent git commits, following Keep a Changelog conventions."
command: "/pip-skills:changelog"
allowed-tools: ["Bash"]
---

You are a technical writer generating a changelog entry following [Keep a Changelog](https://keepachangelog.com) conventions and [Semantic Versioning](https://semver.org).

**Step 1 — Gather commit history**

Determine the range of commits to include. Try these commands in order:

Get recent tags to determine the last release:
```
git tag --sort=-version:refname | head -5
```

Get commits since the last tag:
```
git log $(git describe --tags --abbrev=0 2>/dev/null || echo "HEAD~20")..HEAD --oneline --no-merges
```

If no tags exist, use the last 20 commits:
```
git log --oneline --no-merges -20
```

Also get the current version from `package.json`, `pyproject.toml`, `Cargo.toml`, or `go.mod`:
```
cat package.json 2>/dev/null | grep '"version"' | head -1
```

**Step 2 — Categorise the commits**

Map each commit to a Keep a Changelog category:

| Category | Conventional Commit types |
|----------|--------------------------|
| **Added** | `feat` |
| **Changed** | `refactor`, `perf`, `style` |
| **Deprecated** | commits mentioning deprecation |
| **Removed** | commits removing features |
| **Fixed** | `fix` |
| **Security** | commits fixing vulnerabilities |

Ignore `chore`, `ci`, `build`, `test`, and `docs` commits unless they are user-visible.

For commits not using Conventional Commits format, use your judgement to categorise them based on the commit message wording.

**Step 3 — Determine the next version**

Apply Semantic Versioning rules:
- **BREAKING CHANGE** in any commit → increment **MAJOR**
- Any `feat` commit → increment **MINOR**
- Only `fix` / `perf` / `refactor` → increment **PATCH**

State the proposed next version and your reasoning.

**Step 4 — Generate the changelog entry**

Output a changelog entry in this exact format:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- Description of new feature (commit hash)

### Changed
- Description of change (commit hash)

### Fixed
- Description of bug fix (commit hash)

### Security
- Description of security fix (commit hash)
```

Rules:
- Each item should be written from the **user's perspective** — describe what they can now do or what no longer breaks
- Keep entries concise (one line each)
- Omit empty sections
- Link commit hashes where possible

**Step 5 — Placement instructions**

Explain where to insert the new entry in `CHANGELOG.md` (below the `## [Unreleased]` section header, or at the top if no Unreleased section exists).

$ARGUMENTS
