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
`budgets.json` there only.
