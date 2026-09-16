# Almoner: one triaged view of what is asking for your attention

**Date:** 2026-09-13
**Plugins:** `almoner` (new), `overseer` (dashboard page, backend routes)
**Status:** CLI core + Notion source built (plan 2026-09-15-almoner-cli-core-notion);
Slack, Linear and mail adapters, the judging skill and POST /dismiss unbuilt.

**Revised 2026-09-13 (second pass).** The day table replaced the grouped view
as the primary surface; rollups and their safety rule were added; the mail
deep-link question was answered. Those three had been living in code comments
and are folded in here.

## Problem

Work arrives through several systems at once — mail, Linear, Slack — and each
one only knows about itself. Triage therefore happens by hand, by visiting
each in turn, which means it happens either too often (interrupting) or not
often enough (missing things).

A daily cloud-scheduled mail triage already exists and is a different product:
it runs unattended at 08:00, pushes to a phone, needs no laptop, and is bound
to **one** mailbox because a hosted connector holds one OAuth grant. That last
limit is structural — it can never see a second inbox, nor Linear, nor Slack.
Fetching locally turns that hard limit into a config key.

## Goal

One page on the overseer dashboard, beside the Chronicle. Press **Gather**;
every configured source is read, deduplicated and ranked, then laid out as the
day actually happened — merged across sources rather than split by them.
Read-only against every remote system: nothing is sent, replied to, marked
read, archived, assigned or resolved.

## Architecture

Almoner is a fourth instance of a pattern the repo already runs three times,
for `census`, `vigil` and `chronicle`: a sibling plugin resolved by
`find_plugin`, with every route soft-degrading rather than erroring.

```
Almoner page ──► GET /api/almoner/digest
                    └─► almoner digest --json         (soft dependency)
                          └─► for each source, in parallel and independently:
                                adapter.fetch(window) -> list[Item]
```

A source that is unreachable, unauthorised or slow degrades to an unavailable
marker and is **named in the UI**; it never fails the digest. A silently short
digest is worse than a visible error, because an empty list reads as "nothing
needs you" either way.

### The transport seam

The single most important constraint on this design: **it must be trivial to
swap how a source is reached.** A headless agent is not a rival architecture —
it is one implementation of the adapter interface.

```
adapter.fetch(window) -> list[Item]     # the ONLY contract
      ├── slack:agent   claude -p, connector-backed   ← today
      ├── slack:api     user token, direct            ← when a token exists
      ├── mail:imap     app password                  ← when settled
      └── notion:api    integration token             ← when authorised
```

**Notion** is a source, and its grain is the **page**, not the comment: a
thread of comments on one document is one thing to deal with, which is the
same collapse Slack forced, arrived at from a different direction. It is
currently unreachable rather than unbuilt — the connector exposes only its
authorisation call — and the page therefore names it among the sources it
could not reach, which is what an unreachable source is supposed to look like.

Notion turns out not to need the connector at all: it is reachable directly by
an internal integration token (`via: api`), needing no connector.

Swapping is a config edit, not a refactor:

```json
{ "type": "slack", "via": "agent", "label": "slack", "context": "work" }
{ "type": "slack", "via": "api",   "label": "slack", "context": "work" }
```

Two costs, accepted deliberately. A headless run is **seconds, not
milliseconds**. And it puts an LLM in the fetch path, where variance is
unwelcome — mitigated by giving the agent **no judgement whatsoever**: run
these exact searches, collapse by conversation, emit this exact JSON. All
ranking stays in the separate judging skill.

**The `awaiting` rule and conversation collapse live in the CLI, on both
sides of the swap**, so the two transports cannot drift apart in behaviour.

### CLI and skill

- **The CLI fetches and pre-filters.** Deterministic, fast, free.
- **A skill judges and ranks.** Reads the surviving candidates, orders them,
  writes one line each on why.

The boundary test: **unplug the skill and the CLI must still return something
usable** — an unranked, newest-first digest rather than nothing.

### Judging (ratified 2026-09-15)

Design not yet built (see Next plan).

- **Two stages: gather, then judge.** The CLI's gather is deterministic; the
  `almoner:judge` skill runs second, and processes only items whose
  `digest_hash` differs from the hash they were last judged at.
- **The agent never touches SQLite.** `almoner judge --pending [--limit N]` is
  a pure read — it never marks rows shown — returning unjudged or changed
  items plus a feedback block of the reader's recent dismissals and acks
  (capped at 20; title, source, asks — no bodies). `almoner judge --apply
  FILE|-` validates per item against a fixed schema; each judgement echoes
  `digest_hash`, and a stale one is rejected.
