"""Finding a sibling plugin, in either layout.

The dashboard reaches vigil, census and chronicle by subprocess to a sibling
plugin's CLI. It used to locate them by walking up a FIXED number of parents
to a directory it assumed was `plugins/` — true of a repo checkout, false
once installed, because the marketplace inserts a version directory:

    repo       plugins/overseer/dashboard/backend/app/   -> parents[4] = plugins/
    installed  cache/<mkt>/overseer/0.15.0/.../app/      -> parents[4] = .../overseer/

So every marketplace install resolved `overseer/chronicle/scripts/cli.py`,
which never exists, and silently reported the plugin as absent — the Chronicle
page never appeared, and the vigil and census integrations were dead. Nothing
caught it because the only tests ran from the checkout, where it passes.
"""
from __future__ import annotations

from pathlib import Path

from app.cli_client import find_plugin


def _cli(root: Path, *parts: str) -> Path:
    """Create `<root>/<parts...>/scripts/cli.py` and return the CLI path."""
    target = root.joinpath(*parts, "scripts")
    target.mkdir(parents=True, exist_ok=True)
    cli = target / "cli.py"
    cli.write_text("# stub\n")
    return cli


def _caller(root: Path, *parts: str) -> Path:
    """The `backend/app/cli_client.py` position inside a plugin root."""
    app = root.joinpath(*parts, "dashboard", "backend", "app")
    app.mkdir(parents=True, exist_ok=True)
    return app / "cli_client.py"


class TestRepoCheckoutLayout:
    def test_finds_a_sibling_under_plugins(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        want = _cli(plugins, "chronicle")
        _cli(plugins, "overseer")
        assert find_plugin("chronicle", _from=_caller(plugins, "overseer")) == want


class TestMarketplaceCacheLayout:
    def test_finds_a_sibling_behind_its_version_directory(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache" / "pip-skills"
        want = _cli(cache, "chronicle", "0.5.0")
        _cli(cache, "overseer", "0.23.0")
        caller = _caller(cache, "overseer", "0.23.0")
        assert find_plugin("chronicle", _from=caller) == want

    def test_prefers_the_highest_installed_version(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache" / "pip-skills"
        # Old versions linger in the cache (all marked `.in_use`), so "the
        # first one found" would pin whichever the filesystem happened to
        # list first — 0.10.0 sorts before 0.9.0 as a string, so this also
        # pins that the comparison is numeric, not lexical.
        for v in ("0.4.0", "0.9.0", "0.10.0"):
            _cli(cache, "chronicle", v)
        want = cache / "chronicle" / "0.10.0" / "scripts" / "cli.py"
        caller = _caller(cache, "overseer", "0.23.0")
        assert find_plugin("chronicle", _from=caller) == want

    def test_ignores_a_version_directory_with_no_cli(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache" / "pip-skills"
        (cache / "chronicle" / "9.9.9").mkdir(parents=True)   # half-removed install
        want = _cli(cache, "chronicle", "0.5.0")
        caller = _caller(cache, "overseer", "0.23.0")
        assert find_plugin("chronicle", _from=caller) == want


class TestAbsent:
    def test_returns_none_when_the_plugin_is_not_installed(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        _cli(plugins, "overseer")
        assert find_plugin("chronicle", _from=_caller(plugins, "overseer")) is None

    def test_never_matches_the_caller_s_own_plugin_directory(self, tmp_path: Path) -> None:
        # Walking up must not find `overseer/overseer`, nor treat the plugin
        # root itself as a sibling of the same name.
        plugins = tmp_path / "plugins"
        want = _cli(plugins, "overseer")
        assert find_plugin("overseer", _from=_caller(plugins, "overseer")) == want


class TestLiveLayout:
    def test_resolves_the_real_siblings_from_this_checkout(self) -> None:
        for name in ("chronicle", "vigil", "census"):
            assert find_plugin(name) is not None, f"{name} not found from the live layout"
