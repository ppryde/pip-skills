# Read-only queries for a reconcile

All of these open the store read-only. Set `DB` to the store or, better, a copy. Run from a checkout
that has the merged chronicle code (Python >= 3.10) so `scripts.report` prices with the current rates.
Set `CHRONICLE_PLUGIN_ROOT` to that checkout's `plugins/chronicle`.

Environment, set once (nothing below hard-codes an account, a path or a label):

- `CHRONICLE_PLUGIN_ROOT` the checkout's `plugins/chronicle`.
- `RECONCILE_DB` the store or a copy of it (default: `$CHRONICLE_DB`).
- `RECONCILE_ACCOUNT` the account uuid you are reconciling (from `cli.py accounts`).
- `RECONCILE_ACCOUNT_LABELS` optional JSON `{"<first 8 chars of uuid>": "label"}` for readable output.
- `RECONCILE_ARCHIVE` optional folder of archived transcripts (`**/*.jsonl`).

```python
import collections, json, os, sqlite3, sys
sys.path.insert(0, os.environ["CHRONICLE_PLUGIN_ROOT"])   # so `from scripts import report` works
from scripts import report, ratebook
DB = os.environ.get("RECONCILE_DB") or os.environ["CHRONICLE_DB"]    # the store, or better a copy
ACCOUNT = os.environ["RECONCILE_ACCOUNT"]
LABELS = json.loads(os.environ.get("RECONCILE_ACCOUNT_LABELS", "{}"))
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
book = ratebook.load(c)      # the price history; report._cost_of(row, book) prices one row
HOME = os.path.expanduser("~")
def label(uuid):             # a readable account name, else its 8-char prefix
    return LABELS.get(uuid[:8], uuid[:8]) if uuid else "NO ACCOUNT"
```

## Sources: sessions and cost per source and account

```python
for r in c.execute("""select coalesce(config_dir,'-') d, account_uuid a, count(*) n
                      from sessions group by 1,2 order by 3 desc"""):
    print(r["d"].replace(HOME, "~"), label(r["a"]), r["n"])
print("no account:", c.execute("select count(*) from sessions where account_uuid is null").fetchone()[0])
print("container sessions with no repo:", c.execute(
      "select count(*) from sessions where cwd like '/workspaces/%' and repo_root is null").fetchone()[0])
```

## DB-only sessions (transcript no longer exists anywhere)

```python
import os, glob
archive = os.environ.get("RECONCILE_ARCHIVE")          # optional; no archive = empty set
arch = {os.path.basename(p)[:-6] for p in glob.glob(os.path.join(archive, "**/*.jsonl"), recursive=True)
        if "/subagents/" not in p} if archive else set()
gone = [sid for sid, p in c.execute("select session_id, transcript_path from sessions")
        if p and not p.startswith(("docker://",)) and not os.path.exists(p) and sid not in arch]
print(len(gone), "sessions exist only in the store")      # keep these; never rebuild the store
```

## Account cross-tab: config-dir account vs bridge owner

```python
tab = collections.defaultdict(lambda: [0, 0.0])
cost = {k: v["cost_usd"] for k, v in report._costs_by(c, "t.session_id", "", []).items()}
for r in c.execute("select session_id, account_uuid cfg, owner_account_uuid first_o, bridge_owner_uuid last_o from sessions"):
    k = tuple(label(x) if x else "none" for x in (r["cfg"], r["first_o"], r["last_o"]))
    # (config-dir account, first bridge owner, last bridge owner); "none" = never bridged
    tab[k][0] += 1; tab[k][1] += cost.get(r["session_id"], 0)
for k, (n, v) in sorted(tab.items(), key=lambda kv: -kv[1][1]):
    print(k, n, round(v))          # rows where the three disagree are the attribution question
```

Turns carry their own stamp: effective account = `COALESCE(turns.account_uuid, sessions.account_uuid)`.

## Models priced by prefix (a quietly inherited price)

A new model first seen after the last price refresh, or a dated snapshot id, is priced at its parent's
rate. `chronicle pricing status` lists them as `prefix_priced` and `unpriced_models`; the same from
Python:

