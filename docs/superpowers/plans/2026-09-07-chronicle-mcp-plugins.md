# Chronicle MCP + Plugin Usage Panels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show MCP usage (split by provenance) and plugin usage (MCP servers *and* skills) as two panels, both on the Chronicle page for the current filter view and in the per-session drawer.

**Architecture:** One nullable `qualifier` column on `tool_calls` keeps the plugin identity that ingest currently discards (`Skill`'s `skill` input, `Agent`'s `subagent_type`). One pure classifier in `report.py` turns `(tool_name, qualifier)` into MCP and plugin attributions; `summary()` and `session_detail()` each expose `mcp` and `plugins` blocks built from it. The frontend mounts one presentational component at both call sites. No new endpoints — both surfaces already fetch the verb that now carries the data.

**Tech Stack:** Python 3 stdlib + SQLite (chronicle), pytest; React + TypeScript + Vitest (dashboard frontend).

**Spec:** `docs/superpowers/specs/2026-09-07-chronicle-mcp-plugins-design.md`

## Global Constraints

- **Test isolation is mandatory.** Every Python test runs under the autouse `_isolate_chronicle` fixture in `tests/chronicle/conftest.py`, which pins `CLAUDE_CONFIG_DIR`, `CHRONICLE_DB` and clears `CLAUDE_CONFIG_DIRS` into `tmp_path`. Never write outside `tmp_path`. See the "Test isolation" section of `CLAUDE.md`.
- **Python test command:** `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q` (Poetry is not usable here; use the repo `.venv`). Baseline before starting: **95 passed**.
- **Frontend test command:** `cd plugins/overseer/dashboard/frontend && npm run test` (vitest).
- **Frontend build command:** `cd plugins/overseer/dashboard/frontend && npm run build` — `dist/` is committed, so it must be rebuilt and committed in the final task.
- **Chronicle is stdlib-only.** No new Python dependencies; `plugins/chronicle/scripts/` must not import from `plugins/overseer/`.
- **Idempotency.** Every write into `tool_calls` is keyed `(session_id, tool_use_id)`. A re-fold of the same lines must converge, never duplicate.
- **Naming, verbatim from the spec:** provenance values are exactly `"plugin"`, `"connector"`, `"local"`. Plugin item kinds are exactly `"mcp"` and `"skill"`.
- **Deliberate overlap:** a plugin-provided MCP server is counted in *both* the MCP block and the plugins block. This is intended; do not deduplicate.

---

### Task 1: The classifier

The pure function everything else is built on. No schema change and no I/O — it can be written and tested entirely on its own.

**Files:**
- Modify: `plugins/chronicle/scripts/report.py` (add near the top, after the existing module constants)
- Test: `tests/chronicle/test_report.py` (add a new `TestClassify` class at the end)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `report.McpRef`, `report.Classified`, `report.classify(tool_name: str, qualifier: str | None) -> Classified`, and the constant `report.QUALIFIED_TOOLS: dict[str, str]`. Tasks 2, 3 and 4 all depend on these exact names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/chronicle/test_report.py`:

```python
class TestClassify:
    def test_plugin_mcp_server_is_both_mcp_and_plugin(self):
        c = report.classify("mcp__plugin_playwright_playwright__browser_evaluate", None)
        assert c.mcp is not None
        assert c.mcp.server == "plugin_playwright_playwright"
        assert c.mcp.tool == "browser_evaluate"
        assert c.mcp.provenance == "plugin"
        # The overlap the spec asks for: it counts in BOTH boxes.
        assert c.plugin == "playwright"

    def test_hyphenated_plugin_name_splits_on_the_last_underscore(self):
        c = report.classify("mcp__plugin_agent-ui-telemetry_agent-ui__health_check", None)
        assert c.mcp.server == "plugin_agent-ui-telemetry_agent-ui"
        assert c.mcp.tool == "health_check"
        assert c.plugin == "agent-ui-telemetry"

    def test_connector_server_is_mcp_but_not_a_plugin(self):
        c = report.classify("mcp__claude_ai_Snowflake__sql_exec_tool", None)
        assert c.mcp.server == "claude_ai_Snowflake"
        assert c.mcp.tool == "sql_exec_tool"
        assert c.mcp.provenance == "connector"
        assert c.plugin is None

    def test_local_server_is_mcp_but_not_a_plugin(self):
        c = report.classify("mcp__claude-in-chrome__computer", None)
        assert c.mcp.server == "claude-in-chrome"
        assert c.mcp.tool == "computer"
        assert c.mcp.provenance == "local"
        assert c.plugin is None

    def test_tool_name_containing_a_double_underscore_keeps_its_tail(self):
        c = report.classify("mcp__wayflyer-dev__run__query", None)
        assert c.mcp.server == "wayflyer-dev"
        assert c.mcp.tool == "run__query"

    def test_malformed_mcp_name_falls_back_to_the_raw_string(self):
        # No second `__`: never drop the row, attribute it to itself.
        c = report.classify("mcp__brokenname", None)
        assert c.mcp.server == "mcp__brokenname"
        assert c.mcp.tool == "mcp__brokenname"
        assert c.mcp.provenance == "local"

    def test_qualified_skill_is_a_plugin(self):
        c = report.classify("Skill", "tribunal:reckoning")
        assert c.mcp is None
        assert c.plugin == "tribunal"
        assert c.skill == "tribunal:reckoning"

    def test_unqualified_skill_is_builtin_not_a_plugin(self):
        c = report.classify("Skill", "code-review")
        assert c.plugin is None
        assert c.skill == "code-review"

    def test_qualified_agent_is_a_plugin(self):
        c = report.classify("Agent", "pr-review-toolkit:code-reviewer")
        assert c.plugin == "pr-review-toolkit"
        assert c.skill is None

    def test_unqualified_agent_is_not_a_plugin(self):
        assert report.classify("Agent", "general-purpose").plugin is None

    def test_ordinary_tool_is_neither(self):
        c = report.classify("Bash", None)
        assert c.mcp is None and c.plugin is None and c.skill is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle/test_report.py::TestClassify -q`
Expected: FAIL — `AttributeError: module 'scripts.report' has no attribute 'classify'`

- [ ] **Step 3: Write the implementation**

In `plugins/chronicle/scripts/report.py`, confirm `from dataclasses import dataclass` is imported (add it to the existing import block if not), then add after the module constants:

```python
MCP_PREFIX = "mcp__"
# Tools whose identity lives in their input rather than their name. The value
# is the input key ingest keeps as the row's `qualifier` (see transcript.py).
QUALIFIED_TOOLS: dict[str, str] = {"Skill": "skill", "Agent": "subagent_type"}


