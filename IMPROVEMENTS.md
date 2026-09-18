# Improvements

Tracked improvements for pip-skills. Each entry notes the problem, the affected
component, and the proposed resolution.

---

## Language Agnosticism in Doctrines

**Status:** Open — overhaul required
**Affects:** `plugins/puritan/skills/doctrines/ddd.md` (confirmed); other doctrines not fully audited

### Problem

The DDD doctrine presents itself as a general architectural audit but is silently
Python-specific. Its violation catalog is not usable against TypeScript, Go, Java,
or any other language without a full rewrite.

Specific heresies in `ddd.md`:

- **Import detection patterns** (DDD-001–004) scan for Python import syntax:
  `from <pkg>.infrastructure`, `import sqlalchemy`, `import fastapi`, etc.
- **Framework deny-list** is Python-only: SQLAlchemy, FastAPI, Celery, aiohttp,
  httpx, requests.
- **Structural rules** reference Python-specific constructs: `__slots__`, `__eq__`,
  `__hash__`, `model_config = {"frozen": True}`, Pydantic frozen models.
- **UTC rule** (DDD-090) checks for `date.today()` and `datetime.now()` —
  Python stdlib API, not a language-agnostic temporal pattern.
- **Allowed domain imports** list is Python stdlib (`uuid`, `datetime`, `decimal`,
  `typing`, `abc`, `collections`, `re`, `json`, `os`, `copy`).

A TypeScript or Go team running `puritan:inquisition` against this doctrine would
receive false positives on legitimate code and miss real violations because none
of the detection patterns apply.

### Proposed Resolution

**Option A — Language-scoped variants**
Split language-specific doctrines at the file level:
`ddd-python.md`, `ddd-typescript.md`, `ddd-go.md`. Each shares the conceptual
rules but provides language-appropriate detection patterns. The framework
(Inquisition, config.yml) already supports referencing any doctrine file by name,
so no structural changes required.

**Option B — Language-agnostic core with per-language detection tables**
Keep a single `ddd.md` that separates *what the rule means* from *how to detect
it*. Each violation row would include a detection block per language:

```markdown
| DDD-001 | layer-boundary | Domain must not import from infrastructure | error |
  Python: `from <pkg>.infrastructure` or `import <pkg>.infrastructure` in domain/ files
  TypeScript: `import ... from '../../infrastructure'` in domain/ files
  Go: `"<module>/infrastructure"` in imports within `domain/` packages
```

**Option C — Declare language scope in the doctrine header**
If a doctrine is intentionally language-specific, it should declare this
explicitly so Inquisition can warn when applied to a non-matching codebase.
Minimal change; does not fix the detection gaps but at least makes the
assumption visible.

**Recommendation:** Option A for existing doctrines (clear separation, no
ambiguity), Option C as a mandatory header field going forward (enforced via
Scriptorium — see below).

---

## Scriptorium: Enforce Language Scope Declaration

**Status:** Done
**Affects:** `plugins/puritan/skills/scriptorium/SKILL.md`

### Change Made

Added **Language Scope** as a required header field in Step 4, with explicit
guidance in Step 6 that detection patterns must match the declared scope (no
implicit language assumptions), and two new checklist items in Step 9. New
doctrines written via Scriptorium will now be required to declare their language
scope before writing any violation rules.

---

## Skill Permission Pre-Approval

**Status:** Open — documentation / DX improvement
**Affects:** All skills (puritan, tribunal)

### Problem

Running skills like `tribunal:reckoning` requires repeated "yes" clicking for
every tool call (`gh api`, `Read`, `Edit`, etc). This friction discourages
use and slows workflows, especially for skills that make many API calls.

### Proposed Resolution

Document recommended `allowedTools` entries per skill so users can pre-approve
the tools each skill needs. Add guidance to each plugin's `README.md`.

**Tribunal (reckoning):**
```json
{
  "permissions": {
    "allow": [
      "Bash(gh:*)",
      "Read",
      "Edit"
    ]
  }
}
```

**Puritan (inquisition, covenant, scriptorium):**
```json
{
  "permissions": {
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "Edit",
      "Write"
    ]
  }
}
```

