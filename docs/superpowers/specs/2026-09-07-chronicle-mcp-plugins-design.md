# Chronicle: MCP and plugin usage, aggregated and per session

**Date:** 2026-09-07
**Status:** approved, ready for implementation planning
**Touches:** `plugins/chronicle/scripts/{transcript,store,report}.py`,
`plugins/overseer/dashboard/frontend/src/components/chronicle/*`

## Problem

The Chronicle page has one "Tool calls" panel: the top 20 tool names by call
count. Bash, Read and Edit account for ~90% of all calls, so MCP traffic is
never visible in it, and plugin usage is not visible at all.

Two questions cannot be answered today:

1. **What is MCP costing me, and from where?** The store holds 2,488 MCP calls
   across 51 sessions and 18 distinct servers, but they are drowned in a shared
   top-20 list and undifferentiated by provenance.
2. **Which of my plugins do I actually use?** Not answerable at any price from
   the current store — see "The discarded field" below.

Both are wanted in two places: aggregated for the current view (with its repo,
days and branch filters applied), and per session in the drawer.

## The discarded field

Claude Code already writes the plugin identity into the transcript. A skill
invocation appears as:

```json
{ "type": "tool_use", "id": "toolu_01WSb6…", "name": "Skill",
  "input": { "skill": "tribunal:reckoning", "args": "355" } }
```

`transcript._fold_assistant` reads this block and keeps only `(id, name)`. It
opens `input` for exactly one tool — `Artifact` — and discards it for every
other. The same is true of `Agent`, whose `subagent_type` names the plugin
supplying the agent definition.

So the data is neither derived nor newly emitted: it is present on disk and
dropped at ingest. This spec keeps it.

## Data available today

| Signal | Where | Status |
|---|---|---|
| MCP server + tool | `tool_calls.tool_name` (`mcp__<server>__<tool>`) | present, indexed |
| Context cost of a call | `tool_calls.result_chars` | present |
| Plugin skill name | transcript `input.skill` | **discarded at ingest** |
| Subagent type | transcript `input.subagent_type` | **discarded at ingest** |

Observed server shapes, from the live store:

```
plugin_playwright_playwright      1621 calls   17 tools    plugin
claude-in-chrome                   303 calls   10 tools    local
claude_ai_Snowflake                199 calls    2 tools    connector
plugin_linear_linear               137 calls   12 tools    plugin
wayflyer-dev                        11 calls    1 tool     local
```

## Design

### 1. Store: one `qualifier` column

Add `("tool_calls", "qualifier", "TEXT")` to `store._MIGRATIONS`. Nullable,
filled only for an allowlist of tools whose identity is a short bounded
string:

| Tool | Qualifier source |
|---|---|
| `Skill` | `input.skill` (e.g. `tribunal:reckoning`) |
| `Agent` | `input.subagent_type` (e.g. `claude-code-guide`) |

Null for everything else.

**Why an allowlist and not the whole input.** The transcripts are the durable
record; chronicle is a re-derivable projection over them. Copying arbitrary
inputs in — `Agent`'s full delegated prompt, `Write`'s file bodies — would turn
a facts table into a second, unmanaged copy of the conversation, at odds with
the store's existing discipline of counts and ids. Widening the allowlist later
costs one migration plus a re-sync, so nothing is foreclosed.

**Rejected alternatives.** A dedicated `skill_calls` table (as `artifacts`
has): `artifacts` earns its table by carrying five fields plus page-identity
logic; a table holding one string per row, joined back on every read, is
ceremony. Storing the full input JSON: see above.

### 2. Ingest: keep the qualifier

`transcript.Turn.tool_uses` becomes `(tool_use_id, name, qualifier)`.
`_fold_assistant` extracts the qualifier via a small
`_qualifier(name, input)` helper driven by the allowlist table. `ingest`
writes it through the existing `INSERT OR REPLACE` on
`(session_id, tool_use_id)`, so a re-fold converges rather than duplicating.

### 3. Backfill

None to build: `ingest.sync(full=True)` already deletes every cursor and
re-reads each transcript from byte 0, and all writes are idempotent by
design. `chronicle sync --full` populates the column for all 216 historical
sessions.

