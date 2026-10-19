# Delegation: who does what

The main session holds the conversation, the approval gate and nothing heavy. Comment payloads, code reads and fixes happen in subagents on Sonnet:

```
Agent({ subagent_type: "general-purpose", model: "sonnet", description: "...", prompt: "..." })
```

**Nesting guard.** If you are already a subagent (your caller says so, or you have no Agent tool), do not spawn: run the steps inline and return the same compressed result the subagent would.

## Triage subagent (Steps 1–7)

Give it paths and facts, not pasted rule text. Its prompt:

- The skill directory, and that it runs Steps 1–7 of tribunal:reckoning by reading `SKILL.md` (Untrusted input, Hard rules) and the step references (`fetch.md`, `categorise.md`, `validate.md`, `present.md`, `commands.md`); in progress mode `progress-summary.md` instead of 4–7. It must not invoke the skill itself or spawn agents.
- The PR from the pre-check (`repo`, `pr`, `head_sha`, `reason`), the mode, any reviewer or tier filter, and whether the user asked to skip validation.
- That it never asks the user anything: questions (PR not found, closed PR, a bot still running, more than 50 comments) come back as a `NEEDS:` line for the main session to ask.
- That it returns **only** the compressed summary below, at most ~1,500 tokens.

Compressed summary format:

```
PR #<n> <owner/repo> · <review status> · <unresolved> unresolved threads · bot review running: <no | name>
NEEDS: <question for the user>            (only if blocked)
Critical
C1 <file:line> — <reviewer> — <issue> — <proposed fix>
High
H1 ...
Medium
M1 ...
Low
L1 ...
Conflicts: <labels and the choice>   Suspicious: <items>   Notices: <draft/closed/merged>
```

One line per item, labels as in `present.md` (C1, H1, …), "— likely invalid: <reason>" appended where Step 5 says so, groups and duplicates already condensed. Keep the thread-id mapping inside the subagent's working notes only if a fix subagent will need it: it can re-fetch.

In progress mode the subagent returns the progress report instead, and in "resolve threads" mode the numbered unresolved threads (file:line — reviewer — first line).

## Main session after the summary

1. Present the summary (Witchfinder voice), plus the cost line: the subagent's token count and tool uses from the Agent result, e.g. "triage: 48k tokens, 23 tool calls (Sonnet)". Report every subagent's usage the same way so callers can log cost.
2. If it carries a `NEEDS:` line, ask the user, then resume the same subagent (SendMessage) or spawn a new one with the answer.
3. Step 8 gate as in `action-resolve.md`: branch guard, approval, conflicts and likely-invalid confirmations stay in the main session.

## Fix subagent (Steps 8–9)

Spawn one Sonnet subagent with: the PR (repo, number, head branch), the approved item lines verbatim from the summary (with any conflict choices), the skill directory and an instruction to read `action-resolve.md` and `commands.md`. It applies the approved fixes only, reports one line per item (applied / action failed: reason / requires upstream change) and returns. When the user then agrees to resolve, send it (or a new one) the list of threads to resolve; it re-fetches thread ids with the 3d query and resolves only those, following the Step 9 rules.

Then save the state (`precheck.md`).
