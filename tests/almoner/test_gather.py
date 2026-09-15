import json
import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import gather, paths, store
from scripts.config import Source
from scripts.gather import AdapterError, FetchResult, Window
from scripts.model import InMessage, conversation

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp()
NOTION = Source("notion", "api", "notion", "work")


def _secret(label: str) -> None:
    path = paths.secret_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("invented-token")
    os.chmod(path, 0o600)


def _item(pid: str, source: str = "notion"):
    at = datetime.fromtimestamp(NOW, timezone.utc) - timedelta(hours=1)
    return conversation(id=f"shared:{pid}", source=source, context="work", title=pid,
                        messages=[InMessage(text="hi", at=at, who="Rhona Baird", mine=False)])


class Fake:
    def __init__(self, result=None, exc=None, block: threading.Event | None = None):
        self.result, self.exc, self.block, self.windows = result, exc, block, []

    def fetch(self, window: Window) -> FetchResult:
        self.windows.append(window)
        if self.block is not None:
            self.block.wait(5)
        if self.exc is not None:
            raise self.exc
        return self.result


def _registry(fake):
    return {("notion", "api"): lambda source, secret: fake}


class TestWindow:
    def test_hours_bound_the_first_fetch(self):
        w = gather.fetch_window(NOW, 48, None)
        assert w.until.timestamp() == NOW and w.since.timestamp() == NOW - 48 * 3600

    def test_watermark_narrows_but_keeps_an_overlap(self):
        w = gather.fetch_window(NOW, 48, NOW - 600)
        assert w.since.timestamp() == NOW - 600 - gather.OVERLAP_S


class TestDegrade:
    def test_missing_credentials_names_the_source_and_fetches_nothing(self):
        conn = store.connect()
        fake = Fake(result=FetchResult(items=[]))
        out = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW, registry=_registry(fake))
        [report] = out.reports
        assert (report.ok, report.error) == (False, "no credentials") and fake.windows == []

    def test_unsupported_transport_is_reported(self):
        conn = store.connect()
        src = Source("slack", "agent", "slack", "work")
        _secret("slack")
        [report] = gather.gather_and_store(conn, [src], hours=48, now=NOW, registry={}).reports
        assert report.error == "unsupported source: slack via agent"

    def test_adapter_error_is_shown_but_unexpected_errors_are_not_echoed(self):
        conn = store.connect()
        _secret("notion")
        [r1] = gather.gather_and_store(
            conn, [NOTION], hours=48, now=NOW,
            registry=_registry(Fake(exc=AdapterError("notion 401")))).reports
        [r2] = gather.gather_and_store(
            conn, [NOTION], hours=48, now=NOW,
            registry=_registry(Fake(exc=RuntimeError("token=secret")))).reports
        assert r1.error == "notion 401"
        assert r2.error == "failed: RuntimeError" and "secret" not in (r2.error or "")

    def test_a_wedged_source_times_out_without_holding_the_digest(self):
        conn = store.connect()
        _secret("notion")
        release = threading.Event()
        fake = Fake(result=FetchResult(items=[]), block=release)
        try:
            [report] = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW,
                                               registry=_registry(fake), timeout=0.2).reports
        finally:
            release.set()
        assert (report.ok, report.error) == (False, "timed out")

    def test_adapter_construction_failure_is_reported_and_others_still_gather(self):
        conn = store.connect()
        _secret("notion")
        _secret("notion2")
        healthy = Fake(result=FetchResult(items=[]))
        second = Source("notion", "api", "notion2", "home")

        def factory(source, secret):
            if source.label == "notion":
                raise AdapterError("notion: bad config")
            return healthy

        out = gather.gather_and_store(conn, [NOTION, second], hours=48, now=NOW,
                                      registry={("notion", "api"): factory})
        reports = {r.label: r for r in out.reports}
        assert reports["notion"].error == "notion: bad config"
        assert reports["notion2"].ok

    def test_adapter_construction_error_never_echoes_the_secret(self):
        conn = store.connect()
        _secret("notion")

        def bad_factory(source, secret):
            raise ValueError(f"bad token: {secret}")

        [report] = gather.gather_and_store(
            conn, [NOTION], hours=48, now=NOW,
            registry={("notion", "api"): bad_factory}).reports
        assert report.error == "failed: ValueError"
        assert "invented-token" not in json.dumps(report.to_json())


class TestProcessExit:
    def test_a_wedged_source_does_not_block_the_process_at_exit(self, tmp_path):
        home = tmp_path / "config" / "almoner"
        secret = home / "secrets" / "notion"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("invented-token")
        os.chmod(secret, 0o600)

        script = textwrap.dedent("""
            import threading

            from scripts import gather, store
            from scripts.config import Source
            from scripts.gather import FetchResult, Window

            class Wedged:
                def fetch(self, window: Window) -> FetchResult:
                    threading.Event().wait()  # never set: this thread never returns
                    return FetchResult(items=[])

            conn = store.connect()
            source = Source("notion", "api", "notion", "work")
            registry = {("notion", "api"): lambda source, secret: Wedged()}
            out = gather.gather_and_store(conn, [source], hours=48, now=1000.0,
                                          registry=registry, timeout=0.2)
            print(out.reports[0].error)
        """)
        almoner_dir = Path(__file__).resolve().parents[2] / "plugins" / "almoner"
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
              "ALMONER_HOME": str(home), "ALMONER_DB": str(home / "almoner.db")}
        result = subprocess.run([sys.executable, "-c", script], cwd=almoner_dir, env=env,
                                capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == 0, result.stderr
        assert "timed out" in result.stdout


class TestPersist:
    def test_items_suppressions_watermark_and_run_are_stored(self):
        conn = store.connect()
        _secret("notion")
        fake = Fake(result=FetchResult(items=[_item("p1")],
                                       suppressed=[("notion:p2", "notion:no-open-comments")],
                                       cursor="c"))
        out = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW, registry=_registry(fake))
        assert out.items_out == 1 and out.suppressed == 1
        assert out.reports[0].ok and out.reports[0].watermark == NOW
        assert store.get_watermark(conn, "notion") == NOW
        assert [r["id"] for r in store.read_digest(conn, days=14, now=NOW)] == ["shared:p1"]
        assert store.log_runs(conn)["runs"][0]["items_out"] == 1

    def test_the_same_event_from_two_sources_is_one_row_seen_in_both(self):
        conn = store.connect()
        _secret("notion")
        _secret("notion2")
        second = Source("notion", "api", "notion2", "home")
        fakes = iter([Fake(result=FetchResult(items=[_item("p1", source="notion")])),
                      Fake(result=FetchResult(items=[_item("p1", source="mail")]))])
        registry = {("notion", "api"): lambda source, secret: next(fakes)}
        out = gather.gather_and_store(conn, [NOTION, second], hours=48, now=NOW,
                                      registry=registry)
        [row] = store.read_digest(conn, days=14, now=NOW)
        assert out.items_out == 1 and row["seen_in"] == ["notion", "mail"]
