# concordance — an owned symbol index for review, Python and TypeScript

## Why

The 2026-10-11 spike (`scratch/code-graph/code-graph-spike-report.md`, gitignored)
benched code-review-graph (crg) and graphify against plain Read/Grep on four
ledger-poc PRs, 12 Sonnet reviews. Neither graph beat the baseline: same
findings, ~50-74K tokens each, 1 useful graph call in 13. The blind spots were
removed code (a graph holds only what exists), semantics in strings (FK order in
SQL), fragile name resolution (`_refund_partial`, `DomainEvent` not found, a TS
type matched to a Python class) and broad queries that flood.

Two things the spike also showed:

1. The one useful call was exact: "who calls `RefundRepayment` and which test
   guards it".
2. The graph reviewers got a tool *menu* ("use it to understand the blast
   radius"), not a *procedure*. Part of the negative verdict measured weak
   instructions, not only weak tools.

So we build our own: small, exact, owned (security: we control the code), with
the review procedure as a first-class part of the product. Ideas are borrowed
with attribution from crg (MIT), graphify (Apache-2.0) and codebase-memory-mcp
(MIT, vendored vectors Apache-2.0); GitNexus (PolyForm-Noncommercial) for ideas
only, no code.

A concordance is the index of every place a word appears in scripture. This is
that, for symbols.

## Goals

1. **Exact answers** to: who calls this, which tests guard it, what still relies
   on what the diff removed, which call sites no longer match a changed
   signature.
2. **Detection in the CLI, judgement in the agent.** Everything deterministic runs
   as SQL/CLI at zero agent tokens; the agent only reads hits and judges meaning.
   Some checks need no judgement and return verdicts.
3. **A review procedure** (mandatory steps, each ending "finding" or "clean"),
   shipped with the tool and run by a review-panel `blast-radius` lens.
4. **Worktree-native:** one store per repo shared by all worktrees, answers scoped
   to the asking worktree, uncommitted edits included.
5. **Never blocks, never silent:** deadlines everywhere, unparsed files always
   reported.
6. **Measured before trusted:** the bench replay judges v1; shadow mode judges the
   hook before it injects anything.

## Non-goals (v1)

- Languages beyond Python and TypeScript.
- Hook injection and the pane (phase 2), flows (phase 3), embeddings (phase 4).
- Daemons, watchers, CLAUDE.md "ALWAYS use the graph" blocks, multi-platform
  installers, wikis, MCP server.
- Dev-container stores: a container has its own config dir and so its own store.

## Success criteria

- **v1:** on the bench replay the lens catches at least what the baseline
  catches, with fewer tokens or more findings, and case D (the clean PR) stays
  quiet (no error/warning findings).
- **Performance, ledger-poc (1,459 files):** cold build ≤ 45 s, incremental
  per-file update ≤ 200 ms, warm `review-context` ≤ 2 s.
- **Phase 2 gate:** see Shadow mode.

## Architecture

Python core plus per-language extractors (approach A of three; the alternatives,
an all-TS mod-native indexer and uniform tree-sitter, were rejected: the first
needs a CLI anyway for the lens, the second repeats the rivals' syntax-only
resolution failure).

```
plugins/concordance/
  pyproject.toml
  README.md
  scripts/concordance/         # Python package, CLI entry `concordance`
    cli.py
    store.py                   # SQLite schema + migrations (one writer)
    views.py                   # worktree → view (path → blob), base view from git
    index.py                   # hash-gated incremental build, lazy on first query, GC
    extract_py.py              # stdlib ast → facts
    extract_ts/                # Node script on pinned `typescript` → facts as JSON
    resolve.py                 # qualified-name resolution, "did you mean"
    diff.py                    # base/head trees → touched + removed items
    classify.py                # pure-refactor classifier (normalised ast compare)
    query.py                   # removed / sig-drift / callers / tests / literals
    render.py                  # budgeted output, whole rows, coverage footer
  skills/review-procedure/SKILL.md
  tests/
plugins/review-panel/skills/reviewers/blast-radius.md
```

Each unit has one job and is testable alone on fixture repos: extractors turn
source into facts and know nothing of storage; the store holds facts; views map a
worktree to file versions; the resolver maps names to symbols; queries answer
within a budget; render formats.

Phase 2 adds `plugins/concordance-mod/` (mod layout, see CLAUDE.md "Mod layout")
reading the same store. v1 stays a plain plugin, so nothing restructures later.

### Extractors

- **Python:** stdlib `ast`. Module qualname from the path relative to the
  worktree root (src-layout and package roots detected from `pyproject.toml`).
  Emits symbols (module, class, function, method, with line ranges, `is_test`
  from pytest conventions), references (calls, attribute access, imports,
  inheritance, decorators) with the raw dotted name, call-site argument shapes
  (positional count, keyword names, `*args`/`**kwargs` present), function
  signatures, string literals and comments with lines. No virtualenv needed.
- **TypeScript:** a Node script on the TypeScript compiler API, `typescript`
  pinned to an exact version in a lockfile. A custom compiler host serves file
  content from the view (so it works on the git-only base and on worktrees
  without `node_modules`). The checker resolves in-repo symbols exactly; imports
  from packages are labelled `external`, never `ambiguous`. Same fact shape as
  Python, as JSON on stdout.
- Both report per-file parse status; a file that fails or times out is recorded
  as such, not skipped silently.

### Store and worktrees

Repo identity is `git rev-parse --git-common-dir`; one store per repo under the
account's config dir (`$CLAUDE_CONFIG_DIR/concordance/<repo-key>/index.db`,
rooted at `CLAUDE_CONFIG_DIR`, never a hardcoded `~/.claude`). Nothing is written
into the repo.

