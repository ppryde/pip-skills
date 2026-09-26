# Read-only queries for a reconcile

All of these open the store read-only. Set `DB` to the store or, better, a copy. Run from a checkout
that has the merged chronicle code so `scripts.report` prices with the current rates.

```python
import sqlite3, sys
sys.path.insert(0, "plugins/chronicle")          # so `from scripts import report` works
from scripts import report, ratebook
DB = "/Users/<you>/.claude/chronicle/sessions.db"   # or a copy
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
book = ratebook.load(c)      # the price history; report._cost_of(row, book) prices one row
```

## Sources: sessions and cost per source and account

```python
nm = {"1538875f": "Enterprise", "ae34a29e": "Max", None: "NO ACCOUNT"}     # first 8 chars of the uuid
for r in c.execute("""select replace(coalesce(config_dir,'-'),'/Users/<you>/','~/') d,
                             substr(account_uuid,1,8) a, count(*) n
                      from sessions group by 1,2 order by 3 desc"""):
    print(r["d"], nm.get(r["a"], r["a"]), r["n"])
print("no account:", c.execute("select count(*) from sessions where account_uuid is null").fetchone()[0])
print("container sessions with no repo:", c.execute(
      "select count(*) from sessions where cwd like '/workspaces/%' and repo_root is null").fetchone()[0])
```

## DB-only sessions (transcript no longer exists anywhere)

```python
import os, glob
arch = {os.path.basename(p)[:-6] for p in glob.glob(os.path.expanduser("~/claude-transcript-archive/**/*.jsonl"), recursive=True)
        if "/subagents/" not in p}
gone = [sid for sid, p in c.execute("select session_id, transcript_path from sessions")
        if p and not p.startswith(("docker://",)) and not os.path.exists(p) and sid not in arch]
print(len(gone), "sessions exist only in the store")      # keep these; never rebuild the store
```

## Account cross-tab: config-dir account vs bridge owner

```python
import collections
tab = collections.defaultdict(lambda: [0, 0.0])
cost = {k: v["cost_usd"] for k, v in report._costs_by(c, "t.session_id", "", []).items()}
for r in c.execute("select session_id, account_uuid cfg, owner_account_uuid first_o, bridge_owner_uuid last_o from sessions"):
    k = tuple(nm.get(x[:8], x[:8]) if x else "none" for x in (r["cfg"], r["first_o"], r["last_o"]))
    # (config-dir account, first bridge owner, last bridge owner); "none" = never bridged
    tab[k][0] += 1; tab[k][1] += cost.get(r["session_id"], 0)
for k, (n, v) in sorted(tab.items(), key=lambda kv: -kv[1][1]):
    print(k, n, round(v))          # rows where the three disagree are the attribution question
```

Turns carry their own stamp: effective account = `COALESCE(turns.account_uuid, sessions.account_uuid)`.

## Duplicate groups (one API call counted more than once)

```python
groups, extra = c.execute("""select count(*), coalesce(sum(n-1),0) from
                             (select count(*) n from turns where model is not null
                              group by session_id, message_id having n > 1)""").fetchone()
print(groups, "duplicated calls,", extra, "surplus rows")     # 0 after `chronicle dedupe --apply`
```
`chronicle dedupe` (dry run) prices what removal would change, per account.

## Daily comparison against the console

```python
import time
ENT = "1538875f-1dea-4637-b6cb-9c21c02c8ce9"
since = time.mktime((2026, 9, 1, 0, 0, 0, 0, 0, -1))
ours = {d["day"]: d["cost_usd"] for d in report.summary(c, account=ENT, since=since)["by_day"]}
console = {"2026-09-01": 85, "2026-09-02": 35}     # the console's Claude Code bars, UTC
for day in sorted(set(ours) | set(console)):
    print(day, console.get(day, 0), round(ours.get(day, 0)), round(ours.get(day, 0) - console.get(day, 0)))
```

## Cost by model for a window (compare with the console's per-model view)

```python
s = report.summary(c, account=ENT, since=since)
for m in sorted(s["by_model"], key=lambda m: -(m.get("cost_usd") or 0)):
    print(m["model"], m["turns"], round(m["cost_usd"], 2))
```

## Top sessions and what they did

```python
rows = c.execute("""select t.session_id sid, t.agent_id, t.message_id, t.model, t.input_tokens, t.cache_read_tokens,
                           t.cache_creation_tokens, t.output_tokens, t.cache_5m_tokens, t.cache_1h_tokens
                    from turns t where t.model is not null""").fetchall()
cost, seen = collections.Counter(), set()
for r in rows:
    if (r["sid"], r["message_id"]) in seen: continue      # de-duplicated view
    seen.add((r["sid"], r["message_id"])); cost[r["sid"]] += report._cost_of(dict(r), book) or 0
for sid, v in cost.most_common(15):
    m = c.execute("select title, repo_root, git_branch, prompts, peak_context_tokens from sessions where session_id=?", (sid,)).fetchone()
    tools = c.execute("select tool_name, count(*) from tool_calls where session_id=? group by 1 order by 2 desc limit 5", (sid,)).fetchall()
    print(round(v), sid[:8], tuple(m), [tuple(t) for t in tools])
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