- **Store:** a `judgement` table keyed `(id, digest_hash)`, history kept,
  latest `judged_at` wins; a `rollup(key, title, excerpt, judged_at)` table.
  Judgements are not columns on `item`, because each gather replaces the item
  row.
- **Judgement fields:** `asks`, `rank`, `because`, `topic` (free-text label
  for v1), `for_reader`, `fold_into`, `attributed`.
- **`for_reader` demotes only.** Row state is `bundled` > (`awaiting === true`
  && `for_reader !== false`) > reconcile > fyi. Mechanical `awaiting` is never
  overwritten.
- **The agent cannot hide rows.** Its only tools for noise are `fold_into` (a
  disclosed rollup) and `for_reader: false`.
- **Safety gate in code:** a keyword list (sign-in, password, login/verification
  code, reset, bank, payment, invoice, card, credential, currency marks); a
  keyword-hit item without an explicit `attributed: true` has its `fold_into`
  rejected per item.
- **Rollup validation:** every member is an accepted item in the same batch;
  `excerpt` is non-empty and not equal to `title`; the read shows the rollup as
  one `bundled: true` row, members not repeated at top level.
- **v1 is interactive-only** (run the skill in a session). Connector lookups
  during judging are allowed, read-only, only for rows otherwise ambiguous. A
  dashboard Judge button (headless `claude -p`, inheriting `CLAUDE_CONFIG_DIR`)
  is a later task.

## Findings that shaped this

These came from measurement, not assumption, and several overturned the
original brief.

### Slack has no unread, and `to:me` is not what it says

The connector reaches public channels, private channels, DMs and group DMs,
and supports `to:me`, `from:`, `in:` and date filters. But:

- **There is no unread concept** — no `is:unread`, no mentions endpoint, no
  unread counts. It gives **recency, not unreadness**. This turns out to
  agree with the design: almoner keeps its own `seen` state rather than
  trusting remote read-state, so dismissal is its own judgement.
- **`to:me` is a conversation filter, not an addressed-to-you filter.** It
  returns the same set as an unfiltered DM search minus your own messages.
  Anything relying on it to mean "someone asked me something" is wrong.
- **Your own messages come back** in an unfiltered search, so `-from:me` is
  mandatory.
- **Search returns at most 20 results per call**, which constrains paging.

### The item grain is a conversation, not a message

Twenty messages across 48 hours covered about **five actual conversations**.
One person sent five consecutive messages inside a minute that were plainly
one thought. Five rows of that is noise the reader must re-triage by hand,
which defeats the page. Rows collapse a run of messages and disclose the
collapse ("5 messages ▾") rather than hiding it.

### Most asks are already closed — the last-speaker rule

A question at 11:06 was settled by 13:37. A digest that still calls that an
open ask is simply wrong. The fix is mechanical and belongs in the CLI:

> **If the last message in a conversation is from you, it is probably not
> awaiting you.**

That single rule drops nearly all of the observed traffic with no judgement.
It is exposed as `awaiting`, computed identically on both transports, and
**strictly `=== true`** at the render site — an adapter that cannot compute
the rule leaves the field absent, and absence must not manufacture urgency.

**Caveat on the measured signal rate.** The observed ~5% actionable rate is an
artefact of measurement, not a property of Slack: the inbox had already been
triaged by hand before it was sampled. The plugin's value is that it lets that
manual checking stop, at which point more of the digest is genuinely open.
Do not treat 5% as a design target.

### Mail authentication: live, discouraged, undated

Google's own Workspace page, describing the less-secure-apps shutdown, says
plainly: *"You will no longer use a password for access (with the exception of
app passwords)."* Google's personal-account page gives **no discontinuation
date**, saying only that app passwords *"aren't recommended"*. Third-party
"2026 phase-out" claims trace to vendor blogs, not Google.

So **IMAP + app password is a live path with no announced end**, on a
deprecation-shaped trajectory. That argues *for* the adapter-per-transport
design: a future OAuth mail adapter is a new file, not a rewrite.

Two caveats: IMAP has been on by default since January 2025 (nothing to
enable), but **Workspace admins can disable app passwords entirely**, so a
work mailbox may not follow personal's answer.

**Probe status: written, not yet run** — it waits on an app password being
generated and stashed in the macOS Keychain. It opens the inbox `readonly`
and fetches headers with `BODY.PEEK`, so it cannot even mark mail read.

