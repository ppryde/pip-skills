# almoner

One triaged view of what is asking for your attention, on the overseer
dashboard's Almoner page. Read-only against every source: nothing is sent,
marked read, resolved or edited.

## Invoke

Stdlib only — no install step:

    python3 <plugin>/scripts/cli.py <verb>

The dashboard runs it the same way, as a subprocess.

## Verbs

    almoner status                     sources, credentials, last fetch (no network)
    almoner digest --json              gather every source, then read the digest back
    almoner digest --source notion     one source, by label
    almoner digest --context work      one context
    almoner digest --hours 72          how far back to FETCH (default 48)
    almoner digest --days 30           how far back to READ (7|14|30, default 14)
    almoner digest --new               only rows not shown before
    almoner dismiss <id>               hide until it changes — local only
    almoner ack <id>                   mark actioned — local only
    almoner log --runs | --suppressed  refresh history, or what was filtered and why

## Configure (per machine, per Claude account)

Everything lives in `$CLAUDE_CONFIG_DIR/almoner/` (default `~/.claude/almoner/`):

    config.json         {"sources": [...]}
    secrets/<label>     one credential per source, chmod 600
    almoner.db          the store — caches every gather, never pruned

The plugin ships no sources: until you add one the page says "not configured".

Two overrides, mainly for tests and for running more than one instance:
`ALMONER_HOME` moves the whole directory above (default derived from
`$CLAUDE_CONFIG_DIR`); `ALMONER_DB` moves just `almoner.db` on its own.

## Notion (`type: notion`, `via: api`)

1. Create an **internal integration** at https://www.notion.so/profile/integrations
   with *Read content*, *Read comments* and *Read user information including email
   addresses*. A work workspace's admin may need to allow this.
2. Save its secret to `$CLAUDE_CONFIG_DIR/almoner/secrets/notion` and `chmod 600` it.
3. Share the pages or teamspaces you care about with the integration (page ⋯ → Connections).
   **Pages not shared with it are invisible, and invisible looks the same as quiet.**
4. Add the source, with `me` set to your Notion email (or user id) so `awaiting` can be computed:

       {"sources": [{"type": "notion", "via": "api", "label": "notion",
                     "context": "work", "me": "you@example.com"}]}

5. `almoner status` should show the source `ok: true` — that only means the secret file
   exists, not that it works. Run `almoner digest --json --hours 168` to actually prove
   access: a real digest (or a legitimately empty one) confirms the token and the shared
   pages are good; an `error` on the source means something is still wrong.

What it reads: recently edited pages and their **open** comment threads — one row per
page. Notion's API has no inbox or mentions feed, so a resolved thread is gone and an
@-mention outside a comment is not seen.

`digest` may carry `warnings` on a source alongside `ok: true` — a non-fatal
problem worth knowing about without failing the fetch. Two so far: the
50-page-per-run cap was hit (older in-window pages were not read, and the watermark
does not advance past them until a run gets under the cap), and the configured `me`
could not be resolved to a Notion user (so `awaiting` is unknown for every item this
run). `status` never fetches, so neither warning can appear there — the only warning
`status` can show is the secret file being readable by others.