Facts are content-keyed, not worktree-keyed:

| table | columns |
|---|---|
| `file_facts` | `path, blob_sha, lang, parsed_ok, error` — key `(path, blob_sha)` |
| `symbols` | `id, path, blob_sha, qualname, kind, line_start, line_end, is_test, signature_json` |
| `refs` | `path, blob_sha, src_symbol, target_name, kind, line, args_json` |
| `literals` | `path, blob_sha, kind (string\|comment), text, line` |
| `views` | `view_id, worktree_path, kind (worktree\|base), ref, built_at` |
| `view_files` | `view_id, path, blob_sha` |
| `events` | shadow-mode and query telemetry (see Shadow mode) |
| `meta` | schema version |

The path is part of the fact key because a Python qualname depends on it.

- **A view** is `git ls-files -s` for the worktree, with dirty and untracked
  (non-ignored) files hashed by `git hash-object`. A new worktree parses only
  files whose `(path, blob_sha)` is not already in `file_facts`; that is the hash
  gate and the incremental build in one mechanism.
- **The base view** is `git ls-tree -r <base>` with content from `git cat-file`;
  the base never needs a checkout and mostly reuses existing facts.
- **Resolution happens at query time within a view:** refs are joined against
  that view's symbol table, so divergent worktrees never contaminate each other.
  Each resolved ref carries `exact | inferred | ambiguous | external`. A per-view
  resolution cache may be added if measurement shows the need.
- **Concurrency:** WAL, `busy_timeout`, short write transactions, fact inserts
  `INSERT OR IGNORE` on `(path, blob_sha)` so racing indexers are harmless, plus a
  per-view lock with a deadline.
- **Output paths** are relative to the asking worktree's root; the CLI resolves
  its view from the cwd. No answer ever points into another worktree.
- **GC, lazy on build:** drop worktree views whose path is absent from
  `git worktree list --porcelain`, drop base views older than 7 days, then delete
  facts no view references.

### Diff, removed items, classification

`diff.py` compares base and head views of each changed file:

- **Touched symbols:** changed hunks mapped to head symbols by line range.
- **Removed items:** from base-only lines and the ast diff: deleted symbols,
  removed parameters/keywords, removed guards (`if`/`raise`/`assert`/early
  `return`), removed decorators.
- **Signature changes:** old and new signature per touched callable.
- **Pure refactor:** `classify.py` compares normalised asts of a touched symbol
  (formatting, docstrings and local renames normalised away). Equal means no
  behaviour change; steps 3-4 skip it.
- **Literal, ordering and comment changes:** changed string literals; statement
  sequences that moved within a function; removed comments adjacent to unchanged
  code.

Base default: `--base`, else the merge-base of HEAD with the default branch
(never `HEAD~1`).

## Review flow

