# review-clone

Clone a reviewer's voice and rules from their public GitHub review history. Every finding cites a real comment. The persona never invents APIs.

## What it does

`/clone-reviewer` → walks you through creating a persona from any GitHub reviewer's public comments.

`/review-as-<alias>` → review the current branch, refresh from new comments, or chat as the persona:
- no args → review the current branch
- `refresh` → pull comments since last scan, fold into rules
- `chat <question>` → ask the persona's opinion (cited or "no signal")

A review can be emitted to chat, written to a file, or **posted inline onto the open PR** — one comment per finding, each prefixed `[From <alias>]:` so the clone is never mistaken for the real reviewer. Posting always asks for confirmation first.

## Layout

`review-as` loads the persona, then reads one reference for the mode it was asked for
(`mode-review`, `mode-refresh` or `mode-chat`; `post-inline-pr` only when that output is
chosen). The collector dispatch and the slash-command render are written once, in
`references/collect-and-render.md`, and read by both `clone-reviewer` and `review-as` refresh.

## Storage

Personas are personal, portable across repos, and kept per Claude account under its config dir (`${CLAUDE_CONFIG_DIR:-~/.claude}`), never in your repo. Directories are 0700 and files 0600:

```
<config dir>/review-clone/personas/<alias>/PERSONA.md      # rules + voice
<config dir>/review-clone/personas/<alias>/raw/            # cached scrape (delete with `collect.py cleanup`)
<config dir>/review-clone/personas/<alias>/digest.jsonl    # compact corpus the extraction reads (always the full corpus)
<config dir>/review-clone/personas/<alias>/digest-new.jsonl # only the comments the last refresh added
<config dir>/review-clone/personas/<alias>/snapshot.json   # provenance, watermark, errors
<config dir>/commands/review-as-<alias>.md                 # auto-registered command
```

Personas from earlier versions under `~/.claude/review-clone/<alias>/` are still read (never written); the next refresh moves them to the new location. `/review-as-<alias>` can write a review file to `.review-clone/` in the repo: add it to `.gitignore` (the skill prints a hint and does not edit it).

## Requirements

- `gh` CLI >= 2.48 (needed for `gh api --paginate --slurp`), authenticated (`gh auth status`)
- Python 3.11+
- Repo with `origin` set (for default repo detection at clone time)

## Limits (v1)

- Window capped at 6 months
- Pre-extract gate prompts above 100 PRs or 200 comments (theme extraction reads the digest, not the raw files)
- Drift log capped at 20 entries; older entries archived to `drift.log`

## Privacy

`review-clone` derives personas from GitHub review comments. The cloned person is not notified. A disclaimer line is written into every PERSONA.md.

Private and internal repos are allowed when your `gh` login can read them (`collect.py check` verifies this first). Their raw comments and diff hunks are stored only on your machine, owner-only; the persona is marked `private_source` with a matching disclaimer, and the skill offers to delete the raw scrape afterwards (`collect.py cleanup --alias <alias>`). Later refreshes (`collect.py --incremental`) only fetch comments newer than the stored watermark and merge them in, so nothing old is lost; the watermark is held back while any PR failed. Other collector commands: `check --repo`, `digest --alias [--since]`, `cleanup --alias`; flags `--workers` (max 4), `--fresh` (ignore a checkpoint). Personas from older versions under `<config dir>/review-clone/<alias>/` are read-only and are not touched by `cleanup`; the legacy fallback never reads another account's config dir.

## Collector

`collect.py` fetches 3 PRs at a time, backs off on rate limits (`Retry-After`), records PRs that fail in the snapshot's `errors` instead of aborting, and checkpoints each PR, so an interrupted run resumes when you run the same command again.

## pip-agents

review-clone depends on [`pip-agents`](../pip-agents/README.md). The collectors run through `pip-agents:gatekeeper`: `scripts/gate.py brief-collect` builds the brief from validated values, the gatekeeper runs the one `collect.py` command and returns a result envelope with the snapshot **path and counts** (`pr_count`, `comment_count`, `error_count`, top-level integers in `snapshot.json`), and `gate.py check-collect` validates it. The corpus never passes through the session. A persona with more than 30 rules is reviewed in batches by `pip-agents:reviewer-rules` (`gate.py batches`, `gate.py review-ingest`); 30 or fewer stay inline. The validator and batch planner are vendored in `vendor/pip-agents/` (a skill cannot reach a dependency plugin's files); `python3 tools/sync_contract.py` refreshes them and `tests/agents/test_sync_contract.py` fails on drift.
