# pip-agents tools table (PROVISIONAL; the one place tool lists live)

Owned by the permissions audit (subagent-permissions.md + verdict). build_agents.py reads this table; the lint asserts each
composed `tools:` equals its row. Day one: every grant is `unobserved:` (no `pip-agents:*` runs can exist before consumer
PRs B-G), and the generator proposes nothing below `--min-runs 10` (permissions verdict change 8).

Never granted to any persona: Agent, Skill, Edit, Write, MCP, WebFetch/WebSearch. No persona carries `disallowedTools`
(F5: denying ToolSearch loads every MCP schema, 93.5k tokens). `tools` is never omitted (omission grants everything, F4).

| persona | kind | tools | evidence for each grant | withheld, and why |
|---|---|---|---|---|
| reviewer-correctness | review | Read, Bash, Monitor | Its consumer #14 (test-crucible Phase 6) used Bash (sed, python, grep, ruff, git), Read and Monitor in its one run (perm §1.4); overseer-reviewer Read + Bash (git log, pytest), 5 runs; GR reviewers Bash-heavy (git show/diff, pytest), 115 runs. Needs `git diff/show/grep` and the brief's `tests:` command. Monitor backs the charter text "use Monitor, not sleep" (59 sleep-guard denials). **Unverified:** that an explicit `Monitor` grant resolves in a plugin agent (deferred tool in main sessions on 2.1.296); probe in PR A `measure_spawn.py` | Grep, Glob: not exposed when Bash is granted (F11; 0 Grep/Glob calls in every Bash bucket). Edit, Write: used by test-crucible run and GR reviewers, withheld by the read-only charter (mutation "scratch copy" check dropped) |
| reviewer-security | review | Read, Grep, Glob | No runs (unobserved). Diff arrives as a file the lead wrote; Grep/Glob for source-to-sink tracing | Bash: this lens reads the most hostile text; a shell turns injection into execution |
| reviewer-scope | review | Read, Grep, Glob | No runs (unobserved). Grep for callers/consumers of changed public names (F11 keeps the schema) | Bash: old code comes from the `--function-context` diff; outside hunks is `unchecked` |
| reviewer-rules | review | Read, Grep, Glob | Puritan doctrine agents: Read only, 22/22 calls, 9 runs (below --min-runs). Doctrine tables and django groups carry grep hints, so Grep/Glob are load-bearing | Bash: **binding** (subagents.verdict change 4; puritan contract "no shell commands"); email `rules.py select/scan` moves to the lead. Overrides permissions verdict Q2 by that verdict's own rule ("if the sibling verdict sets a different list, that list wins") |
| validator | validate | Read, Grep, Glob | No runs (unobserved). subagents.verdict change 4 | Bash: verdict change 4 (perm §3.4 "as reviewer minus Write" superseded). Claims needing execution return `refuted` with `unverified:`; the lead may route them to reviewer-correctness |
| gatekeeper | run | Bash, Read, Monitor | No runs. Runs the one named script (`collect.py`, #11/#12); Read confirms `out:` and reads its `counts`. Monitor (session 3): the charter line "use Monitor, not sleep" goes verbatim into every Bash-bearing body, so the tool it names must exist; same resolution probe as reviewer-correctness | Grep, Glob: F11; locator work goes through the named command |
| explorer | locate | Read, Grep, Glob | No runs (unobserved). Consumer #7 django grep pass is two Grep scans (imports, attribute uses) over a target list; Glob expands the target; Read confirms a hit is an import or attribute use, not a comment | Bash: F11 (Bash would remove Grep/Glob and force pipes the charter forbids); the gatekeeper route was rejected because the two-grep pass needs a pipe. Edit, Write: never |

Charter text in every Bash-bearing body (permissions verdict counsel; 335 worktree-guard + 59 sleep-guard denials):
"One plain command per Bash call; use Monitor, not sleep." Never an allow rule (WORKER_BRIEF rule).

## Specialists considered and not built (DECISIONS.md "Specialists"; owner asked, see STATUS.md)

| candidate | would need | why not now |
|---|---|---|
| planner | Read, Grep, Glob, Write (plan file) | only consumer is overseer orchestrate (#15), whose agents stay (subagents.verdict Q3) |
| implementer | Read, Grep, Glob, Bash, Edit, Write, Skill | same; also orchestrate SKILL.md:145 sends MCP-needing chunks to general-purpose, and pip-agents never grants MCP |
| verifier / test-runner | Read, Bash, Monitor | same; overseer-verifier stays; reviewer-correctness already runs a brief's `tests:` command |
| summariser | Read | no spawn site; review-clone keeps theme extraction in the main session on purpose |
| researcher / scout | Read, Grep, Glob, WebFetch | no spawn site; the built-in Explore agent covers ad-hoc use; WebFetch is never granted |

Each would also add a line to every session's agent listing whether used or not (verdict counsel: listing cost is per session).
