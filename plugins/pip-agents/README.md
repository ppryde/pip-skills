# pip-agents

Seven shared subagent personas for pip-skills plugins, built from one base, with one brief/result contract and its
validator. No skills, no hooks, no consumer wired in yet: each consumer plugin moves onto it in its own PR and
declares `"dependencies": ["pip-agents"]`.

| Agent | Kind | Tools | Does |
|---|---|---|---|
| `pip-agents:reviewer-correctness` | review | Read, Bash, Monitor | wrong results, edge cases, vacuous tests |
| `pip-agents:reviewer-security` | review | Read, Grep, Glob | source-to-sink security defects |
| `pip-agents:reviewer-scope` | review | Read, Grep, Glob | unapproved change, scope leak, back-compat breaks |
| `pip-agents:reviewer-rules` | review | Read, Grep, Glob | one batch of rulebook rules (at most 30) against a target |
| `pip-agents:validator` | validate | Read, Grep, Glob | confirms or refutes up to 10 claims |
| `pip-agents:explorer` | locate | Read, Grep, Glob | locations of names inside a target, never contents |
| `pip-agents:gatekeeper` | run | Bash, Read, Monitor | runs one named command, returns counts and a path |

Install: `/plugin install pip-agents --marketplace ppryde/pip-skills`

## The contract in five lines

1. The agent's whole prompt is a brief: `key: value` lines (`brief: pip-agents/1`, `kind:`, optional `ref:`, then paths and short values), never pasted text.
2. The agent ends its final message with one ```` ```pip-agents-result ```` block holding a JSON object; the last such block wins.
3. The envelope is `result, kind, persona, status, summary, checked, unchecked, out_of_lens, injection_attempts` plus a `payload` per kind (or `error` when `status` is `error`).
4. `contract/result.schema.json` and `contract/brief.schema.json` are the law; `scripts/validate_result.py` (stdlib, runs under `python3 -I`) checks a brief, a result and the cross rules (`contract/VALIDATOR.md`).
5. Revision `contract/REVISION` (`1.0 <sha256 of the schemas>`) changes with the schemas; `contract/VERSIONING.md` says what bumps what.

## Layout

- `agents/`: GENERATED, never hand-edited. `python3 tools/build_agents.py` rebuilds; `--check` fails on drift.
- `personas/`: the sources (`common.md`, the two bases, `lenses/`, `validator.md`, `explorer.md`, `gatekeeper.md`) and `tools.md`, the one table of tool grants. They sit outside `agents/` because subfolders of `agents/` load as agents.
- `contract/`: schemas, specs, `examples/`, generated `personas.json` (persona -> kind and lens).

## Using it from a consumer plugin

1. Add `"dependencies": ["pip-agents"]` to the consumer's `plugin.json` (no fallback to `general-purpose`).
2. Write a brief file per dispatch and spawn `pip-agents:<name>` with the brief text as the prompt.
3. Validate the final message with `validate_result.py` (`parse_result(message, brief, persona)`) before merging results; re-dispatch once on rejection.
4. A skill cannot rely on reaching this plugin's files at run time: `${CLAUDE_PLUGIN_ROOT}` is the consumer's own root and no environment variable names a dependency's path (probe recorded in the PR). Consumers vendor `validate_result.py` and the two schemas with a hash drift test (`tools/sync_contract.py`, first needed by the review-panel PR).

Dev tools live in `tools/`: `build_agents.py`, `batching.py` (30-rule cap) and `measure_spawn.py` (first-call token cost, by hand).
