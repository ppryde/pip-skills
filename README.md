# pip-skills

A personal collection of Claude Code skills for serious engineering work — from PR review to architectural auditing. Built for my own workflows, shared because they might help yours.

## Installation

Install directly from GitHub using the Claude Code plugin command:

```bash
claude plugin install https://github.com/ppryde/pip-skills
```

## Skills

| Skill | Command | Description |
|-------|---------|-------------|
| PR Review | `/pip-skills:pr-review` | Senior-engineer-level review of the current git diff / pull request |
| Architectural Audit | `/pip-skills:arch-audit` | Deep structural analysis of the codebase — coupling, layering, risks |
| Code Review | `/pip-skills:code-review [file]` | Focused review of a specific file or function |
| Test Generation | `/pip-skills:test-gen [file]` | Comprehensive unit and integration tests for the specified code |
| Refactor | `/pip-skills:refactor [file]` | Concrete refactoring suggestions for readability and maintainability |
| Security Scan | `/pip-skills:security-scan [file]` | Vulnerability analysis with severity ratings and remediation guidance |
| Docs Generator | `/pip-skills:docs-gen [file]` | Generates docstrings, module docs, or a full README |
| Commit Message | `/pip-skills:commit-msg` | Conventional-commit message from the current staged diff |
| Debug Assistant | `/pip-skills:debug-assist [error]` | Systematic root-cause analysis and fix for a reported bug |
| Changelog | `/pip-skills:changelog` | Keep a Changelog entry from recent git commits |

## Usage Examples

```
# Review everything in the current PR
/pip-skills:pr-review

# Audit the architecture of the whole codebase
/pip-skills:arch-audit

# Review a specific file
/pip-skills:code-review src/auth/middleware.ts

# Generate tests for a module
/pip-skills:test-gen src/utils/parser.py

# Suggest refactoring improvements
/pip-skills:refactor src/services/UserService.java

# Security scan a specific file
/pip-skills:security-scan src/api/routes.go

# Generate JSDoc for a module
/pip-skills:docs-gen src/lib/crypto.ts

# Write a commit message for staged changes
/pip-skills:commit-msg

# Debug an error
/pip-skills:debug-assist TypeError: Cannot read property 'id' of undefined

# Generate a changelog entry for the next release
/pip-skills:changelog
```

## Repository Structure

```
pip-skills/
├── .claude-plugin/
│   ├── plugin.json         # Plugin manifest
│   └── marketplace.json    # Marketplace metadata
├── skills/
│   ├── pr-review/SKILL.md
│   ├── arch-audit/SKILL.md
│   ├── code-review/SKILL.md
│   ├── test-gen/SKILL.md
│   ├── refactor/SKILL.md
│   ├── security-scan/SKILL.md
│   ├── docs-gen/SKILL.md
│   ├── commit-msg/SKILL.md
│   ├── debug-assist/SKILL.md
│   └── changelog/SKILL.md
├── LICENSE
└── README.md
```

## License

MIT
