---
name: chronicle-reconcile
description: >
  Ad-hoc audit of the chronicle store against reality: why do chronicle's totals not match the
  Anthropic console, where is usage missing, is anything double counted or on the wrong account,
  are the rates right. Use when the user says the chronicle/dashboard cost "doesn't match the
  console", asks "where is the missing usage", "which sources are we reading", "are we
  double counting", "is this on the right account", wants to add a container/remote box/backup as
  a source, or wants transcripts and the store backed up. Manual, read-only first. It is a
  runbook the user invokes on purpose; nothing here runs from the dashboard's Sync button or
  from `chronicle sync`.
---

# Reconciling chronicle with the console

Chronicle's number is `tokens x list price`, read from transcripts on disk. The console's number is
what Anthropic billed. They differ for a small set of reasons, and this skill walks them in the order
that cost the least to check. Run it by hand; it is deliberately not part of any sync.

Define the CLI once, relative to this skill (`skills/reconcile/` sits two levels under the plugin
root): `CLI=<plugin root>/scripts/cli.py`, and run every command as `python3.11 "$CLI" <verb>` (every
verb prints JSON; chronicle needs Python >= 3.10). Use the checkout that has the merged code; an old
checkout silently gives old numbers. Read the store with `file:<db>?mode=ro`. Always compare per
account and per day. The console's days are UTC; chronicle's `by_day` buckets use LOCAL time, so a
turn near midnight lands on different days and the skew is not bounded by "a few dollars". For a
like-for-like daily comparison use the UTC variant in `references/queries.md`.

## Ground rules

1. **Snapshot before you write.** Copy the store first (`sqlite3` backup API, not `cp`, the store is
   WAL) into an archive folder:
   ```python
   import sqlite3
   src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); dst = sqlite3.connect(COPY)
   src.backup(dst); print(dst.execute("PRAGMA integrity_check").fetchone()[0])  # expect "ok"
   dst.close(); src.close()
   ```
   Do every experiment on a COPY with a scratch config dir, and keep `sync` away from the network and
   other sources: `env -u CLAUDE_CONFIG_DIRS CLAUDE_CONFIG_DIR=$SCRATCH CHRONICLE_DB=$COPY
   CHRONICLE_NO_REMOTES=1 CHRONICLE_NO_PRICING_REFRESH=1 python3.11 "$CLI" ...` (`sync` otherwise
   honours `CLAUDE_CONFIG_DIRS`, configured remotes and volumes, and the daily price refresh). Touch
   the real store only for a step you have already proved on the copy.
2. **Never delete or rebuild the store.** Claude Code prunes old transcripts and chronicle keeps the
   rows it already ingested, so some sessions exist ONLY in the store (174 of them on the author's
   machine, 54k turns). Count them first (`references/queries.md`, "DB-only sessions") and keep a
   copy of them in the archive.
3. **Read-only until told.** Docker volumes are read with `:ro`, remote boxes only through the
   redacting `remotes` transport, transcripts are copied not moved. Never point a tool at a
   production-access host without the user configuring it (`chronicle remotes add` is the standing
   authorization; an agent must not open ssh to `*.wayflyer.team` on its own).
4. **Verify claims yourself.** Re-run the tests and re-measure on a copy before merging what a
   subagent reports. (This caught a >200 s query regression once.)

## The checks, cheapest first

