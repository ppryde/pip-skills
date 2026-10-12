# Backup and restore

The live `board.db` and state root are never committed. `backup`/`restore`
are the bridge to git — a diffable, mergeable snapshot in the repo.

- `backup [--dir PATH]` dumps every table to JSON into `.overseer/backups/`
  (or `--dir`), atomically. Run it before a merge or a push you want a safety net for.
- `restore [--dir PATH]` rebuilds the central state root from a backup: cards
  upsert by id with last-modified-wins, board-identity meta (`repo_root`,
  `schema_version`) is never overwritten, and sprints, facts and `usage.jsonl`
  are restored only where absent (fill-gaps, never clobbers). Refuses loudly on
  an unknown schema or bad JSON.
- `restore --from-bak FILE` puts back the pre-0.27.0 `board.db.pre-v2.*.bak`.
- A repo that has run `init` gets an opt-in `PreToolUse` hook that runs
  `backup` and commits `.overseer/backups/` before a Claude-issued `git push`
  proceeds, so the push carries the snapshot.