Until an operator runs it, MCP figures are correct (they derive from
`tool_name`, which was never dropped) and plugin *skill* rows are empty. Both
panels therefore need an empty state that names the re-sync, rather than
rendering a bare zero that reads as "you use no plugins".

### 4. Classification — one function, one source of truth

A pure `report.classify(tool_name, qualifier)` used by every read path:

- `tool_name` starting `mcp__` → **MCP**. Split on `__`: segment 1 is the
  server, the remainder rejoined is the tool. Provenance from the server name:
  `plugin_*` → `plugin`, `claude_ai_*` → `connector`, else `local`. A name that
  does not split cleanly falls back to the raw string — never dropped.
- `Skill`/`Agent` with a qualifier containing `:` → **plugin**, the part before
  the colon naming the plugin.
- An unqualified skill (`code-review`, `dataviz`) is built-in: counted, but not
  attributed to any plugin.
- Everything else is neither, and appears in neither box.

**Deliberate overlap.** A plugin-provided MCP server counts in *both* boxes:
playwright's 1,621 calls appear under MCP's `plugin` provenance and again as
the playwright plugin's usage. The boxes answer different questions — "what is
MCP costing me" versus "which plugins do I use" — and each states its scope in
its subtitle so the totals never read as double-counting.

### 5. Report: two blocks, two verbs

`summary()` and `session_detail()` each gain `mcp` and `plugins`, derived from
the `tool_calls` rows they already scan. Shape:

```json
{ "mcp": { "calls": 2488, "sessions": 51, "result_chars": 13800000,
           "by_provenance": { "plugin": 1764, "connector": 400, "local": 324 },
           "servers": [ { "server": "...", "provenance": "plugin",
                          "tools": 17, "calls": 1621, "sessions": 3,
                          "result_chars": 2105000 } ],
           "tools":   [ { "server": "...", "tool": "browser_evaluate",
                          "calls": 504, "sessions": 14, "result_chars": 604565 } ] },
  "plugins": { "calls": 1819, "sessions": 62,
               "items": [ { "plugin": "playwright", "kind": "mcp",
                            "calls": 1621, "sessions": 3 },
                          { "plugin": "tribunal", "kind": "skill",
                            "calls": 18, "sessions": 9 } ] } }
```

`sessions` counts are omitted from the `session_detail` variant, where they are
always 1.

No new endpoint and no new fetch: both surfaces already call the verb that now
carries the data.

### 6. Frontend

One presentational component — rows, title, subtitle, empty state — rendering
through the existing `BarList`, mounted at both call sites:

- **`ChroniclePage`**: two `chr-panel` sections beside the existing "Tool
  calls" panel, plus two `StatTile`s ("MCP calls", "Plugin calls") in the tile
  row. Repo/days/branch filtering comes free, since the data rides `summary`.
- **`SessionDrawer`**: two sections following the existing "Tools" panel, from
  the `session` detail payload.

`api/types.ts` gains the two block types, shared by both.

## Testing

Per the repo's isolation rule, every test pins `CHRONICLE_DB` and
`CLAUDE_CONFIG_DIR` into `tmp_path` before running — never the developer's real
store.

- **`classify`** carries the bulk: table-driven over the real server names in
  the live store (`plugin_playwright_playwright`, `claude-in-chrome`,
  `claude_ai_Snowflake`, `wayflyer-dev`), qualified and unqualified skills, and
  the malformed-name fallback.
- **`transcript`**: the qualifier is captured for `Skill` and `Agent`, is null
  for other tools, and a second fold of the same lines does not duplicate.
- **`report`**: both blocks present and correctly aggregated in `summary` and
  `session_detail`, including the deliberate overlap.
- **components**: both mount points render rows, and both show the empty state
  rather than a zero when the column is unbackfilled.

## Out of scope

**Context composition.** The store holds context *provenance* per turn —
`input` / `cache_read` / `cache_creation` (split 5m/1h) / `output` /
`thinking`, plus `peak_context_tokens` — which says how much of a prompt was
fresh versus cached, not what occupied it. Nothing records the system prompt,
tool-definition schema overhead, or injected skills. The nearest honest
approximation is attribution by `result_chars` (characters, not tokens, at
roughly 3.7:1), which `report.biggest_jumps` already does per session. A true
composition breakdown needs new ingest work and belongs to its own card.