### Gathered for real, 2026-09-14

The design above was built from samples and an invented fixture. It was then
run against the actual accounts, by hand, in the shape the CLI will emit. Four
things came back, and none of them softened the design.

**Not one of thirty mail threads was written by a human.** Over four days:
orders and deliveries, newsletters, promotions, two from a professional
network, a calendar notification, two security notices. Zero conversations.
The invented fixture guessed two humans in twenty and was too generous. On this
mailbox, folding is not a feature of the product — it *is* the product, and a
digest that merely listed what arrived would be indistinguishable from the
inbox it was supposed to replace.

**Slack was eighteen bots to two people.** Twenty results, and the two human
messages were a broadcast about CI flakes and a question addressed to somebody
else. This matters for the `awaiting` rule: computed mechanically, both humans
score `awaiting: true` because the last message in each was not the reader's —
yet neither actually wants anything from them. The rule is still right to be
mechanical and cheap, but it is a *floor*, and this is the evidence that the
judging skill has real work to do above it rather than merely ordering rows.

**The safety rule fired unprompted, on its own merits.** Two security mails
arrived in the window. One was attributable — a sign-in to a florist's site
three minutes before that florist's own order confirmation — and folds away
quietly. The other was an account-confirmation code with nothing near it to
explain it, which is exactly the case the rule exists for, and it escaped as
its own `awaiting` row. Neither outcome was arranged. That is the first
evidence the rule discriminates rather than simply always-escaping.

**The inflow gap fired six times out of six, and is useless.** Every active
Linear issue was reported as having no overseer card — because the board holds
111 cards and *not one* carries a Linear key. The check is correctly
implemented and worthless, which is precisely the noise failure open question 2
warned about. **It must not ship until cards actually carry the key**; until
then it would train the reader to ignore the Reconcile group, which is the one
group that cannot afford to be ignored.

### A durable mail link needs no extra scope — but it is a search

Linking out to a mail row needs nothing but the RFC 822 `Message-ID` header,
which every IMAP fetch already returns: `#search/rfc822msgid:<id>` finds it. So
the `via: imap` adapter can link out **without the Gmail API and without asking
for a second scope.**

The caveat is real and worth not pretending otherwise: that is a **search URL,
not a direct link to the message.** Gmail's own web id is wrapped with a
per-account server key, cannot be derived offline, and is not returned by the
API — a durable direct link is simply not available to us. The reader lands on a
search page holding exactly one result. Good enough to act on; not the same
thing as opening the message.

Two details fall out of it. The `/u/<n>/` account form indexes mailboxes by
**signed-in order**, which is unstable and differs per device, so a stored link
carries the **address** instead and lets Gmail resolve the mailbox — which
matters because this design has always assumed more than one. And on a phone the
Gmail app claims `mail.google.com` links, so a single URL covers both.

## Data model

### Item

A row is a **conversation**. `messages` ride inline in the digest rather than
being fetched on expand: at real volumes the payload is trivial, and a
per-expand fetch would mean a fresh headless agent run every time a row opens.

```jsonc
{
  "id":       "slack:GDM-0000:1757612775", // conversation, not message; dedup key
  "source":   "slack",
  "context":  "work",
  "title":    "Group DM · Rhona, Tomas",    // who and where
  "excerpt":  "…do you think we could get a third pair of eyes on this",
  "count":    5,                            // messages collapsed
  "messages": [ { "who": "…", "text": "…", "at": "…", "url": "…" } ],
  "who":      "Rhona Baird",
  "arrived":  "2026-09-11T19:06:15+01:00",  // absent on derived items
  "bundled":  false,                        // true on a rollup of machine mail
  "awaiting": true,                         // MECHANICAL — see last-speaker rule
  "asks":     "reply",                      // review|reply|rsvp|acknowledge|
                                            // verify|reconcile|fyi; null until judged
  "url":      "https://…",                  // deep link to the conversation
  "seen_in":  ["slack", "mail"],            // one event legitimately arrives twice
  "rank":     null,                         // filled by the judging pass
  "because":  null
}
```

*(Names and ids throughout this document are invented, matching the sample
fixture. See Distribution.)*

`count` and `messages.length` are allowed to disagree — an adapter may
summarise without shipping every line — and the UI label follows what can
actually be shown.

### Rollups: folding machine mail