```
concordance review-context [--base <ref>] [--budget 4000]
  1. view      cwd → worktree root → view (index lazily, hash-gated)
  2. base      merge-base with default branch → base view from git
  3. diff      touched symbols, removed items, signature changes, classification
  4. queries   removed-contract, sig-drift, callers, guarding tests, literals
  5. render    budgeted, whole rows, "+N more (exact|≥)", coverage footer
```

Each section is also its own command (`removed`, `sig-drift`, `touched`,
`callers`, `tests`, `literals`) for drilling down. Every command takes `--budget`
(tokens, estimated at chars/3); seeds render first and are never cut; counts say
whether they are exact or lower bounds.

### Who does what

| Step | CLI / SQL (no agent tokens) | Agent |
|---|---|---|
| 0 Orient | all | reads one budgeted block |
| 1 Removed contract | detects removed items, joins against head-view refs; each hit with its line ±2 | judges whether a hit *relies* on the removed behaviour; opens a file only if the snippet is not enough |
| 2 Signature drift | **verdict**: each call site's argument shape vs the new signature (unknown keyword, missing required, too many positional) | only `undecided` sites (`*args`, `**kwargs`, `getattr`, dynamic dispatch) |
| 3 Callers | ranked callers with call lines; skipped for pure refactors | what callers assume about changed behaviour |
| 4 Tests | guarding tests (test symbols within 2 hops), whether the diff touched them; **verdict** on test gap (behaviour changed, no guarding test) | whether a guarding test still asserts the old behaviour |
| 5 Blind spots | changed literals with other occurrences in the view, reordered statements, removed comments | what they mean (SQL order, event order, lost invariants) |

`concordance check` runs the two verdicts (BR-002, BR-005) and exits non-zero on
any; usable without an agent (pane, hook, CI).

### The procedure (`skills/review-procedure`)

Mandatory steps; each ends with a finding or "clean":

0. **Orient:** `review-context` once. Read the coverage footer: silence about an
   unparsed file is not evidence of safety.
1. **Removed contract:** every hit.
2. **Signature drift:** report CLI verdicts; judge `undecided` sites.
3. **Callers:** for each behaviour-changed touched symbol, its top callers.
4. **Guarding tests:** does any still assert the old behaviour? Report a test gap
   only when behaviour changed.
5. **What the index cannot see:** changed literals (SQL, config keys, event
   names), reordered statements or events, removed explanatory comments.
6. *(Phases 3-4)* flow/tag line; similar code that likely should have changed.

It ends with a tool log: which steps produced findings, which were clean, which
fell back to grep. The bench replay and shadow mode score that log.

### The lens (`review-panel/skills/reviewers/blast-radius.md`)

In review-panel's reviewer template. Seated for diffs with removals, signature
changes, or touched symbols with more than one caller. Techniques: change-impact,
cross-referencing.

| ID | rule | default severity | source |
|---|---|---|---|
| BR-001 | removed contract still referenced | error | CLI hit, agent judges |
| BR-002 | signature drift at a call site | error | CLI verdict |
| BR-003 | caller assumption broken by a behaviour change | warning | agent |
| BR-004 | guarding test asserts the old behaviour | warning | agent |
| BR-005 | behaviour change with no guarding test | info | CLI verdict |

### Failure handling

- Index build over its deadline (default 60 s): `review-context` says so, prints
  what it has, and names the steps to do by grep instead.
- Parse failures and timeouts are listed in the coverage footer of every answer.
- Ambiguous names return "ambiguous, did you mean: …" with candidates, never an
  empty result.
- No command blocks the agent or fails a review on its own error; `check`'s
  non-zero exit is reserved for verdicts (internal errors exit 2 with a message).

## Phases

**Phase 1 (v1):** everything above.

**Phase 2: `concordance-mod`, hook and pane, shadow first.** Starts from the Mods
Field Notes doc and the plugin-authoring skill.

- Hook: PreToolUse on symbol-shaped Grep/Read injects at most 5 lines (callers,
  tests) under a deadline; never blocks. SessionStart line: index freshness.
- Pane: touched symbols, removed-contract hits, `check` verdicts, impacted tests,
  freshness.
- **Shadow mode** (`CONCORDANCE_SHADOW=1`): computes what it would inject and
  records to `events` (session id, tool, estimated tokens, latency, payload
  symbols, would-inject), injecting nothing. Use-rate proxy: the agent Reads or
  Greps something named in the would-be payload within its next 5 tool calls.
  concordance is the one writer; chronicle reads `events` and joins it with
  session token data.
