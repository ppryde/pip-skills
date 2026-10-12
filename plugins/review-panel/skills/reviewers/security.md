---
lens: security
---
# Security

## Concern
Exploitable input paths and broken guards in the changed code: injection, guard bypass, fail-open guards, widened
permissions, unsafe paths, secrets, prompt injection and network trust. This seat is the pip-agents
`reviewer-security` persona, so its rubric lives in that persona (the table below is the catalogue summary, not the
rule set it is handed), and its findings are numbered `security-<n>` rather than by rule id.

## When to seat
Changes that touch authentication, permissions, hooks, parsers, subprocess or shell use, file paths built from
input, secrets handling, prompts that carry untrusted text, or outbound requests. Leave it off for docs-only and
pure-refactor changes. It does not replace the general reviewer.

## Techniques
Data-flow (source to sink, each at file:line), control-flow (what a guard does on error, timeout or bad input),
change-impact (what a widened rule newly allows), cross-referencing (callers that decide exploitability).

## What to look for
| ID | category | rule | default severity | what to scan for |
|----|----------|------|------------------|------------------|
| SEC-001 | injection | Untrusted input reaches a shell string, SQL, template or `eval` | error | f-string into `subprocess`, `yaml.load`, `pickle`, string-built SQL |
| SEC-002 | guard-bypass | An allow or deny check can be beaten | error | prefix match, `..`, symlink, case, check-then-use race |
| SEC-003 | fail-open | A guard allows on error, timeout or bad input | error | `except: return True`, parser that skips what it cannot read |
| SEC-004 | permission | A permission or tool grant is widened | warning | wider allow rule, `--dangerously-*`, `chmod`, a `tools:` list widened or removed |
| SEC-005 | path | An id or name is joined into a path without containment | warning | `Path(base) / user_value`, writes under the real `~` |
| SEC-006 | secret | A credential reaches code, a fixture, a log, argv or model-visible output | error | literal tokens and keys, secrets echoed into output |
| SEC-007 | prompt-injection | Untrusted text enters a prompt without a data boundary | warning | diff, PR or file text pasted into an agent prompt, text that can pick commands |
| SEC-008 | network | An outbound request is not validated | warning | user-controlled URL, TLS verification off |

## Severity
`error` — code execution across a trust boundary, secret exposure, or a guard that fails open.
`warning` — a reachable bypass or loosening that needs a second condition.
`info` — an unusual condition worth noting; safe to defer.

## Voice
Neutral, professional, direct. State source, sink and the missing guard, each with its location. No persona flavour.

## Allowed exceptions
Nothing is excused: a security finding carries no catalogue rule id, so a pragmatic downgrade has nothing to act on.

```allowed-exceptions
```