A first scan of a real personal mailbox found **eighteen of twenty threads over
four days were machine-written**, and of the two a person sent, one had already
been answered. A second scan, a day later and over the same window, found
**thirty threads of which not one was written by a human at all** (see Gathered
for real). Suppression and folding are therefore the main event, not a
refinement of it — and the first scan was the optimistic one.

Dropping machine mail silently loses information — *did my parcel ship?*
Listing it individually drowns whatever a person did write. So each category
folds into **one row** carrying `bundled: true`, which expands with exactly the
same control as a conversation: `messages` holds the individual items, and
nothing has actually gone.

**A rollup's excerpt must name its subjects, never restate its count.** A row
titled *3 security alerts* whose excerpt reads "3 security alerts" is a row you
must open every single time, which defeats the fold. *"mail account: new
sign-in, and an app granted access · photo service: login code"* can be
dismissed at a glance. Which account, which order, which parcel — the adapter
is expected to extract that, and **a rollup that cannot is better left as
individual rows.**

Rollups are excluded from the day band (see The page): a row standing for four
newsletters would plot as one dot of equal weight to a review request, and the
band is a picture of when *work* reached you, not when mail did.

#### Safety rule: attribution before folding

> **Never fold a security or access event that cannot be positively attributed
> to the reader.**

A sign-in you made is noise. A sign-in you did not make, to a bank, is the most
urgent thing that can arrive all week — and burying it under *"3 security
alerts"* beside the newsletters is worse than not folding at all. When
attribution is uncertain the item **escapes the bundle as its own row, with
`awaiting: true`**. The same caution applies to anything naming money,
credentials or a password reset.

Folding is an optimisation; this is the case where the optimisation is not
worth its cost. The sample fixture demonstrates the escape deliberately, with
an unrecognised bank sign-in sitting outside the security rollup that would
otherwise have swallowed it.

Row state checks `bundled` **before** `awaiting`, so a rollup never wears
"needs you" whatever an adapter happened to set — the escape above is the only
route by which a machine-written item reaches that state.

### Store

**Decision (2026-09-13): the store caches remote content.** This reverses the
original brief's "no cache of remote content" non-goal, on the owner's
explicit instruction after the trade-off was put to them. What follows
supersedes that non-goal.

What it buys beyond browsing history:

- The page **renders instantly on open** from the last gather, instead of an
  empty "nothing gathered yet" state before a slow round trip.
- Yesterday's **ranking is stable** — it is the judgement that was actually
  made, not one recomputed against a moved window.
- `--new` becomes trivial, and history survives content being deleted upstream.

```
watermark   source, cursor, fetched_at
seen        id, source, first_seen, last_seen, shown_count,
            digest_hash, state, state_at        -- new|shown|dismissed|acted
item        id, source, context, title, excerpt, messages, url,
            who, arrived, awaiting, gathered_at
suppressed  id, source, rule, at                -- what was filtered, by which rule
run         id, started, finished, sources_ok, sources_failed,
            items_in, items_out
```

`asks`, `rank` and `because` are deliberately not columns here — they are
judgements, and every gather replaces the `item` row wholesale, which would
wipe them. They live in the planned `judgement` table (see Judging), keyed
`(id, digest_hash)`, once that stage is built.

Consequences that must be designed for, not discovered:

- **History is a snapshot, not a live view.** Stored content can diverge from
  the source (edits, deletions). Historical rows must be stamped *"as gathered
  at HH:MM"*, and expanding or following one out goes live to the source.
- **The store now grows with content**, not merely with observations. That
  was expected to force a retention policy; it did not — see Retention below,
  where the window turns out to be a view rather than a delete.
- **The store now holds work content at rest** in `$CLAUDE_CONFIG_DIR/almoner/`
  (per Claude account), not the central overseer folder — the store directory
  is `0700` and the database file and its `-wal`/`-shm` sidecars are `0600`,
  regardless of the process umask: `store.connect()` narrows the umask for
  the create/connect/schema sequence and then tightens the directory, db and
  any sidecars unconditionally, so a pre-existing loose directory or file is
  brought private too, not just what gets created fresh. Local only, never
  committed, never sent anywhere.

#### Retention: the window is a view, not a delete

**Decision (2026-09-13, owner): the store keeps everything. Nothing rolls.**
What was an open question about deletion turns out to be a question about the
*default view*, and those are not the same thing.

The digest is read through a **window — 7, 14 or 30 days, configurable** —
which is a filter over the query and never a filter over what is written. The
consequences that follow are the point of settling it this way:

- **Nothing is ever lost to a policy chosen before anyone knew what history
  was worth.** The table's value is depth, and a roll set at thirty days
  quietly forecloses the fortnight-scale argument the day band is supposed to
  make about your calendar.
- **`suppressed` stays complete**, so "why did I never see this?" is always
  answerable. It remains the largest table by far — that is now a storage
  cost knowingly accepted, not an accident. It is local, single-user and
  text; the growth is real but slow.
- **The window must be a query bound, not a post-filter.** Reading the whole
  store and discarding in the page is the one implementation that would make
  this decision expensive, and it gets slower every week it runs.
- **Growth is therefore a monitoring concern, not a correctness one.** `log
  --runs` should be able to say how large the store has become, so an
  eventual archive or prune is a decision taken on evidence.

The default window ships at the middle value. If deletion is ever wanted it
arrives as an explicit, owner-invoked prune — never as a background roll that
throws away history nobody chose to lose.

### Dismissal expires on change

Keying dismissal to the id alone means dismissing something once suppresses it
forever, including after it becomes relevant again. Store a `digest_hash` over
the fields that would change your mind — state, assignee, priority, due date —
and treat a dismissal as applying to that hash. When the hash moves, the item
returns as new. **Dismissing means "not as it currently stands", not "never
again".**

`acted` is a separate state and mostly a fallback: `awaiting` already flips a
row out of *Awaiting you* mechanically when you reply in the source. Manual
marking earns its place only where the action happened somewhere the source
cannot see.

### Watermarks are an optimisation, not a cursor

If the watermark alone decides what gets fetched, anything arriving with an
earlier timestamp — delayed delivery, a backfilled webhook, clock skew — is
missed permanently and silently. Instead: fetch from **watermark minus an
overlap window** (an hour, tunable per source) and let `seen` discard what has
already been shown, by id. Idempotent dedup by id is what makes re-fetching
safe; the cursor only avoids paging through last month.

## The page

Reading order is deliberate: **summary before detail.**

1. **The day band** — *where did the time go.* Arrivals placed along a time
   axis, clustered runs lifted into lanes. It answers something no list does:
   what shape did the day have? The quiet middle afternoon and the 19:06
   pile-up are visible at a glance, and over a fortnight that is an argument
   about your calendar rather than about your inbox. It covers the newest day
   only — a scatter across a fortnight is a different chart.
2. **Waiting on you** — *who am I holding up.* The digest re-read as
   obligations to **people**, because an obligation is owed to someone and not
   to a piece of software: *"Rhona has been waiting two hours"* lands in a way
   *"1 unread"* never does. This is where the last-speaker rule stops being a
   hidden filter and becomes the headline — **`clear` is earned** (you answered
   last), not merely "nothing arrived". The strip is capped so it stays a
   glance rather than a directory, and the cap bites on the **cleared** first:
   an owed person falling off the strip is the one outcome that would make the
   strip a liar.
3. **The day table** — *what exactly.* The working surface.

### Two views, and the table won

The original design made **urgency positional**: three groups, *Awaiting you*
above *Reconcile* above *For information*.

**Decision (2026-09-13): the day table is the primary view.** Rows are cut into
days, newest day first and newest-first within each day. Urgency stops being
positional and is carried three ways at once — a spine down the row's left
edge, a filled state chip, and a faint wash on rows that still want you. Three
channels because one is never enough, and the chip says "needs you" in *words*,
so colour is reinforcement rather than the only carrier.

The two are not rivals. They answer different questions:

| View | Question | Structure |
|---|---|---|
| Grouped | *what needs me now* | urgency, positional |
| Day table | *what happened yesterday* | time |

**The table is the history view this design asked for, and that is why the
store caches content** (see Store). "Yesterday" is the next block down rather
than a different screen. Without the cache the table holds exactly one day and
is not worth building — the two decisions stand or fall together.

`groupDigest` remains exported and tested but is no longer rendered. It is one
component away from returning as a toggle, so the grouping rules below are live
specification rather than history.

| Group | Rule |
|---|---|
| **Awaiting you** | `awaiting === true` |
| **Reconcile** | `asks === "reconcile"` — derived, nobody sent it, no arrival time |
| **For information** | everything else |

Within a group: ranked items first ascending, then unranked newest-first. Empty
groups are omitted; Reconcile sits below Awaiting so derived items never compete
with things a person actually said. The table's row state uses the **same
three-way split**, so the two views may disagree about where a row sits but
never about what it is.

