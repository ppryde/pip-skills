# Contract versioning

Two identifiers, one number:

- **Wire version** `pip-agents/<major>`: the `brief:` line of every brief and the `result` field of every result.
  Today `pip-agents/1`. Repo path: `plugins/pip-agents/contract/` (this folder, copied as-is in PR A).
- **Schema revision** `1.<minor>`: recorded in `plugins/pip-agents/contract/REVISION` (`claude plugin validate` warns on an unknown
  `plugin.json` key, so it is not recorded there) and in every composed agent's `generated:` frontmatter line
  (`generated: build_agents.py contract 1.<minor>`). It never appears on the wire.

## What bumps what

| Change | Bump | Wire string | Who must move |
|---|---|---|---|
| New optional field (envelope, payload, finding, brief), new lens-only finding field, longer `maxLength`, a description edit | minor | unchanged | nobody; consumers ignore what they do not read |
| New kind, new enum value in a field consumers branch on (`status`, `verdict`, `severity`, `outcome`) | minor, but the PR lists every consumer `match` on that field and updates it in the same PR | unchanged | the listed consumers |
| Field made required, renamed or removed; enum value removed or renamed; type changed; payload moved | **major** | `pip-agents/2` | every consumer and every persona, one PR |

Every bump also bumps the `pip-agents` plugin version and the marketplace version (feedback rule: every merge bumps
versions). A major bump also bumps every consumer plugin, because each consumer's parse code changes.

## Compatibility window

- Personas emit exactly one wire version: the one they were built with.
- Consumers and the validator accept the current major and the one before it for one release, then drop it; the drop is
  its own PR. Briefs are written by consumers, so a consumer never sends a brief newer than the personas it depends on:
  its `plugin.json` dependency on `pip-agents` names the minimum version that carries that wire major.
- There is no negotiation and no per-brief `contract:` override (retired; DECISIONS.md conflict 2 revision).

## Drift guards (PR A)

- `tests/agents/test_contract.py`: every `examples/*.result.md` and `*.brief.txt` validates; each kind in the schema's
  `kind` enum has one example pair; the stdlib checker and the schema agree on a fixed set of negative cases.
- `tests/agents/test_personas.py`: every composed agent's `generated:` revision equals the `contract/REVISION` revision; every
  composed output skeleton is regenerated from `result.schema.json` and must match byte for byte.
- A schema change without a `contract` revision change fails `test_contract.py` (hash of the two schema files is stored
  beside the revision in `contract/REVISION`: `1.0 <sha256>`, the sha256 of `brief.schema.json` bytes followed by `result.schema.json` bytes).