These go in `.claude/settings.local.json` (project-level, not committed) or
`~/.claude/settings.json` (user-level). Alternatively pass `--allowedTools`
on the CLI for one-off sessions.

Consider adding a "Recommended Permissions" section to each plugin's
`README.md` and/or `SKILL.md` frontmatter if Claude Code ever supports
permission declarations in skill metadata.

---

## Chronicle: Ingest Miscounts Against Real Data

**Status:** Open — fix first, ahead of every other chronicle item
**Affects:** `plugins/chronicle/scripts/ingest.py`, `plugins/chronicle/scripts/transcript.py`,
`plugins/chronicle/scripts/report.py`

Found by porting chronicle into another repo and running it against a real
transcript tree. These are the items that make the *stored numbers wrong*, which
is why they come first: every other entry below is ergonomics or packaging, and
a fast CLI over inflated data is worse than a slow one over true data.

### Problem

1. **Resumed and forked sessions double count.** A resumed transcript repeats the
   parent session's records verbatim. `turns` is keyed
   `(session_id, agent_id, message_id)`, so the same message id arriving under a
   new session id inserts a *second* row rather than colliding. The same holds
   for `tool_calls`, `events`, `file_edits` and `artifacts`. Every total that
   aggregates across sessions — the summary, per-day series, cost — is inflated
   by however much of the parent the child repeated.
2. **Failed Artifact publishes are recorded.** `transcript._artifact_use` never
   consults the tool result's `is_error`, so a publish that published nothing
   still becomes an `artifacts` row and is counted.
3. **One artifact published from several sessions counts several times.**
   `ingest.rollup`'s redeploy detection is scoped `WHERE session_id = ?`, so
   cross-session republishes of the same URL are distinct pages as far as the
   store is concerned.
4. **Impossible turn durations.** `turn_duration` events take the transcript's
   `durationMs` at face value; a record written after a long gap yields a
   duration no turn could have taken, which then flows into `active_ms`.
5. **Trends are not clipped to the selected window.** To be confirmed against
   `report.py`'s series builders before changing anything.

### Proposed Resolution

Skip any turn, tool call, event, result, file edit or artifact whose id already
belongs to *another* session; cap a turn duration at the time elapsed since the
turn began; consult `is_error` before recording an artifact; dedupe artifacts by
URL across sessions rather than within one; clip each series to the window.

Port the covering tests from the other repo's suite along with the fixes rather
than filing them as separate work — they are what proved these five.

---

## Chronicle: Two Error Contracts In One CLI

**Status:** Open — cheap, do it alongside the ingest fixes
**Affects:** `plugins/chronicle/scripts/cli.py`

### Problem

`cmd_session`, `cmd_agent` and `cmd_ingest` print bare text to stderr
(`chronicle: no session X`) and exit 1. `cmd_pull_volume` prints
`{"error": ...}` and distinguishes invalid input (2) from runtime failure (1).
Same binary, two contracts, so every caller needs both parsers.

### Proposed Resolution

One contract: success prints a single JSON object to stdout; failure prints
`{"error": ...}` to stderr and exits **2** for invalid input, **1** for a runtime
failure or a thing not found.

---

## Chronicle: Most Sessions Have No Account

**Status:** Open
**Affects:** `plugins/chronicle/scripts/ingest.py`, `plugins/chronicle/scripts/store.py`

### Problem

Only `owner_account_uuid` is recorded, and only for sessions bridged from
claude.ai. Chronicle's own README records the consequence: 75 of 342 sessions on
this machine were unattributable to any account. The plan columns are already
stamped per session from `.claude.json` at ingest; the account uuid beside them
is not.

### Proposed Resolution

Write `account_uuid` on every session from the ingesting config dir's profile,
**write-once**, with the same discipline as the plan snapshot — a later
`sync --full` must not relabel history. `owner_account_uuid` keeps its present
meaning (what the bridge record literally says) and is not merged into it.

---

## Chronicle: Telling Accounts Apart Without Storing An Email

**Status:** Decided — the upstream change is deliberately **not** adopted
**Affects:** `plugins/chronicle/scripts/store.py` (`ACCOUNT_IDENTITY_FIELDS`)