Undated items — the derived reconcile checks — ride at the top of the newest
day rather than in a section of their own: they are current, and an orphan
"no date" heading reads as a rendering fault rather than as a finding.

**One layout at every width.** An earlier pass restacked the table into cards
below the house breakpoint, and the table simply vanishing on a narrow window
was more confusing than useful. The narrow case tightens the columns instead.

## Linear × overseer: a join, not a duplicate

Linear is the high-level work board; overseer is the inflow board for
breakdowns and agent work. A Linear issue does not duplicate an overseer card
— it **decomposes into** them, and the interesting information is the gap
between. Neither board shows that gap alone; almoner can, because it reads
both. **They must never be deduplicated against each other.**

The join key already exists: `Card` carries `jira` and `linear` fields, both
are schema columns, and `cli.py` does
`card_id = args.jira or args.linear or db.mint_id(conn)` — so a card created
against an issue takes that issue key **as its id**. Match on both the
`linear` field and the card id.

Two derived checks, computed by joining, neither a notification:

- **Inflow gap** — a Linear issue assigned to you, in an active state, with no
  overseer card carrying its key. **Settled 2026-09-13 — see "Active" below.**
- **Upstream drift** — an overseer card whose Linear issue has since been
  closed, reassigned, or dropped in priority.

Both render as `asks: "reconcile"`, in their own group.

### "Active" is a state TYPE, with one named exception

**Decision (2026-09-13, owner): active means `type: "started"`, minus
`Blocked`.** In practice: *In Progress* and *In Review*.

Key the rule on the state **type, never the name.** Linear names are defined
per team and differ between them, so a list of names is a rule that breaks the
first time a second team appears; `type` is workspace-wide and stable. It also
keeps the spec free of any real team's vocabulary, which matters because this
repo is public.

The reasoning, stated so it can be argued with later:

| Type | Active? | Why |
|---|---|---|
| `started` | **yes** | You have begun it. Beginning work with no breakdown behind it is exactly the gap worth seeing. |
| `unstarted` | no | Ready-to-pick-up is not a gap. Having no card is *correct* until you start. |
| `backlog` | no | Flagging a backlog deliberately not started is the noise that would make the check worthless. |
| `triage` | no | Not yours yet. |
| `completed` / `canceled` / `duplicate` | no | Nothing to decompose. |

**The `Blocked` exception is deliberate and is the one place a name is used.**
Linear classes a blocked issue as `started`, which is true — it was begun —
but a blocked issue is one you have *stopped on purpose*, and a check nagging
for a breakdown of work you cannot do is the check crying wolf. So it is
excluded by name.

That makes the exception the portable part's weak point, and the config must
own it rather than the code:

```jsonc
{ "type": "linear",
  "active": { "types": ["started"], "exclude": ["Blocked"] } }
```

`types` is the backbone and travels anywhere; `exclude` is a per-workspace
escape hatch that is empty by default. A name in `exclude` that matches no
state is **not an error** — teams rename things — but `almoner status` should
say so, because a silently-inert exclusion is how this check would start
crying wolf again without anyone noticing.

## Surface

```
almoner status                     sources configured, reachable, last fetch
almoner digest --json              all sources, merged, deduplicated
almoner digest --source linear     one source
almoner digest --context work      one context
almoner digest --hours 72          widen the fetch window (default 48)
almoner digest --days 14           how far back to READ (7|14|30, default 14)
almoner digest --new               only what has not been shown before
almoner dismiss <id>               local only
almoner ack <id>                   mark actioned — local only
almoner log --runs                 refresh history
almoner log --suppressed           what was filtered, and by which rule
almoner judge --pending            unjudged/changed items, read-only         (unbuilt)
almoner judge --apply FILE         apply validated judgements from FILE or - (unbuilt)
almoner digest --cached            read the store without gathering         (unbuilt)
```

```
GET  /api/almoner/status    { installed, configured, sources[] }
GET  /api/almoner/digest    ?hours=&days=&context=&new=  — soft-fails to
                             { items: [], sources: [], error } when the CLI
                             fails; a genuinely empty digest carries no
                             `error`. `days=` (unbuilt) is not yet passed
                             through — every read uses the CLI's default.
POST /api/almoner/dismiss   { id } — token-gated, like the board's mutations
GET  /api/almoner/log       ?runs= | ?suppressed=
```

