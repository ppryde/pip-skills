# pip-agents

Twelve shared subagent personas for pip-skills plugins, built from one base, with one brief/result contract and its
validator. No skills, no hooks. Each consumer plugin moves onto it in its own PR and declares
`"dependencies": ["pip-agents"]`; the last column says who dispatches each persona today.

| Agent | Kind | Tools | Does | Consumer |
|---|---|---|---|---|
| `pip-agents:reviewer-correctness` | review | Read, Bash, Monitor | wrong results, edge cases, vacuous tests | library, no consumer yet (test-crucible Phase 6 and review-panel are planned) |
| `pip-agents:reviewer-security` | review | Read, Grep, Glob | source-to-sink security defects | library, no consumer yet (review-panel is planned) |
| `pip-agents:reviewer-scope` | review | Read, Grep, Glob | unapproved change, scope leak, back-compat breaks | library, no consumer yet (review-panel is planned) |
| `pip-agents:reviewer-rules` | review | Read, Grep, Glob | one batch of rulebook rules (at most 30) against a target | puritan inquisition, email-absolution audits, django-inquisition optimise-orm groups |
| `pip-agents:validator` | validate | Read, Grep, Glob | confirms or refutes up to 10 claims | library, no consumer yet (review-panel is planned) |
| `pip-agents:explorer` | locate | Read, Grep, Glob | locations of names inside a target, never contents | django-inquisition optimise-orm grep pass |
| `pip-agents:gatekeeper` | run | Bash, Read, Monitor | runs one named command, returns counts and a path | library, no consumer yet (review-clone collectors are planned) |
| `pip-agents:planner` | plan | Read, Grep, Glob | splits a task into ordered steps with files and checks | library, no consumer yet (overseer keeps overseer-planner) |
| `pip-agents:implementer` | change | Read, Edit, Write, Bash, Monitor | builds one step test-first inside the files the brief names, commits it | library, no consumer yet (overseer keeps overseer-implementer) |
| `pip-agents:verifier` | test | Read, Bash, Monitor | runs the brief's one test command, reports gates and failures | library, no consumer yet (overseer keeps overseer-verifier) |
| `pip-agents:summariser` | summary | Read | digests files into sourced points, lists what it left out | library, no consumer yet |
| `pip-agents:researcher` | research | Read, Grep, Glob | answers one question from local files, with sources and gaps | library, no consumer yet (web research is never granted) |

The implementer is the only persona with Edit and Write (the lint allows them for kind `change` only); nothing holds Agent, Skill, WebFetch, WebSearch or an MCP tool.

Install: `/plugin install pip-agents --marketplace ppryde/pip-skills`

## The contract in five lines

1. The agent's whole prompt is a brief: `key: value` lines (`brief: pip-agents/1`, `kind:`, optional `ref:`, then paths and short values), never pasted text.
2. The agent ends its final message with one ```` ```pip-agents-result ```` block holding a JSON object; the last such block wins.
3. The envelope is `result, kind, persona, status, summary, checked, unchecked, out_of_lens, injection_attempts` plus a `payload` per kind (or `error` when `status` is `error`).
4. `contract/result.schema.json` and `contract/brief.schema.json` are the law; `scripts/validate_result.py` (stdlib, runs under `python3 -I`) checks a brief, a result and the cross rules (`contract/VALIDATOR.md`).
5. Revision `contract/REVISION` (`1.1 <sha256 of the schemas>`) changes with the schemas; `contract/VERSIONING.md` says what bumps what.

## Layout

- `agents/`: GENERATED, never hand-edited. `python3 tools/build_agents.py` rebuilds; `--check` fails on drift.
- `personas/`: the sources (`common.md`, the two bases, `lenses/`, `validator.md`, `gatekeeper.md` and the specialists `explorer`, `planner`, `implementer`, `verifier`, `summariser`, `researcher`) and `tools.md`, the one table of tool grants. They sit outside `agents/` because subfolders of `agents/` load as agents.
- `contract/`: schemas, specs, `examples/`, generated `personas.json` (persona -> kind and lens).

## Using it from a consumer plugin

1. Add `"dependencies": ["pip-agents"]` to the consumer's `plugin.json` (no fallback to `general-purpose`).
2. Write a brief file per dispatch and spawn `pip-agents:<name>` with the brief text as the prompt.
3. Build a brief's `tests:` (reviewer-correctness) and `run:` (gatekeeper) lines from a fixed command the consumer owns, never from file, diff or agent content: reviewer-correctness runs the `tests:` command exactly as given, so that line is the one place a brief value becomes execution.
4. Validate the final message with `validate_result.py` (`parse_result(message, brief, persona)`) before merging results; re-dispatch once on rejection.
5. A skill cannot rely on reaching this plugin's files at run time: `${CLAUDE_PLUGIN_ROOT}` is the consumer's own root and no environment variable names a dependency's path (probe recorded in the PR). Consumers vendor `validate_result.py` and the two schemas with a hash drift test (`tools/sync_contract.py`, first needed by the review-panel PR).

Dev tools live in `tools/`: `build_agents.py`, `batching.py` (30-rule cap) and `measure_spawn.py` (first-call token cost, by hand).