### Problem

The ported version stores `emailAddress` so its UI can label accounts, reversing
this repo's no-email rule on purpose and flagging it for a decision. The need is
real — `accountUuid` alone is not a label a person can read.

### Resolution

Keep the rule. `ACCOUNT_IDENTITY_FIELDS` is a whitelist precisely so a personal
field added upstream cannot leak by default, and this store is served by the
dashboard and copied between machines; an email is the one field that makes a
leaked copy identify a person.

Meet the UI's actual need instead: a short `account_uuid` prefix plus plan
distinguishes accounts on sight, and a local nickname
(`chronicle accounts label <uuid> "personal"`) held in config — *not* in the
database — gives a proper name to anyone who wants one.

---

## Chronicle: Docker Volumes Should Be Read In Place

**Status:** Open — own card; too large to ride along with the ingest fixes
**Affects:** `plugins/chronicle/scripts/cli.py` (`pull-volume`),
`plugins/chronicle/scripts/ingest.py`, `plugins/chronicle/README.md`

### Problem

`pull-volume` copies a named volume's transcripts onto the host with
`cp -au` in a root helper container. On Linux there is no uid remapping, so a
`0600` root-owned transcript lands unreadable by whoever runs `sync`, which skips
it *silently*. The plugin currently carries a whole apparatus to cope: an
`unreadable` count, a `warning` naming two remedies, a `--user` flag suggestion,
and several paragraphs of README.

### Proposed Resolution

Read the volume in place through short-lived read-only helper containers
(`docker run --rm -v vol:/v:ro`): one lists the transcripts, another reads only
the bytes appended since the last sync. Nothing is copied to the host, so the
ownership failure mode cannot occur and the entire apparatus above is deleted
rather than documented.

Requires teaching `sync`/`cursors` that a transcript source is not always a host
path, and porting the fake-Docker tests. Sync must keep working when Docker is
down: local transcripts still sync, and the volume is reported under
`unavailable`. `volumes add` checks the volume exists before saving it, with
`--claude-dir` for where the config dir sits inside it (default `.config/claude`).

---

## Chronicle: Standalone In Name, Overseer-Configured In Practice

**Status:** Open
**Affects:** `plugins/chronicle/scripts/cli.py`, `plugins/chronicle/scripts/store.py`,
`plugins/chronicle/README.md`

### Problem

Chronicle states that it stands alone — it keeps its own small config loader
rather than importing overseer's — and then instructs the user to run
`overseer claude-dirs add` and to hand-edit `path_map` into overseer's JSON. A
chronicle installed without overseer has no supported way to configure either.

### Proposed Resolution

Chronicle's own verbs over the same file: `dirs add|list|rm`,
`path-map add|list|rm` (and `volumes add|list|rm` when the entry above lands).
Configuration by command, not by editing JSON. Also read `~/.claude` in addition
to the active `CLAUDE_CONFIG_DIR`, so setting up a second account elsewhere stops
hiding the default one.

---

## Chronicle: Store Resolution Is Clever

**Status:** Open — needs a migration path, not just a changed function
**Affects:** `plugins/chronicle/scripts/store.py` (`db_path`)

### Problem

`db_path` picks the **fullest** existing store across the watched config dirs.
It was the right answer to a real bug (a second account raising a rival store,
342 sessions against a stale 238), but it means the file you are writing to is
computed, not stated, and `chronicle status` exists partly to tell you which one
you got.

### Proposed Resolution

One store per machine at a fixed location, whichever config dir is active, with
an env override to move it (the ported version uses `~/.claude/.context-ui/` and
`CONTEXT_UI_HOME`; here it would stay under a chronicle-named directory).

This cannot be a straight swap: there is live data in more than one store on this
machine. It needs a migration that merges the existing stores into the chosen one
— every fact table is idempotent and keyed by transcript-native ids, so a merge
converges — and it must be safe to run twice.

---

## Chronicle: Report And Summary Additions

**Status:** Open — additive, no migration
**Affects:** `plugins/chronicle/scripts/report.py`, `plugins/chronicle/scripts/cli.py`

### Problem