`--hours` and `--days` are different axes and must not be conflated:
`--hours` bounds what is **fetched** from the sources this run, `--days`
bounds what is **read back** out of the store (see Retention). Gathering an
hour's worth and displaying a fortnight is the normal case.

Read verbs go through `run_almoner`, which returns `None` for a missing
plugin, timeout, non-zero exit or bad JSON alike. `POST /dismiss` is a
mutation and sits behind the token gate, not the ungated path chronicle's
sync uses.

## Non-goals

- **No schedule.** No plugin manifest can register recurring work. Refresh is
  manual, by design; the 08:00 cloud task owns the unattended case.
- **No writes to remote systems.** Nothing is sent, replied to, marked read,
  archived, assigned or resolved. Dismissing changes a local row and nothing
  else; the remote systems never see almoner at all.
- **No externally-written store.** The store is written only by almoner's own
  runs. It accepts no payload from outside.
- **Not a notifier.** It has no opinion about when you should look.

*(The former "no cache of remote content" non-goal is superseded — see Store.)*

## Distribution

The published plugin ships an **empty source list**. Installed-but-unconfigured
renders "not configured", distinct from "nothing needs you" — otherwise a
fresh install reads as good news. Nothing in the public code names any
account, workspace or mailbox.

**The sample fixture ships in the public build.** It carries real *shapes* with
entirely invented names, links and numbers, and says so on the page. Do not
repopulate it with real content: no colleague, customer, employer, account or
workspace may be nameable from anything in this repo — this document included.

### Two fixtures, and the one that is not allowed to ship

`fixture.ts` ships and is invented. `fixture.local.ts` does not ship, is
gitignored, and holds a developer's own gathered inflow — because judging this
design needs real content. An invented fixture cannot tell you whether a
rollup's excerpt is enough to dismiss on, since its excerpts were written by
someone who already knew the answer. The local file wins at runtime when it
exists; `import.meta.glob` is what makes it optional, because a bare import of
a missing module fails the build while a glob that matches nothing is an empty
object.

Two rules hold it together, and both were learned rather than designed:

**The shipped fixture is used under test even when an override exists.**
Otherwise the suite asserts against whatever is in one person's inbox that
morning — green locally, red in CI, red differently tomorrow. A private file
must never decide whether the tests pass.

**Gitignoring the override is not sufficient, and believing it was cost us a
disclosure.** `dist/` is committed. `npm run build` compiles whatever is in
`src/`. A build run with an override present therefore writes real names,
customers and commercial terms into the repository — and on 2026-09-14 it did
exactly that, to a public repo, and nothing failed. It was found by grepping
the built asset afterwards. So the override now declares a marker that
`demo.ts` re-exports, and a test greps `dist/` for it: a bundle carrying local
content cannot be committed with the suite green. **Assume any local-only input
will eventually be compiled into a committed artefact, and put the check
there.**

Credentials live one file per source label, `0600`, gitignored, following
`scripts/remote_token.py`; a missing file means "this source is not
configured" and never raises.

## State of play

**Built** (WF-111), on branch `feat/almoner-page` as PR #71, stacked on #70:
the dashboard page — TopBar coin gated on `/api/almoner/status`, code-split
page, soft-failing backend routes, the day band, the waiting strip, the day
table with conversation *and* rollup disclosure and per-message permalinks, the
grouping and ordering logic kept behind it, source-aware links out including
the Gmail `rfc822msgid` form, service icons for four sources, the optional
local-inflow override, and a labelled sample fixture at `?demo=1` so the page
is visible before the CLI exists. The suite stands at **1218 frontend and 222
backend**, of which the almoner's own are a subset.

Also done along the way, because the almoner's fourth coin exposed them: the
guild bar's view switcher now places any number of coins rather than exactly
three; the bar names the page you are on; and the board's five unrelated reds
became one alarm pair (Pantone 485 with a vermilion for text).

**Built (2026-09-15)**, on branch `feat/almoner-ui`: the `almoner` CLI core —
`status`, `digest`, `dismiss`, `ack`, `log --runs|--suppressed` — the SQLite
store (`watermark`, `seen`, `item`, `suppressed`, `run`), the Notion source
(`type: notion`, `via: api`), and the history read the table was already
shaped to display. Fetches run on daemon threads so a wedged source can never
hold the CLI process open; adapter construction failures degrade per source
like fetch failures. The Notion adapter degrades per item: a malformed page is
suppressed as `notion:malformed-page`, a page whose comments are all malformed
as `notion:malformed-comments`, alongside `notion:no-open-comments` and
`notion:no-new-comments`. Two Notion API facts remain unverified until a live
smoke test: whether inline block comments are returned when listing comments
by page id, and the `?d=<discussion_id>` deep link. Two more, found during
the 2026-09-15 final review, remain unverified the same way: whether posting
a new comment bumps a page's `last_edited_time` at all — if it does not, a
new comment on an otherwise-untouched page is never picked up by the recency
scan — and whether `Notion-Version: 2026-03-11` is actually accepted by the
API rather than silently downgraded.

