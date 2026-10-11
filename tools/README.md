# tools/

Repo-level dev tooling. Nothing here ships inside a plugin: plugins are installed whole, so
generators live here and the **generated artefact is committed inside the plugin**, which keeps
the installed plugin self-contained.

## build_index.py (lean skills, WF-268)

Stdlib-only, deterministic (sorted rows, LF line endings), no dependencies to pin.

```
python3 tools/build_index.py optimise-orm [--check]   # plugins/django-inquisition/skills/optimise-orm/checks/INDEX.md
python3 tools/build_index.py doctrines    [--check]   # plugins/puritan/skills/doctrines/INDEX.md
```

- `--check` writes nothing. It normalises CRLF to LF on both sides, prints a unified diff on drift
  and exits 1; exit 2 means the source files are malformed (for example a frontmatter id with no
  `### CODE` section).
- Spans are `L<start>-<end>`, 1-based as `Read` displays them, and mean
  `Read(file, offset=<start>, limit=<end>-<start>+1)`. A check's span runs from its `### CODE` heading
  to the line before the next heading (headings inside code fences are ignored). Every generated
  INDEX states this mapping in its header.
- Tests: `tests/lean/` (run by `tests/run.sh`). `tests/lean/budgets.json` has a per-file byte budget
  for every SKILL.md and `commands/*.md`, and an `indexes` table: an index becomes **enforced** (its
  committed file must equal the generated one) in the PR that first commits it.

## Sync to wf-claude-market (chosen option: carry the generator across)

wf-claude-market receives `tools/build_index.py`, `tests/lean/` (including `budgets.json`) and any
generated `INDEX.md` as a plain copy, in the same sync that carries the skill changes. wf can then
regenerate and run the same `--check` itself; it does not hold generated files it cannot rebuild.
Edits still follow the standing rule: fix in pip-skills first, merge, then sync wf. Every lean PR's
sync note lists these paths. If wf has plugins pip-skills lacks, add their rows to wf's
`budgets.json` there only. When copying, drop the pip-only `budgets.json` rows (files wf does not
have) and the overseer-ledger dangling-reference exemption in `test_references_wired.py` if wf's ledger skill differs.

## pip-agents tools (WF-270)

Stdlib only; `plugins/pip-agents/` holds the generated agents and the contract.

```
python3 tools/build_agents.py [--check]      # personas/ + contract/result.schema.json -> agents/*.md, contract/personas.json
python3 tools/measure_spawn.py run --plugin-dir plugins/pip-agents --persona reviewer-scope --config-dir ~/.claude-personal
python3 tools/measure_spawn.py report <session-dir> [--persona NAME]
```

- `build_agents.py` composes each agent from its base, the common sections, its lens file and the `personas/tools.md`
  row, and generates the output skeleton from the result schema. `--check` writes nothing, prints a unified diff and
  exits 1 on drift; lint failures (size over `COMPOSED_CAP`, tools not equal to the tools.md row, banned tool,
  description form, a stale `contract/REVISION` hash, a schema keyword outside the validator subset) exit 1 with
  every failure listed; a malformed source exits 2. `COMPOSED_CAP` is 5,632 B and provisional: the binding guard is
  the measured first-call token ratchet below.
- `batching.py`: `BATCH_CAP = 30`, `BATCH_FLOOR = 8`, `plan_batches(units)`. A unit over the cap splits along its
  categories; units under the floor pack only when their scope lists are identical. Consumers import the constants
  for their drift tests.
- `measure_spawn.py` runs by hand against a real account (a few cents), never in CI. `run` copies the plugin to a
  temp dir first (a `--plugin-dir` under `.claude/worktrees` silently loads the installed version). The ratchet: a
  later PR may not raise a persona's first-call input tokens by more than 5 % without saying why.
- Tests: `tests/agents/` (run by `tests/run.sh`). Sync to wf-claude-market: copy `plugins/pip-agents/`, the three
  tools and `tests/agents/` as one unit; the build is deterministic, so wf runs the same `--check`.