### 0. Frame the gap
Get the console figure for the same account and window (Claude Code product only, UTC) and,
ideally, its daily bars and per-model split. Compute chronicle's for the same window with
`python3.11 "$CLI" summary --account <uuid> --since <ISO>` (the `since` value must be ISO-8601, not an
epoch; the dashboard's `GET /api/chronicle/summary` returns the same JSON). Spend IN the window is
`sum(by_day[*].cost_usd)`: the window selects sessions, so `totals` and `by_model` are whole-session sums
and over-count sessions that began before the window. The rest of the skill is explaining that difference.

### 1. Are the sources all being read?
List what chronicle reads: `claude_dirs`, `volumes`, `remotes` and `path_map` in
`<primary config>/overseer/config.json` (the primary is `$CLAUDE_CONFIG_DIR`; note that a
`path_map` in a different account's config is NOT applied, which once left container sessions with
no repo). Then look for usage that lives elsewhere:
- host config dirs (`~/.claude*`) and their newest transcript date (a stale copy stops growing);
- Docker named volumes (`docker volume ls`; which container sets `CLAUDE_CONFIG_DIR`);
- other machines: cloud dev/prod-access boxes reached over ssh (`~/.ssh/config`), each with its own
  `/opt/wf-state`; these were the largest missing source (see `chronicle remotes`);
- Claude Desktop local agent / Cowork sessions
  (`~/Library/Application Support/Claude/local-agent-mode-sessions/<account>/<org>/local_*/.claude/`);
- Claude Code on the web or mobile leaves NO local transcript at all: only the console sees it.
A source you cannot read is a gap you can only bound, not close.

### 2. Is each session on the right account?
Chronicle takes a session's account from `<config_dir>/.claude.json` (`oauthAccount`) at ingest, and a
per-turn override from `bridge-session` records (`ownerAccountUuid`). Check `references/queries.md`
"Account cross-tab": sessions with no account, sessions whose bridge owner differs from the config-dir
account, and the cost sitting in that disagreement. Transcripts rarely carry an account id
(only recent versions, only bridged or artifact sessions), so backups need a whitelisted
`.claude.json` next to them (the file lives BESIDE the dir for a default `~/.claude`, not inside it).
Caveats: the account stamped is the CURRENT login of that config dir at ingest time, and
`backfill_account_uuids` fills NULL rows from that same login later, so a config dir that has switched
accounts relabels its old sessions. A default `~/.claude` install keeps its `.claude.json` BESIDE the
dir (`~/.claude.json`), which chronicle does not read, so its sessions can have no account at all.
A bridge owner is the account that owns the claude.ai bridge, not necessarily the billed account;
when the transcript cannot settle it, say so and ask the user what they were signed in as.

### 3. Is anything counted twice?
A resumed agent re-writes its whole history into a NEW agent file, so one API call can sit in dozens
of snapshot files. Chronicle counts one call once per session (`chronicle dedupe`, dry-run first, then
`--apply`, which is transactional and idempotent). Measure with `references/queries.md` "Duplicate
groups"; expect it to matter on agent-team sessions and to be ~0 elsewhere. It inflated one account by
~$14k of $31k before the fix.

### 4. Are the rates right for the date?
`chronicle pricing status` (rows, `pricing_as_of`, last refresh) and `pricing refresh --dry-run`
(compares the live pricing page with the store; writes nothing). Claude Code's own `cost-state`
transcript records are a useful cross-check where present (they are periodic snapshots, so long sessions
lag) but are NOT a ledger and chronicle deliberately does not use them.
Unknown model ids show as unpriced; a prefix match can silently price a new model at its parent's rate.
Chronicle prices every turn at the standard list rate: it does not model fast-mode, regional-inference,
long-context or tool-fee premiums. On an expensive day with a uniform shortfall, check
`usage.speed` / `usage.inference_geo` in the transcripts before blaming the rate table.

### 5. Compare per day and per model
Line the console's daily bars up against chronicle's `by_day` for the account (`references/queries.md`
"Daily comparison"). A steady daily shortfall on days with no attribution ambiguity means missing
usage (check 1); a shortfall confined to days with bridged sessions is an attribution question (check
2); a uniform percentage on every clean day would be price arithmetic (check 4). The per-model split
narrows which kind of workload is missing.

### 6. What did the expensive sessions do?
Rank sessions by de-duplicated cost with their per-account split, then read the first prompt, the last
prompt, tool mix and subagent types for the top few (`references/queries.md` "Top sessions"). Cost is
dominated by cache reads on very long contexts (near the window limit), so the pattern to look for is
marathon sessions, not one huge call.

## Backing things up

- **Transcripts:** copy `projects/` (main + `subagents/`) from every source into one archive folder, one
  sub-folder per source with a README naming where each came from; keep file mtimes; verify counts
  match; do not copy the full `.claude.json` (it holds an email), write a whitelisted one instead
  (`store.parse_account_profile`).
- **The store:** full snapshot before any write, plus a stripped copy that keeps only the sessions whose
  transcripts exist nowhere else. Record the ids.
- **Remote boxes:** the `remotes` mirror is an append-only, redacted usage backup (no prompts, no tool
  content). It is a usage record, not a substitute for the raw transcripts.

## Making a source permanent (after the check proved it)

Add it to the primary config, then sync once: a new `claude_dirs` entry (archive folders shaped
`<dir>/projects`), `chronicle volumes add <volume>` for a Docker volume, or
`chronicle remotes add <name> <ssh-host> --mirror-dir <path>` then `remotes probe` and
`remotes sync --dry-run`. Back the config file up first. Re-running is idempotent: the same session
arriving from two places converges, only its source label changes (last reader wins).

## Report what you found

Finish with a short table: what was wrong, dollars moved, what remains unexplained and why, and the one
next action. Say plainly when a number is an upper bound or an inference (a bridge owner, an
`effective_from` on a price row, an archive-backed date). Do not present a coincidence as a match.