**Awaiting is computed per thread, not per page (F1).** A Notion page can
carry several open discussions at once, and the reader answering one must
not hide an unanswered question sitting in another. `InMessage` carries an
internal `thread` id (the discussion id, on Notion); when any message on a
row has one, `awaiting` is computed by grouping on it: `true` if any
thread's newest message is not the reader's, `false` only if every thread's
newest message is, and absent otherwise. A row with no threads keeps the
original whole-row rule.

**The 50-page cap is disclosed, and never moves the watermark past what it
skipped (F2).** `_recent_pages` stops at `MAX_PAGES`; if pages in the window
were still unread when it did, the fetch reports `complete: false` and a
warning naming the cap, and `gather_and_store` holds the previous watermark
rather than advancing it. The search is newest-first, so a page skipped by
the cap is only ever older than everything already read this run — a later
run does not "pick up" from the cap in any special sense, it just re-runs
the same newest-first search from scratch and re-hits the same cap at the
same place, reading no more pages than it did last time. The warning keeps
firing on every run until one of them finds fewer than `MAX_PAGES`
recently-edited pages still in the window — which only happens as the
oldest of them age out of it, not because any run reads further into them.
The same mechanism surfaces a second
warning when the configured `me` cannot be resolved to a Notion user, since
`awaiting` is then unknown for the whole run. Archived and trashed pages are
now skipped outright (`notion:archived`) and reported `closed`, never read.
Fully paging past the cap in one run is deferred — this is the honest v1.

**A resolved conversation leaves the digest (F3).** Notion's comments
endpoint only ever returns open threads, so a page whose last open thread
gets resolved would otherwise sit in the digest, stale, for up to `--days`.
The Notion adapter now reports such pages as `closed` (in addition to the
existing `notion:no-open-comments` suppression) — `notion:no-new-comments`
pages are not, since their threads are still open, just quiet.
`store.read_digest` excludes an item with a `closed` suppression newer than its
own `gathered_at`; nothing is deleted, and a later gather that re-emits the
item (its threads reopened) clears the suppression's effect by moving
`gathered_at` past it.

**Unbuilt:** Slack, Linear and mail adapters; the judging skill;
`POST /api/almoner/dismiss`; a `days` passthrough on `GET /api/almoner/digest`.
`status` also still surfaces a CLI failure the same way as "no sources"
(`configured: false`) rather than with its own `error`, unlike `digest` —
and the page's empty state currently points at the overseer config rather
than `$CLAUDE_CONFIG_DIR/almoner/config.json`. Both are next-plan items.

**Built but must not ship yet:** the inflow-gap check — see Gathered for real.
It needs overseer cards to carry Linear keys before it says anything true.

## Open questions

1. ~~**Retention policy for the store.**~~ **Settled 2026-09-13 — see
   Retention: the window is a view, not a delete.**
2. ~~**Which Linear states count as "active"**~~ **Settled 2026-09-13 against
   the real workflow states — see "Active" is a state TYPE.**
3. ~~**Is the source list per-machine or per-repo?**~~ **Settled 2026-09-15: per
   machine, rooted per Claude account at `$CLAUDE_CONFIG_DIR/almoner/`.**
4. **Mail authentication**, once the probe runs: app password if it holds,
   otherwise provider OAuth with someone owning the client registration.
5. **Slack `via: api` may never be available** — a corporate workspace may not
   permit a user token. If so, `via: agent` is not a stepping stone but the
   permanent transport, and its latency budget becomes a first-class concern.

## Parked

**Granola → the vault, not the digest.** Meeting notes were considered as a
fourth source and deliberately parked. The agreed shape, should it return: a
separate **`clerk`** plugin writes Granola into an Obsidian vault, extracting
once **at write time** so ids are stable; almoner then reads that vault as an
ordinary `via: files` source, **reading the folder at gather time and never
watching it**. SQLite stays the store — the vault is a sink and a source, never
the backend.