- **Gate to inject:** use rate ≥ 30% and median payload ≤ 150 tokens over a
  shadow week (both configurable).

**Phase 3: flows and domain tags.**

- Entry points auto-detected: FastAPI/Django/Flask routes, click/typer/argparse
  commands, Celery tasks, event handlers, plus decorators configured per repo.
- Tags from a repo `.concordance.toml`, e.g.
  `billing = { paths = [...], names = [...], entries = [...] }`.
- Query: reverse reachability from touched symbols to entry points and tags:
  "reaches 2 user-facing routes (`POST /refunds`, …) and 1 billing task".
- Feeds `review-context`, the pane and procedure step 6.

**Phase 4: embeddings.**

- Static token-vector table (codebase-memory-mcp's approach; nomic-embed-code
  vectors, Apache-2.0, attributed), numpy, no model runtime, no network.
- Two jobs: fuzzy "did you mean" when names miss, and the similar-code step.
- Gate: must beat the plain resolver fallback on the bench's misses.

**Phase 5: case by case.** Git co-change edges first ("these usually change
together; this time one didn't"). Then route nodes across services, cross-repo
package nodes. Communities only if the pane needs orientation. (Edge confidence
labels are already v1.)

## Testing

- **Unit, per unit**, on tiny fixture repos built in `tmp_path`.
- **Worktrees:** divergent edits in two worktrees (no leakage), a dirty file, an
  untracked file, a removed worktree (GC), concurrent indexing from two
  processes, a TS worktree without `node_modules`.
- **Resolution:** private names, re-exports, aliased imports, same-named symbols
  in Python and TS (no cross-language match).
- **Isolation:** every test pins `CLAUDE_CONFIG_DIR` into `tmp_path` (repo rule,
  CLAUDE.md "Test isolation").
- **Bench replay** as a regression suite: the 4 spike cases plus new hand-written
  regressions that keep their explaining comments (the spike's method caveat);
  baseline arm vs lens arm, Sonnet reviewers, the spike's reviewer brief output
  shape. Run on demand, not in the unit suite.

## Implementation notes (added with the plan, 2026-10-11)

Refinements found while planning; each keeps the design's intent.

1. **Layout follows repo convention:** the package is `plugins/concordance/scripts/`
   (import name `scripts`, as census/chronicle), run as
   `python <plugin>/scripts/cli.py`; tests live in `tests/concordance/`.
2. **TypeScript uses the compiler's parser per file, not the type checker.** The
   checker resolves across files, which would make a file's facts depend on other
   files and break content keying (the worktree design). Imports, re-exports and
   `tsconfig.json` `paths` are resolved by concordance at query time, as for
   Python. Calls on values (`obj.m()`) are `inferred`/`ambiguous`, as in Python.
3. **Package roots without reading `pyproject.toml`:** module names are the file
   path (minus a leading `src/`); absolute imports map to modules by dotted-path
   suffix at query time, `ambiguous` when two roots match.
4. **Pure-refactor classifier is Python-only;** touched TypeScript symbols count as
   behaviour-changed (conservative: more caller/test checks, never fewer).
5. **"Removed comment adjacent to unchanged code"** is operationalised as "a comment
   removed from a symbol that still exists in head".
6. **Schema additions:** a `guards` table (if/raise/assert per symbol) and an
   `alias_of` column on `symbols` (module-level imports and re-exports, followed by
   the resolver).

## Open risks

- The TS compiler on large repos may miss the cold-build target; mitigation is
  per-file parse caching (already content-keyed) and a TS-specific deadline.
- The removed-guard detection may over-report on large refactors; the
  pure-refactor classifier and the budget are the first defences, bench D the
  test.
- The shadow use-rate proxy is approximate; it decides injection, not review
  quality, which the bench owns.
- Budget (added after plan review): `review-context` defaults to 4000 tokens,
  drill-downs to 1500. Rendering fills in three passes (every header, then a
  first row each, then the rest in priority order) so a big early section
  cannot starve the blind-spot sections. Every query logs its cuts plus the
  diff and repo size in the events payload. The defaults are provisional: they
  are reviewed after dogfooding on the refactor work and then a full-size work
  repo, likely becoming size-aware. Bench step 4b compares 1500 against 4000.