@dataclass(frozen=True)
class McpRef:
    server: str
    tool: str
    provenance: str  # "plugin" | "connector" | "local"


@dataclass(frozen=True)
class Classified:
    """What one tool call contributes to each box. The fields are independent,
    not a single `kind`: a plugin-provided MCP server populates BOTH `mcp` and
    `plugin`, which is the overlap the two panels deliberately show."""
    mcp: McpRef | None = None
    plugin: str | None = None
    skill: str | None = None


def _plugin_of_server(server: str) -> str | None:
    """The plugin supplying an MCP server, from Claude Code's own naming:
    ``plugin_<plugin>_<server>``. Split on the LAST underscore, so
    ``plugin_agent-ui-telemetry_agent-ui`` yields ``agent-ui-telemetry``.

    A heuristic, because a plugin whose own name contains an underscore is
    indistinguishable from the server suffix. It degrades to naming the whole
    remainder rather than guessing wrong halves — attribution can be coarse,
    never fabricated."""
    if not server.startswith("plugin_"):
        return None
    rest = server[len("plugin_"):]
    plugin, _, suffix = rest.rpartition("_")
    return plugin if plugin and suffix else rest or None


def classify(tool_name: str, qualifier: str | None) -> Classified:
    """Attribute one tool call to the MCP and/or plugin boxes."""
    if tool_name.startswith(MCP_PREFIX):
        rest = tool_name[len(MCP_PREFIX):]
        server, sep, tool = rest.partition("__")
        if not sep or not server or not tool:
            # Unsplittable: attribute the row to itself rather than dropping it.
            server = tool = tool_name
            provenance = "local"
        elif server.startswith("plugin_"):
            provenance = "plugin"
        elif server.startswith("claude_ai_"):
            provenance = "connector"
        else:
            provenance = "local"
        return Classified(
            mcp=McpRef(server=server, tool=tool, provenance=provenance),
            plugin=_plugin_of_server(server),
        )
    if tool_name in QUALIFIED_TOOLS and qualifier:
        plugin, sep, _ = qualifier.partition(":")
        return Classified(
            plugin=plugin if sep and plugin else None,
            skill=qualifier if tool_name == "Skill" else None,
        )
    return Classified()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q`
Expected: PASS — 95 prior tests plus 11 new = 106 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/chronicle/scripts/report.py tests/chronicle/test_report.py
git commit -m "feat(chronicle): classify tool calls into MCP and plugin attributions"
```

---

### Task 2: Keep the qualifier at ingest

The store change. After this task the column exists and is populated for new ingests; `sync --full` backfills history.

**Files:**
- Modify: `plugins/chronicle/scripts/store.py` (the `_MIGRATIONS` tuple, ~line 172, and the `tool_calls` DDL in `_SCHEMA`, ~line 119)
- Modify: `plugins/chronicle/scripts/transcript.py` (`Turn.tool_uses`, `_fold_assistant`)
- Modify: `plugins/chronicle/scripts/ingest.py` (`_write_facts`, the `tool_calls` executemany, ~line 173)
- Modify: `tests/chronicle/conftest.py` (`TranscriptBuilder.turn`, ~line 110)
- Test: `tests/chronicle/test_transcript.py`, `tests/chronicle/test_ingest.py`

**Interfaces:**
- Consumes: `report.QUALIFIED_TOOLS` from Task 1.
- Produces: `tool_calls.qualifier` (nullable TEXT); `transcript.Turn.tool_uses` becomes a list of `(tool_use_id, name, qualifier)` **3-tuples**; `TranscriptBuilder.turn(tools=...)` accepts either a `str` or a `(name, input_dict)` tuple. Tasks 3 and 4 read the column; any code iterating `tool_uses` must unpack three values.

- [ ] **Step 1: Extend the test builder so a test can express a qualified call**

In `tests/chronicle/conftest.py`, replace the loop body inside `TranscriptBuilder.turn` (currently `for i, name in enumerate(tools):`) with:

```python
        for i, spec in enumerate(tools):
            # `tools` entries are either a bare name or (name, input) — the
            # latter for tools whose identity lives in their input (Skill).
            name, inp = spec if isinstance(spec, tuple) else (spec, {})
            blocks.append({"type": "tool_use", "id": f"{message_id}-tool{i}",
                           "name": name, "input": inp})
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/chronicle/test_transcript.py`:

```python
class TestQualifier:
    def test_skill_call_keeps_its_skill_name(self):
        facts = fold([json.dumps({
            "type": "assistant", "uuid": "u1", "sessionId": "s1",
            "timestamp": "2026-09-01T10:00:00.000Z",
            "message": {"id": "m1", "model": "claude-opus-5", "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": "Skill",
                                     "input": {"skill": "tribunal:reckoning", "args": "355"}}]},
        })])
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Skill", "tribunal:reckoning")]

    def test_agent_call_keeps_its_subagent_type(self):
        facts = fold([json.dumps({
            "type": "assistant", "uuid": "u1", "sessionId": "s1",
            "timestamp": "2026-09-01T10:00:00.000Z",
            "message": {"id": "m1", "model": "claude-opus-5", "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": "Agent",
                                     "input": {"subagent_type": "Explore",
                                               "prompt": "a very long prompt"}}]},
        })])
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Agent", "Explore")]

    def test_ordinary_tool_keeps_no_qualifier(self):
        facts = fold([json.dumps({
            "type": "assistant", "uuid": "u1", "sessionId": "s1",
            "timestamp": "2026-09-01T10:00:00.000Z",
            "message": {"id": "m1", "model": "claude-opus-5", "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                     "input": {"command": "ls -la /secret"}}]},
        })])
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Bash", None)]
```

Append to `tests/chronicle/test_ingest.py`:

```python
class TestQualifierColumn:
    def test_qualifier_is_stored_and_a_reingest_does_not_duplicate(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=[("Skill", {"skill": "overseer:ledger"}), "Bash"]
        ).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        ingest.sync(conn, projects, full=True)  # re-read from byte 0
        rows = dict(conn.execute(
            "SELECT tool_name, qualifier FROM tool_calls WHERE session_id = 's1'"
        ).fetchall())
        assert rows == {"Skill": "overseer:ledger", "Bash": None}
        assert conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE session_id = 's1'"
        ).fetchone()[0] == 2
```

If `T0` and `TranscriptBuilder` are not already imported at the top of `test_ingest.py`, add them — the file's existing tests use the same fixtures, so follow whatever import form is already there.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle/test_transcript.py::TestQualifier tests/chronicle/test_ingest.py::TestQualifierColumn -q`
Expected: FAIL — the transcript tests fail on a 2-tuple vs 3-tuple mismatch; the ingest test fails with `sqlite3.OperationalError: no such column: qualifier`.

- [ ] **Step 4: Add the column to the store**

In `plugins/chronicle/scripts/store.py`, add `qualifier` to the `tool_calls` DDL inside `_SCHEMA`, immediately after the `tool_name` line:

```sql
    tool_name    TEXT NOT NULL,
    qualifier    TEXT,
```

and append to `_MIGRATIONS`, so an existing store gains it too:

```python
    # Identity for tools whose name alone does not say what ran: a Skill's
    # plugin-qualified name, an Agent's subagent type. Backfilled by
    # `chronicle sync --full`, which re-reads every transcript from byte 0.
    ("tool_calls", "qualifier", "TEXT"),
```

- [ ] **Step 5: Keep the qualifier when folding**

In `plugins/chronicle/scripts/transcript.py`:

Change the `Turn.tool_uses` field declaration and its comment:

```python
    # (tool_use_id, name, qualifier) — see `_qualifier`.
    tool_uses: list[tuple[str, str, str | None]] = field(default_factory=list)
```

Add, after the `_artifact_use` function:

```python
# Tools whose identity is in their input, and the input key that carries it.
# Kept deliberately narrow: the transcript is the durable record and chronicle
# is a projection over it, so copying arbitrary inputs (an Agent's full prompt,
# a Write's file body) would make the store a second copy of the conversation.
QUALIFIED_TOOLS: dict[str, str] = {"Skill": "skill", "Agent": "subagent_type"}


def _qualifier(name: str, raw: Any) -> str | None:
    """The short identifier distinguishing one `Skill`/`Agent` call from
    another — `tribunal:reckoning`, `Explore`. None for every other tool."""
    key = QUALIFIED_TOOLS.get(name)
    if key is None or not isinstance(raw, dict):
        return None
    return _opt_str(raw.get(key))
```

In `_fold_assistant`, change the tool_use append block to carry it (`block.get("input")` is already in hand for the Artifact branch):

```python
            if (isinstance(tool_id, str) and isinstance(name, str)
                    and all(existing != tool_id for existing, _, _ in turn.tool_uses)):
                turn.tool_uses.append((tool_id, name, _qualifier(name, block.get("input"))))
                if name == ARTIFACT_TOOL:
                    artifact = _artifact_use(tool_id, block.get("input"))
                    if artifact is not None:
                        turn.artifacts[tool_id] = artifact
```

- [ ] **Step 6: Write it through ingest**

In `plugins/chronicle/scripts/ingest.py`, `_write_facts`, change the first `executemany` to include the column:

```python
    conn.executemany(
        """INSERT OR IGNORE INTO tool_calls(session_id, tool_use_id, agent_id, message_id,
               tool_name, qualifier, ts) VALUES (?,?,?,?,?,?,?)""",
        [
            (session_id, tool_id, t.agent_id, t.message_id, name, qualifier, t.ts)
            for t in facts.turns.values()
            for tool_id, name, qualifier in t.tool_uses
        ],
    )
```