```python
from scripts import pricerefresh
for m in pricerefresh.models_in_use(c, book)["prefix_priced"]:
    print(m["model"], "priced as", m["priced_as"], m["turns"], "turns")   # verify each against the pricing page
```

## Duplicate groups (one API call counted more than once)

```python
groups, extra = c.execute("""select count(*), coalesce(sum(n-1),0) from
                             (select count(*) n from turns where model is not null
                              group by session_id, message_id having n > 1)""").fetchone()
print(groups, "duplicated calls,", extra, "surplus rows")     # 0 after `chronicle dedupe --apply`
```
`chronicle dedupe` (dry run) prices what removal would change, per account.

## Daily comparison against the console

`by_day` buckets are LOCAL time; the console's are UTC. Use the public `report.cost_by_day` (one grouped
query; `report.summary` would run a dozen other full scans just to read `by_day`). `utc=True` is the
like-for-like series for the console; `utc=False` is chronicle's own local-day view.

```python
import time
since = time.mktime((2026, 9, 1, 0, 0, 0, 0, 0, -1))        # the start of the window you are checking
ours = {d: v["cost_usd"] for d, v in report.cost_by_day(c, account=ACCOUNT, since=since, utc=True).items()}
console = {"2026-09-01": 85, "2026-09-02": 35}     # the console's Claude Code bars, UTC: fill in yours
for day in sorted(set(ours) | set(console)):
    print(day, console.get(day, 0), round(ours.get(day, 0)), round(ours.get(day, 0) - console.get(day, 0)))
```

## Cost by model for a window (compare with the console's per-model view)

`by_model` is a whole-session sum for every session active in the window, so it over-counts sessions that
began before the window. For spend strictly inside the window, group `report._costs_by` by `t.model` with a
`t.ts >= ?` filter, as in the UTC snippet above.

```python
s = report.summary(c, account=ACCOUNT, since=since)
for m in sorted(s["by_model"], key=lambda m: -(m.get("cost_usd") or 0)):
    print(m["model"], m["turns"], round(m["cost_usd"], 2))
```

## Top sessions and what they did

`report.cost_by_session` ranks sessions by de-duplicated cost in one grouped query per rate period. The
store is already de-duplicated at ingest, and `chronicle dedupe` (dry run) reports what is left with
prices per account, so there is no Python pass over every turn and no duplicate-group re-implementation.

```python
for e in report.cost_by_session(c, account=ACCOUNT, since=since, limit=15):
    sid = e["session_id"]
    m = c.execute("select title, repo_root, git_branch, prompts, peak_context_tokens from sessions where session_id=?", (sid,)).fetchone()
    tools = c.execute("select tool_name, count(*) from tool_calls where session_id=? group by 1 order by 2 desc limit 5", (sid,)).fetchall()
    print(round(e["cost_usd"]), sid[:8], tuple(m), [tuple(t) for t in tools])
```
Read the first user prompt from the transcript (skip `<system-reminder>`, `<command-`, `Caveat:` and
`<task-notification` noise) for a one-line description. Titles are often empty.

## Claude Code's own recorded cost (a cross-check, not a ledger)

Transcripts hold `{"type":"cost-state","totalCostUSD":..,"modelUsage":{model:{...,"costUSD":..}}}` records in
some sessions. The running total resets when a process restarts (sum each segment's max). Compare it with
chronicle per session; on Enterprise sessions the two agreed within 3% (median ratio 1.00). Long sessions
lag because the record is a snapshot.

## Scan transcripts for account ids (rarely present)

Look for `ownerAccountUuid` (`bridge-session`), `accountUuid` (`artifact-autoreact-ledger`) and
`vetoedAgainstAccountUuid` (`history-suppression`, cause `restored_owner_mismatch`). They exist only in
recent versions and only for bridged or artifact sessions; the artifact field also carries other people's
uuids, so it is not a billing identity.

## Worked example (one machine, for scale only)

On the author's machine the first reconcile found 174 sessions that existed only in the store (54k turns),
and duplicate agent snapshots had inflated one account by about $14k of $31k before `dedupe` existed.
These figures describe that machine on that day; do not expect or quote them for yours.