Filtering is `--days` and `--root` only, so a closed window (a specific past
fortnight) cannot be asked for, and neither can one account's sessions. The
summary carries no basis for comparison.

### Proposed Resolution

Add `--until` beside `--days`, and `--account`. Add to the summary:
previous-period totals for comparison, churn ratios, and the lists of branches,
accounts and plans present. Extend agent detail with attribution, prompts,
compactions and biggest context jumps — confirm which of these `agent_detail`
already returns before writing any of it.

---

## Chronicle: Insights In TypeScript, Where A Standalone Chronicle Cannot Reach Them

**Status:** Open — blocked on the shared-dashboard spec, deliberately
**Affects:** `plugins/overseer/dashboard/frontend/src/board/chronicle/insights.ts`,
`docs/superpowers/specs/` (the shared-dashboard design, commit `b6747b0`)

### Problem

Window fill, cost per turn by model, cost per prompt, thinking share, rework
share and delegation balance — each with a band and suggested fixes — are
computed in the overseer dashboard's frontend. A chronicle installed on its own
has no counsel at all, and a CLI user cannot get one either.

The ported version solves this by moving the lot into Python (`insights.py`) and
shipping its own no-build Preact frontend. **The frontend half is not adopted
here:** this repo already has a spec (`b6747b0`) for extracting *one* dashboard
vendored into both plugins, so a second UI would mean two to keep in step. The
ported version's network serving (`--host` plus a token in an HttpOnly cookie) is
also skipped — it is due to be removed upstream before release, and loopback-only
is the right shape.

### Proposed Resolution

Move insights into Python as part of the shared-dashboard extraction, with the
frontend reduced to display. Not before: doing it ad hoc leaves the same bands
implemented twice for however long the interval lasts.

---

## Overseer: `show` And `board` Print Headings With No Bodies

**Status:** Open — the single biggest friction in using the CLI
**Affects:** `plugins/overseer/scripts/cli.py`

### Problem

`overseer show <id>` emits `## Goal`, `## Plan`, `## Decisions` and so on with
empty bodies. Confirmed still broken in 0.24.0, the newest version cached on this
machine, so it is not already fixed upstream. `--json` is the only way to read a
card, which makes every read cost a JSON parse.

`board` has the same defect from the other direction: its only non-JSON output is
a count (`65 cards, 1 sprints`). `board --help` offers `[--json]` and nothing
else — no stage filter, no readiness filter. With 65 cards, `resume` dumps a flat
27-line list and `board` tells you a number; neither answers "what should I pick
up".

### Proposed Resolution

Render the section bodies in `show`'s human output. Give `board` a real listing
with stage and readiness filters, so the non-JSON path is the one a person would
actually choose.

---

## Overseer: No Verb Appends To A Card Body

**Status:** Open — fix first among the overseer items; this one loses data
**Affects:** `plugins/overseer/scripts/cli.py`, `plugins/overseer/skills/ledger/SKILL.md`

### Problem

The ledger skill's own documentation admits there is no CLI verb to append to a
card body. So writing a line to `## Decisions` means reading the whole body as
JSON, appending, and writing it all back — and the failure mode of a
read-modify-write round trip is silent content loss. That is a data-integrity
footgun, not an ergonomic complaint, which is what puts it ahead of the entry
above despite being less visible.

### Proposed Resolution

An append verb that takes a card, a section and text, and appends server-side
without the caller ever holding the whole body. Update the ledger skill's docs in
the same change.

---

## Overseer: A Bare `ModuleNotFoundError` Reads As A Broken Install

**Status:** Open
**Affects:** `plugins/overseer/scripts/cli.py`

### Problem

Run from the wrong directory, the CLI dies on
`ModuleNotFoundError: No module named 'yaml'`. Poetry resolving its environment
from the current working directory is not this repo's bug, but the bare traceback
is: it has now bitten twice in two different disguises, and both times it read as
a broken plugin install rather than as a shell in the wrong place.

### Proposed Resolution

Catch the import and say what it means: overseer needs PyYAML, and in a Poetry
project it must be run from the project root under `poetry run`. Diagnose the
environment, do not attempt to work around how Poetry picks one.