Then search the rest of the codebase for any other consumer that unpacks `tool_uses` as a 2-tuple and update it:

Run: `grep -rn "tool_uses" plugins/chronicle tests/chronicle`

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q`
Expected: PASS — 106 prior plus 4 new = 110 passed. Any failure here is most likely a missed 2-tuple unpack from Step 6.

- [ ] **Step 8: Commit**

```bash
git add plugins/chronicle/scripts/store.py plugins/chronicle/scripts/transcript.py \
        plugins/chronicle/scripts/ingest.py tests/chronicle/conftest.py \
        tests/chronicle/test_transcript.py tests/chronicle/test_ingest.py
git commit -m "feat(chronicle): keep the plugin identity ingest was discarding"
```

---

### Task 3: `mcp` and `plugins` blocks in `summary()`

The aggregate the Chronicle page reads, honouring the repo/days/branch filter already in `_session_filter`.

**Files:**
- Modify: `plugins/chronicle/scripts/report.py` (`summary`, ~line 407 — add after the existing `tools` query)
- Test: `tests/chronicle/test_report.py`

**Interfaces:**
- Consumes: `report.classify` (Task 1), `tool_calls.qualifier` (Task 2).
- Produces: `report._usage_blocks(rows, *, with_sessions: bool) -> tuple[dict, dict]` returning `(mcp, plugins)`; `summary()["mcp"]` and `summary()["plugins"]`. Task 4 reuses `_usage_blocks`; Task 5 types the payload.

- [ ] **Step 1: Write the failing test**

Append to the existing `TestSummary` class in `tests/chronicle/test_report.py`:

```python
    def test_mcp_and_plugin_blocks(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0, tools=[
            "mcp__plugin_playwright_playwright__browser_click",
            "mcp__plugin_playwright_playwright__browser_click",
            "mcp__claude_ai_Snowflake__sql_exec_tool",
            "mcp__claude-in-chrome__computer",
            ("Skill", {"skill": "tribunal:reckoning"}),
            ("Skill", {"skill": "code-review"}),
            "Bash",
        ]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        out = report.summary(conn)
        mcp, plugins = out["mcp"], out["plugins"]

        assert mcp["calls"] == 4
        assert mcp["sessions"] == 1
        assert mcp["by_provenance"] == {"plugin": 2, "connector": 1, "local": 1}
        assert mcp["servers"][0] == {
            "server": "plugin_playwright_playwright", "provenance": "plugin",
            "tools": 1, "calls": 2, "sessions": 1, "result_chars": 0,
        }
        assert {t["tool"] for t in mcp["tools"]} == {
            "browser_click", "sql_exec_tool", "computer",
        }

        # The playwright MCP calls count in BOTH boxes (deliberate overlap);
        # `code-review` is a builtin skill and is in neither.
        assert plugins["calls"] == 3
        assert plugins["items"] == [
            {"plugin": "playwright", "kind": "mcp", "calls": 2, "sessions": 1},
            {"plugin": "tribunal", "kind": "skill", "calls": 1, "sessions": 1},
        ]

    def test_usage_blocks_respect_the_repo_filter(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["mcp__claude-in-chrome__computer"]).write()
        TranscriptBuilder(projects, "-b", "s3").prompt("u1", T1).turn(
            "m1", T1, tools=["mcp__claude_ai_Notion__notion-fetch"]).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET repo_root = '/repo/a' WHERE session_id = 's1'")
        conn.execute("UPDATE sessions SET repo_root = '/repo/b' WHERE session_id = 's3'")
        conn.commit()

        out = report.summary(conn, repo_root="/repo/a")
        assert out["mcp"]["calls"] == 1
        assert out["mcp"]["servers"][0]["server"] == "claude-in-chrome"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle/test_report.py::TestSummary::test_mcp_and_plugin_blocks -q`
Expected: FAIL — `KeyError: 'mcp'`

- [ ] **Step 3: Write the aggregation helper**

In `plugins/chronicle/scripts/report.py`, add after `classify`:

```python
def _usage_blocks(rows: Iterable[sqlite3.Row], *,
                  with_sessions: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold classified tool-call rows into the `mcp` and `plugins` blocks.

    Rows need `tool_name`, `qualifier`, `result_chars` and (when
    `with_sessions`) `session_id`. A plugin-provided MCP server lands in BOTH
    blocks: the two answer different questions — what MCP costs, and which
    plugins get used — so the overlap is the point, not a bug.

    `with_sessions` is False for a single-session read, where every count
    would be 1 and the key is noise.
    """
    servers: dict[str, dict[str, Any]] = {}
    tools: dict[tuple[str, str], dict[str, Any]] = {}
    plugins: dict[tuple[str, str], dict[str, Any]] = {}
    server_tools: dict[str, set[str]] = {}
    seen: dict[str, set[str]] = {}  # bucket key -> session ids, for `sessions`
    provenance: dict[str, int] = {}
    mcp_calls = mcp_chars = plugin_calls = 0

    def _touch(bucket: dict[str, Any], key: str, session_id: str | None) -> None:
        if with_sessions and session_id is not None:
            ids = seen.setdefault(key, set())
            ids.add(session_id)
            bucket["sessions"] = len(ids)

    for row in rows:
        c = classify(row["tool_name"], row["qualifier"])
        chars = int(row["result_chars"] or 0)
        session_id = row["session_id"] if with_sessions else None
        if c.mcp is not None:
            mcp_calls += 1
            mcp_chars += chars
            provenance[c.mcp.provenance] = provenance.get(c.mcp.provenance, 0) + 1
            server_tools.setdefault(c.mcp.server, set()).add(c.mcp.tool)
            s = servers.setdefault(c.mcp.server, {
                "server": c.mcp.server, "provenance": c.mcp.provenance,
                "tools": 0, "calls": 0, "result_chars": 0,
            })
            s["calls"] += 1
            s["result_chars"] += chars
            s["tools"] = len(server_tools[c.mcp.server])
            _touch(s, f"server:{c.mcp.server}", session_id)

            t = tools.setdefault((c.mcp.server, c.mcp.tool), {
                "server": c.mcp.server, "tool": c.mcp.tool,
                "calls": 0, "result_chars": 0,
            })
            t["calls"] += 1
            t["result_chars"] += chars
            _touch(t, f"tool:{c.mcp.server}/{c.mcp.tool}", session_id)
        if c.plugin is not None:
            plugin_calls += 1
            kind = "mcp" if c.mcp is not None else "skill"
            p = plugins.setdefault((c.plugin, kind), {
                "plugin": c.plugin, "kind": kind, "calls": 0,
            })
            p["calls"] += 1
            _touch(p, f"plugin:{c.plugin}/{kind}", session_id)

    def _ranked(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        # Calls descending, then name ascending so equal counts are stable.
        return sorted(values, key=lambda d: (-d["calls"],
                                             d.get("server") or d.get("plugin") or ""))

    mcp_block: dict[str, Any] = {
        "calls": mcp_calls,
        "result_chars": mcp_chars,
        "by_provenance": provenance,
        "servers": _ranked(servers.values()),
        "tools": _ranked(tools.values()),
    }
    plugins_block: dict[str, Any] = {"calls": plugin_calls, "items": _ranked(plugins.values())}
    if with_sessions:
        mcp_block["sessions"] = len(
            {sid for key, ids in seen.items() if key.startswith("server:") for sid in ids}
        )
        plugins_block["sessions"] = len(
            {sid for key, ids in seen.items() if key.startswith("plugin:") for sid in ids}
        )
    return mcp_block, plugins_block
```

Confirm `from collections.abc import Iterable` is imported at the top of `report.py`; add it if missing.

- [ ] **Step 4: Call it from `summary()`**

In `summary()`, immediately after the existing `tools = [...]` list comprehension, add:

```python
    usage_rows = conn.execute(
        f"""SELECT c.session_id AS session_id, c.tool_name AS tool_name,
                   c.qualifier AS qualifier, c.result_chars AS result_chars
            FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id{where}""",
        params,
    ).fetchall()
    mcp_block, plugins_block = _usage_blocks(usage_rows, with_sessions=True)
```

Then add `"mcp": mcp_block, "plugins": plugins_block,` to the dict `summary()` returns, beside the existing `"tools": tools` entry.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q`
Expected: PASS — 110 prior plus 2 new = 112 passed.

- [ ] **Step 6: Commit**

```bash
git add plugins/chronicle/scripts/report.py tests/chronicle/test_report.py
git commit -m "feat(chronicle): mcp and plugin usage blocks in summary"
```

---

### Task 4: The same blocks in `session_detail()`

What the drawer reads. Reuses Task 3's helper with `with_sessions=False`.

**Files:**
- Modify: `plugins/chronicle/scripts/report.py` (`session_detail`, ~line 205 — add after `detail["tools"]`)
- Test: `tests/chronicle/test_report.py`

**Interfaces:**
- Consumes: `report._usage_blocks` (Task 3).
- Produces: `session_detail()["mcp"]` and `["plugins"]`, both without a `sessions` key. Task 7 renders them.

- [ ] **Step 1: Write the failing test**

Append to the existing `TestSessionDetail` class in `tests/chronicle/test_report.py` (if the class is named differently, add to whichever class already covers `session_detail`):

```python
    def test_mcp_and_plugin_blocks_per_session(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0, tools=[
            "mcp__plugin_linear_linear__save_issue",
            "mcp__claude_ai_Notion__notion-fetch",
            ("Skill", {"skill": "overseer:ledger"}),
            "Read",
        ]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        detail = report.session_detail(conn, "s1")
        assert detail["mcp"]["calls"] == 2
        assert detail["mcp"]["by_provenance"] == {"plugin": 1, "connector": 1}
        # Single-session read: a `sessions` count would always be 1, so it is
        # omitted rather than rendered as noise.
        assert "sessions" not in detail["mcp"]
        assert detail["plugins"]["items"] == [
            {"plugin": "linear", "kind": "mcp", "calls": 1},
            {"plugin": "overseer", "kind": "skill", "calls": 1},
        ]

    def test_blocks_are_empty_not_missing_for_a_session_with_no_mcp(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["Bash"]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        detail = report.session_detail(conn, "s1")
        assert detail["mcp"] == {"calls": 0, "result_chars": 0, "by_provenance": {},
                                 "servers": [], "tools": []}
        assert detail["plugins"] == {"calls": 0, "items": []}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle/test_report.py -k mcp_and_plugin_blocks_per_session -q`
Expected: FAIL — `KeyError: 'mcp'`

- [ ] **Step 3: Write the implementation**

In `session_detail()`, immediately after the `detail["tools"] = [...]` assignment, add:

```python
    detail["mcp"], detail["plugins"] = _usage_blocks(
        conn.execute(
            """SELECT session_id, tool_name, qualifier, result_chars FROM tool_calls
               WHERE session_id = ?""",
            (session_id,),
        ).fetchall(),
        with_sessions=False,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q`
Expected: PASS — 112 prior plus 2 new = 114 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/chronicle/scripts/report.py tests/chronicle/test_report.py
git commit -m "feat(chronicle): mcp and plugin usage blocks in session detail"
```

---

### Task 5: Frontend types and the shared panel component

One presentational component, mounted twice in Tasks 6 and 7.

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/api/types.ts` (after `ChronicleTool`, ~line 404; then `ChronicleSummary` ~line 458 and `ChronicleSessionDetail` ~line 556)
- Create: `plugins/overseer/dashboard/frontend/src/components/chronicle/UsagePanel.tsx`
- Test: `plugins/overseer/dashboard/frontend/src/components/chronicle/UsagePanel.test.tsx`

**Interfaces:**
- Consumes: the payload shapes from Tasks 3 and 4.
- Produces: types `ChronicleMcpServer`, `ChronicleMcpTool`, `ChronicleMcp`, `ChroniclePluginItem`, `ChroniclePlugins`; optional fields `mcp?` / `plugins?` on both `ChronicleSummary` and `ChronicleSessionDetail`; and the component `UsagePanel({ title, subtitle, rows, hue, emptyHint })` where `rows: { label: string; value: number; detail?: string }[]`. Tasks 6 and 7 import all of these.

- [ ] **Step 1: Add the types**

In `src/api/types.ts`, after the `ChronicleTool` interface:

```ts
export interface ChronicleMcpServer {
  server: string;
  /** "plugin" | "connector" | "local" — where the server comes from. */
  provenance: string;
  tools: number;
  calls: number;
  result_chars: number;
  /** Absent on a single-session read, where it would always be 1. */
  sessions?: number;
}

export interface ChronicleMcpTool {
  server: string;
  tool: string;
  calls: number;
  result_chars: number;
  sessions?: number;
}

export interface ChronicleMcp {
  calls: number;
  result_chars: number;
  by_provenance: Record<string, number>;
  servers: ChronicleMcpServer[];
  tools: ChronicleMcpTool[];
  sessions?: number;
}

export interface ChroniclePluginItem {
  plugin: string;
  /** "mcp" | "skill" — how this plugin was used. */
  kind: string;
  calls: number;
  sessions?: number;
}

export interface ChroniclePlugins {
  calls: number;
  items: ChroniclePluginItem[];
  sessions?: number;
}
```

Then add `mcp?: ChronicleMcp;` and `plugins?: ChroniclePlugins;` to `ChronicleSummary`, and the same two optional fields to `ChronicleSessionDetail`.

- [ ] **Step 2: Write the failing test**

Create `src/components/chronicle/UsagePanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsagePanel from "./UsagePanel";

describe("UsagePanel", () => {
  it("renders a heading, subtitle and one row per entry", () => {
    render(
      <UsagePanel
        title="MCP"
        subtitle="2,488 calls across 51 sessions"
        rows={[
          { label: "playwright", value: 1621, detail: "17 tools" },
          { label: "claude-in-chrome", value: 303 },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "MCP" })).toBeInTheDocument();
    expect(screen.getByText("2,488 calls across 51 sessions")).toBeInTheDocument();
    expect(screen.getByText("playwright")).toBeInTheDocument();
    expect(screen.getByText("claude-in-chrome")).toBeInTheDocument();
  });

  it("shows the empty hint rather than a bare zero when there is nothing", () => {
    render(
      <UsagePanel
        title="Plugins"
        subtitle="none recorded"
        rows={[]}
        emptyHint="Run `chronicle sync --full` to backfill plugin usage."
      />,
    );
    expect(screen.getByText(/chronicle sync --full/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd plugins/overseer/dashboard/frontend && npx vitest run src/components/chronicle/UsagePanel.test.tsx`
Expected: FAIL — cannot resolve `./UsagePanel`

- [ ] **Step 4: Write the component**

Create `src/components/chronicle/UsagePanel.tsx`:

```tsx
import { formatTokens } from "../../board/chronicle/format";
import { BarList } from "./ChronicleCharts";

interface UsagePanelProps {
  title: string;
  /** One line naming what is counted — including any deliberate overlap. */
  subtitle: string;
  rows: { label: string; value: number; detail?: string }[];
  hue?: string;
  /** Shown instead of an empty chart. An unbackfilled store has no plugin
   * rows, and a bare zero there reads as "you use no plugins" — which is a
   * different claim from "we have not looked yet". */
  emptyHint?: string;
}

export default function UsagePanel({
  title,
  subtitle,
  rows,
  hue = "--chr-tools",
  emptyHint,
}: UsagePanelProps) {
  return (
    <section className="chr-panel" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <h3 className="chr-panel__title">{title}</h3>
      <p className="chr-panel__sub">{subtitle}</p>
      {rows.length === 0 && emptyHint ? (
        <p className="chr-chart__empty">{emptyHint}</p>
      ) : (
        <BarList rows={rows} format={formatTokens} title={title} hue={hue} />
      )}
    </section>
  );
}
```

If `formatTokens` is not exported from `src/board/chronicle/format`, check `ChroniclePage.tsx`'s import line for the correct path and use that.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd plugins/overseer/dashboard/frontend && npx vitest run src/components/chronicle/UsagePanel.test.tsx`
Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/api/types.ts \
        plugins/overseer/dashboard/frontend/src/components/chronicle/UsagePanel.tsx \
        plugins/overseer/dashboard/frontend/src/components/chronicle/UsagePanel.test.tsx
git commit -m "feat(dashboard): shared usage panel for mcp and plugin breakdowns"
```

---

### Task 6: Mount both panels on the Chronicle page

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.tsx` (StatTile row ~lines 197–221; new sections after the "Tool calls" panel at ~lines 307–319)
- Test: `plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.test.tsx`

**Interfaces:**
- Consumes: `UsagePanel` and the types from Task 5; `summary.mcp` / `summary.plugins` from Task 3.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Append to `ChroniclePage.test.tsx`, following whatever fixture/mock helper the existing tests in that file use to supply a summary (read the top of the file first and reuse it rather than inventing a new one):

```tsx
  it("renders the MCP and plugin panels from the summary", async () => {
    // Extend the existing summary fixture this file already uses.
    renderPage({
      summary: {
        ...baseSummary,
        mcp: {
          calls: 4, sessions: 1, result_chars: 900,
          by_provenance: { plugin: 2, connector: 1, local: 1 },
          servers: [
            { server: "plugin_playwright_playwright", provenance: "plugin",
              tools: 1, calls: 2, sessions: 1, result_chars: 500 },
            { server: "claude-in-chrome", provenance: "local",
              tools: 1, calls: 1, sessions: 1, result_chars: 400 },
          ],
          tools: [],
        },
        plugins: {
          calls: 3, sessions: 1,
          items: [
            { plugin: "playwright", kind: "mcp", calls: 2, sessions: 1 },
            { plugin: "tribunal", kind: "skill", calls: 1, sessions: 1 },
          ],
        },
      },
    });

    expect(await screen.findByRole("heading", { name: "MCP" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Plugins" })).toBeInTheDocument();
    expect(screen.getByText("plugin_playwright_playwright")).toBeInTheDocument();
    expect(screen.getByText("tribunal · skill")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd plugins/overseer/dashboard/frontend && npx vitest run src/components/chronicle/ChroniclePage.test.tsx`
Expected: FAIL — no heading named "MCP".

- [ ] **Step 3: Add the StatTiles**

In `ChroniclePage.tsx`, add `import UsagePanel from "./UsagePanel";` beside the existing `StatTile` import, then add two tiles to the tile row after the existing `Tool calls` tile:

```tsx
            <StatTile label="MCP calls" value={formatTokens(summary?.mcp?.calls ?? 0)} hue="--chr-tools" />
            <StatTile label="Plugin calls" value={formatTokens(summary?.plugins?.calls ?? 0)} hue="--chr-peak" />
```

- [ ] **Step 4: Add the two panels**

Immediately after the closing `</section>` of the existing "Tool calls" panel:

```tsx
            <UsagePanel
              title="MCP"
              subtitle={`${summary?.mcp?.calls ?? 0} calls across ${summary?.mcp?.sessions ?? 0} sessions — by server.`}
              rows={(summary?.mcp?.servers ?? []).slice(0, 10).map((s) => ({
                label: s.server,
                detail: `${s.provenance} · ${s.tools} tools · ${s.calls} calls`,
                value: s.calls,
              }))}
              hue="--chr-tools"
              emptyHint="No MCP calls in this window."
            />
            <UsagePanel
              title="Plugins"
              subtitle="Plugin-provided MCP servers and plugin skills. A plugin's MCP calls are also counted in the MCP panel."
              rows={(summary?.plugins?.items ?? []).slice(0, 10).map((p) => ({
                label: `${p.plugin} · ${p.kind}`,
                detail: `${p.calls} calls across ${p.sessions ?? "?"} sessions`,
                value: p.calls,
              }))}
              hue="--chr-peak"
              emptyHint="No plugin usage recorded. Historical sessions need a `chronicle sync --full` to backfill."
            />
```

- [ ] **Step 5: Run the frontend tests and the type check**

Run: `cd plugins/overseer/dashboard/frontend && npm run test && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.tsx \
        plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.test.tsx
git commit -m "feat(dashboard): MCP and plugin panels on the Chronicle page"
```

---

### Task 7: Mount both panels in the session drawer, and rebuild `dist/`

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/chronicle/SessionDrawer.tsx` (after the "Tools" panel, ~lines 232–240)
- Test: `plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.test.tsx` (the drawer is exercised from there; if a dedicated `SessionDrawer.test.tsx` exists by now, use it)
- Modify: `plugins/overseer/dashboard/frontend/dist/**` (build output — committed)

**Interfaces:**
- Consumes: `UsagePanel` (Task 5), `detail.mcp` / `detail.plugins` (Task 4).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add a test that opens the drawer for a session whose detail carries the blocks, following the existing drawer-opening pattern already in the test file:

```tsx
  it("renders the MCP and plugin panels in the session drawer", async () => {
    renderPage({
      detail: {
        ...baseDetail,
        mcp: {
          calls: 2, result_chars: 100,
          by_provenance: { plugin: 1, connector: 1 },
          servers: [
            { server: "plugin_linear_linear", provenance: "plugin",
              tools: 1, calls: 1, result_chars: 60 },
            { server: "claude_ai_Notion", provenance: "connector",
              tools: 1, calls: 1, result_chars: 40 },
          ],
          tools: [],
        },
        plugins: {
          calls: 2,
          items: [
            { plugin: "linear", kind: "mcp", calls: 1 },
            { plugin: "overseer", kind: "skill", calls: 1 },
          ],
        },
      },
    });
    await openDrawer();

    expect(await screen.findByText("plugin_linear_linear")).toBeInTheDocument();
    expect(screen.getByText("overseer · skill")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd plugins/overseer/dashboard/frontend && npx vitest run src/components/chronicle/ChroniclePage.test.tsx`
Expected: FAIL — `plugin_linear_linear` is not rendered.

- [ ] **Step 3: Add the panels to the drawer**

In `SessionDrawer.tsx`, add `import UsagePanel from "./UsagePanel";` beside the existing chart imports, then after the closing `</section>` of the "Tools" panel:

```tsx
            <UsagePanel
              title="MCP"
              subtitle={`${detail.mcp?.calls ?? 0} calls in this session — by server.`}
              rows={(detail.mcp?.servers ?? []).map((s) => ({
                label: s.server,
                detail: `${s.provenance} · ${s.tools} tools`,
                value: s.calls,
              }))}
              hue="--chr-tools"
              emptyHint="No MCP calls in this session."
            />
            <UsagePanel
              title="Plugins"
              subtitle="Plugin MCP servers and plugin skills used in this session."
              rows={(detail.plugins?.items ?? []).map((p) => ({
                label: `${p.plugin} · ${p.kind}`,
                value: p.calls,
              }))}
              hue="--chr-peak"
              emptyHint="No plugin usage recorded. Older sessions need a `chronicle sync --full` to backfill."
            />
```

- [ ] **Step 4: Run every suite**

Run:
```bash
PYTHONPATH=plugins/chronicle .venv/bin/pytest tests/chronicle -q
.venv/bin/pytest plugins/overseer/dashboard/backend/tests -q
cd plugins/overseer/dashboard/frontend && npm run test && npx tsc --noEmit
```
Expected: all PASS. The backend suite is included because `main.py` proxies the chronicle CLI's JSON straight through — the new keys should ride along untouched, and this proves nothing validates the payload shape too narrowly.

- [ ] **Step 5: Rebuild the committed frontend bundle**

Run: `cd plugins/overseer/dashboard/frontend && npm run build`

This rewrites `dist/`, including `dist/.srchash` and a content-hashed `dist/assets/index-*.js`. The old asset file is replaced — `git add -A` the `dist/` directory so the deletion is staged too.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/chronicle/SessionDrawer.tsx \
        plugins/overseer/dashboard/frontend/src/components/chronicle/ChroniclePage.test.tsx
git add -A plugins/overseer/dashboard/frontend/dist
git commit -m "feat(dashboard): MCP and plugin panels in the session drawer"
```

- [ ] **Step 7: Backfill the real store (manual, once)**

Not part of any test. To populate `qualifier` for the 216 historical sessions:

```bash
PYTHONPATH=plugins/chronicle .venv/bin/python -m scripts.cli sync --full
```

Until this is run against a given store, MCP figures are already correct (they derive from `tool_name`, which was never discarded) and plugin *skill* rows are empty — which is exactly what the `emptyHint` copy explains.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 1. Store: `qualifier` column | Task 2 |
| 2. Ingest keeps the qualifier | Task 2 |
| 3. Backfill via `sync --full` | Task 7, Step 7 (+ the ingest test in Task 2 that runs `full=True`) |
| 4. Classification, one function | Task 1 |
| Deliberate overlap | Task 1 (test), Task 3 (test), Tasks 6/7 (subtitle copy) |
| 5. `mcp`/`plugins` in `summary` | Task 3 |
| 5. `mcp`/`plugins` in `session_detail` | Task 4 |
| 6. Frontend types + component | Task 5 |
| 6. ChroniclePage mount + StatTiles | Task 6 |
| 6. SessionDrawer mount | Task 7 |
| Empty state for an unbackfilled store | Task 5 (component + test), Tasks 6/7 (copy) |
| Testing: classifier, transcript, report, components | Tasks 1, 2, 3, 4, 5, 6, 7 |
| Out of scope: context composition | not planned, by design |

No gaps.

**Type consistency:** `classify` / `McpRef` / `Classified` (Task 1) are used unchanged in Tasks 3 and 4. `_usage_blocks(rows, *, with_sessions)` is defined in Task 3 and called in Task 4 with the same signature. `tool_uses` becomes a 3-tuple in Task 2, and Task 2 Step 6 explicitly greps for other unpack sites. `UsagePanel`'s prop names (`title`, `subtitle`, `rows`, `hue`, `emptyHint`) are identical across Tasks 5, 6 and 7. `BarList`'s row shape (`{ label, value, detail? }`) matches the real signature in `ChronicleCharts.tsx:227`.

**Note on test-fixture names:** Tasks 6 and 7 reference `renderPage`, `baseSummary`, `baseDetail` and `openDrawer` as stand-ins for whatever helpers `ChroniclePage.test.tsx` already defines. Read the top of that file first and reuse the real names — do not add parallel helpers.
