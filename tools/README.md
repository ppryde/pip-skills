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
  categories, and a split never leaves a batch under the floor (31 rules plan as 16 + 15, not 30 + 1); units under the
  floor pack only when their scope lists are identical and declared (an empty scope is "unspecified", never packed).
  Consumers import the constants for their drift tests.
- `measure_spawn.py` runs by hand against a real account (a few cents), never in CI. `run` copies the plugin to a
  temp dir first (a `--plugin-dir` under `.claude/worktrees` silently loads the installed version). The ratchet: a
  later PR may not raise a persona's first-call input tokens by more than 5 % without saying why.

  Baseline (PR A, personal Max account, `--model haiku` main session, hooks and MCP attachments of that account
  included, which is why it sits above the ~4.3-4.6k design estimate; compare only on the same account/config):

  | persona | first-call input tokens | ratchet ceiling (+5 %) |
  |---|---|---|
  | reviewer-correctness | 8,317 | 8,733 |
  | reviewer-security | 5,481 | 5,755 |
  | reviewer-scope | 5,456 | 5,729 |
  | reviewer-rules | 5,292 | 5,557 |
  | validator | 5,010 | 5,260 |
  | gatekeeper | 6,965 | 7,313 |
  | explorer | 4,581 | 4,810 |

  Main-session agent-listing delta: +472 to +506 tokens (35,346 without the plugin, 35,818 and 35,852 with it).
  The two `Bash, Monitor` personas (reviewer-correctness, gatekeeper) are the dearest spawns; `Monitor` resolves
  for both (tool list read back: Read, Bash, Monitor).
- Tests: `tests/agents/` (run by `tests/run.sh`). Sync to wf-claude-market: copy `plugins/pip-agents/`, the three
  tools and `tests/agents/` as one unit; the build is deterministic, so wf runs the same `--check`.

## derive_agent_tools.py (permissions, WF-271 PR 3)

Stdlib only; **read-only**: it prints to stdout and opens no file for writing (a test runs it under a read-only
tree). Reads `chronicle permits --json` and proposes `tools:` changes as a unified diff for review.

```
chronicle permits --json > permits.json
python3 tools/derive_agent_tools.py --evidence permits.json              # diffs + a settings snippet, stdout only
python3 tools/derive_agent_tools.py --evidence permits.json --snapshot   # the tests/agents/evidence.json text
python3 tools/derive_agent_tools.py --evidence permits.json --check      # diff the committed snapshot; exit 1 on drift
```

- Tightening (remove a tool exposed and unused across `--min-runs`, default 10) is proposed normally; with Bash granted,
  Grep and Glob are never proposed for removal (not exposed, so zero calls prove nothing). A persona below
  `--min-runs` gets nothing. Loosening (add a tool, or an allow line) is labelled LOOSENS and needs evidence of need
  ("no such tool", or a read-only shape a person approved temporarily at least 3 times and never otherwise).
  A shape the classifier, safety check, worktree guard or sleep guard refused is never an allow rule: it is listed under
  "investigate the command shape" with its sub-cause, and the remedy is charter text a human writes.
- The diff targets `personas/tools.md` when the plugin keeps its grants there (then run `tools/build_agents.py`), else
  the agent file's frontmatter. A person applies it with `git apply` in a reviewed PR.
- `tests/agents/evidence.json` is the checked-in snapshot (aggregates only: per persona runs, tool-call counts, denial
  causes, prompts) plus the human-written `unobserved` reasons, which the generator carries over and never invents.
  The persona lint (`tests/agents/test_derive_agent_tools.py`) requires every granted tool to be observed in the snapshot
  or listed `unobserved` with a one-line reason. **Day one every grant is `unobserved`**: no `pip-agents:*` run can exist
  before the consumer PRs move dispatches onto the personas, so that is the starting state, not a defect. The scan of the
  work account (aggregates only) is the owner's own act and is not part of any PR.
