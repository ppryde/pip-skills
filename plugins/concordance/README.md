# concordance

**Status: experimental.** The phase-1 bench (7 seeded review cases) showed no catch-rate lift
over a plain Read/Grep reviewer, and about 9% more tokens per review (the review-context
output is additive). The bench cases were too easy to show lift; real-world trials on large
repos are pending.

An owned symbol index for review, in Python and TypeScript. A concordance is the index of
every place a word appears in scripture; this is that, for symbols.

It answers exact questions about a diff, in the CLI, at zero agent tokens:

- **What still relies on what the diff removed?** Deleted symbols, removed parameters, guards
  and decorators, against every remaining reference: one row per removed symbol or function,
  its still-relying sites listed once with an exact count.
- **Which call sites no longer match a changed signature?** A verdict, not a hint (BR-002),
  for calls it can prove; calls it cannot prove are listed as undecided for the reviewer.
- **Who calls the changed code, and which tests reach it?** With a pure-refactor classifier,
  so refactors are not reviewed as behaviour changes. Behaviour changes no test reaches are a
  verdict (BR-005).
- **What can't an index see?** Changed literals (SQL, keys, event names) with their other
  occurrences, reordered statements, removed comments.

The `review-procedure` skill tells a reviewer exactly when to use each answer; review-panel's
`blast-radius` lens runs it.

## Use

```bash
python plugins/concordance/scripts/cli.py review-context [--base REF] [--budget 4000]
python plugins/concordance/scripts/cli.py check            # verdicts only; exit 1 on any
python plugins/concordance/scripts/cli.py callers NAME     # did-you-mean on a miss
python plugins/concordance/scripts/cli.py tests NAME [--hops 2]
python plugins/concordance/scripts/cli.py removed | sig-drift | literals | touched | coverage | index
python plugins/concordance/scripts/cli.py setup-ts         # once, for TypeScript
python plugins/concordance/scripts/cli.py stats [--days 30] [--repo this|all] [--json]
```

The base defaults to the merge-base with the default branch. The index builds lazily on first
use and only re-parses files whose content changed. `--budget` caps output size (default 4000
for `review-context`, 1500 for the other commands).

## Usage log

Every query appends one row to `$CLAUDE_CONFIG_DIR/concordance/usage.db` (override:
`CONCORDANCE_USAGE_DB`): command, repo, latency, tokens returned, budget cuts, diff size and
verdicts. Reviews add one `record-review` row with their findings. The log is kept for good and
is separate from the per-repo index caches, so deleting an index loses no history. `stats`
reports usage, budget pressure by diff size and effectiveness; `--json` is for chronicle.

## Measuring it: replay

`concordance replay --session <id>` reads a finished session's transcripts in memory and, for
each covered tool call, asks the real CLI what concordance would have returned. It stores one
row per call: actual tokens, concordance tokens, CLI latency, whether the answer would have
been enough (yes / no / unknown; judged only on the callers shown within the budget) and
whether the file has changed since (drifted). Rows hold
numbers and labels only; nothing from the transcript is stored. A session idle for under 15
minutes is refused (exit 2) unless `--force`; replaying again replaces that session's rows.
Today's estimators cover whole-repo, unfiltered bare-identifier Greps (callers), the agent's own
concordance calls (passthrough) and Read drift (exact reconstruction; unknown on doubt).
`concordance stats --replay` summarises the rows honestly: a call concordance would not have
answered counts at its actual tokens (no saving), and the totals are split by answerable; only
`yes` is a believable saving. It also counts uncovered calls; sessions whose replay failed or is
pending are visible in `chronicle concordance`. Replay's own CLI calls are tagged
`CONCORDANCE_ORIGIN=replay`, left out of usage stats, and logged as numbers only. `concordance mode inject|shadow
[--session ID]` sets the delivery mode (pure shadow by default; it never blocks or rewrites an
agent tool, and inject-mode hooks arrive later). Every query command takes `--json`.

## Worktrees

One store per repo (keyed by the git common dir) under
`$CLAUDE_CONFIG_DIR/concordance/`, shared by every worktree. Facts are keyed by file content,
so a new worktree parses only what differs. Each worktree gets its own view, including
uncommitted edits; answers never mention another worktree's paths. Removed worktrees are
garbage-collected lazily. Nothing is written into the repo.

## Requirements

Python 3.11+ (stdlib only). TypeScript needs Node 18+ and `setup-ts`, which installs the
pinned `typescript` 5.6.3 from the committed lockfile with install scripts disabled. Without
it, TypeScript files are reported as not indexed; nothing fails.

## Credits

Ideas borrowed, no code copied: code-review-graph (MIT), graphify (Apache-2.0),
codebase-memory-mcp (MIT), GitNexus (ideas only).
