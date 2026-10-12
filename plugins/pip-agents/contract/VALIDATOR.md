# VALIDATOR: spec for PR A's `plugins/pip-agents/scripts/validate_result.py`

Shipped as `scripts/validate_result.py`, a stdlib port of the design prototype; the rules below are normative.
The claims file named by a validate brief is read to check verdict ids (the one file it opens).

## Purpose and callers
One module, two uses: (1) consumer skills' merge code calls `parse_result(message, brief, persona)` on each agent's
final message before merging; (2) PR A's tests validate the examples and the composed personas' skeletons. Stdlib only
(hooks and skills run under a plain `python3`, the overseer `schemas.py` precedent). No `jsonschema` dependency: the
checker implements the subset the two schemas use (`type`, `const`, `enum`, `required`, `properties`,
`additionalProperties`, `items`, `minItems`, `maxItems`, `maxLength`, `minimum`, `maximum`, `pattern`, local `$ref`,
`allOf`, `anyOf`, `not`, `if/then/else`, `dependentRequired`). A schema keyword outside that subset fails the test suite,
so the schema cannot silently outgrow the checker. Annotations are allowed and never validated: `$schema`, `$id`, `title`, `description`, `x-hint` (the
placeholder text in generated skeletons, at most 30 chars), `x-lens`
(the field belongs to that lens's skeleton only) and `x-persona: false` (adapters only; never in a persona skeleton).

## CLI
`python3 -I validate_result.py --brief <brief file> --message <final message file> --persona <name>`
`python3 -I validate_result.py --brief-only <brief file>` (consumers' tests check the briefs they generate)
stdout: one JSON object `{"ok": bool, "kind": str|null, "errors": [str]}`. Exit 0 valid, 1 invalid, 2 usage or unreadable file.

## Parsing a brief
- UTF-8 text; one field per line, `^([a-z_]+): (.*)$`; blank lines ignored; any other line is an error (a pasted rule
  body or file content in a brief is exactly what this catches).
- A key may appear once. Values are strings, except `limit` and `timeout_ms`, which must be decimal integers.
- The parsed object is validated against `brief.schema.json`.

## Extracting the result block (the rule)
1. Search the agent's **final message only** (the last assistant text the Agent tool returns; earlier turns are never read).
2. A block opens with a line that is 3 or more backticks, or 3 or more tildes, immediately followed by the info string
   `pip-agents-result` (first word; trailing spaces or tabs allowed, nothing else), and closes with a line holding the
   same fence character repeated the same number of times, alone (trailing whitespace allowed). Regex, multiline + dotall:
   ``^(`{3,}|~{3,})pip-agents-result[ \t]*\n(?P<body>.*?)^\1[ \t]*$``
3. If several blocks match, take the **last**. A quoted example earlier in the message is harmless (overseer
   `schemas.py` `_BLOCK_RE`, same reasoning).
4. No match: error `E_NO_BLOCK`. A block fenced as ```` ```json ````, an unfenced object, or a block with a different info
   string is NOT accepted, and there is no fallback guess. The error text names what was found ("found a ```json block;
   expected ```pip-agents-result") so the lead can re-dispatch once.
5. `json.loads` the body; failure is `E_BAD_JSON` with the decoder message. The decoded value must be an object.
6. Prose before or after the block is allowed and ignored; a persona puts a one-line headline before it at most.

## Checks, in order (all errors collected, not first-fail)
1. Result object against `result.schema.json`.
2. `persona` equals `--persona`; `kind` equals the brief's `kind` and the persona's kind in tools.md (the build writes
   a `persona -> {kind, lens}` map into `contract/personas.json`). No `x-persona: false` field appears in a persona's result.
3. `ref` equals the brief's `ref` when the brief has one; absent when it has none.
4. `status: error` carries `error` and no `payload`; any other status carries `payload` and no `error`.
5. Per kind:
   - `review`: `payload.lens` equals the persona's `lens` in `contract/personas.json` (so `general` is adapter-only); finding ids unique across `findings` and `medium` (except lens `rules`, where `id` is a rule id and may
     repeat on different lines); each finding's `file` appears in `checked` or in the brief's `target`; lens `rules`:
     `rules_checked` denominator equals the batch size parsed from the brief's `rules:` `(<ids>)` list, and every finding
     and `n_a` id is in that list; lens fields only on their lens (`trigger`, `commands_run` correctness; `old`, `new`,
     `intent`, `affected` scope; `rules_checked`, `n_a` rules).
   - `validate`: verdict ids equal the claims file's ids, same order, each once; `unverified:` reasons only on
     `refuted`; `restated` present iff `weakened`.
   - `locate`: hits at most the brief's `limit` (default 200); `truncated` true iff hits equal the limit; `counts` keys
     equal the brief's `names` (no names: `counts` empty).
   - `run`: `command` equals the brief's `run` verbatim; `counts` keys equal the brief's `counts` names; `out` is null or
     equals the brief's `out`; `stderr_tail` only when `exit_code` is non-zero or null.
   - `plan` (planner persona): `chunks`, when given, equals the number of `steps`; a `done` plan lists its steps; `needs_context`
     lists its questions. `change` (implementer): `tests_passed` at most `tests_total`; a `done` change names its commits. `test`
     (verifier): `outcome` is `pass` iff every gate exits 0 and no failures are listed; with a `tests:` line in the brief the
     single gate is that command verbatim. `summary` (summariser) and `research` (researcher): an `ok` result has at least one
     point or source. Adapter results (overseer, MAPPING.md) are checked against the schema only: they never reach `cross_check`.
6. `injection_attempts` entries non-empty: never an error, but `parse_result` returns them so the lead reports them.

## What it does not do
It does not judge findings, open the cited files, or re-run anything: evidence quality is the validator persona's job
(review-panel adversarial critic), not the script's. It never rewrites a result: an invalid result is rejected whole and
the lead re-dispatches once, then reports the seat as `error`.

## Tests (PR A, `tests/agents/test_contract.py`)
Every example valid; each of these invalid: `error` with `status: ok`; missing `payload`; unknown finding field
(`confidence`); unknown lens; a ```` ```json ```` block only; two blocks where only the first is valid (last wins, so
invalid); a brief with `run:` on kind `review`; a brief line of pasted text; `restated` on `confirmed`; `unverified:` on
`confirmed`; `counts` keys differing from `names`.
