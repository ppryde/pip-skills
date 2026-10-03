from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

# One table of Claude Code entrypoints and whether each is headless (None = unknown),
# shared by every layer that interprets CLAUDE_CODE_ENTRYPOINT.
ENTRYPOINT_HEADLESS = [
    ("sdk-cli", True), ("sdk-ts", True), ("sdk-py", True),
    ("cli", False), ("claude-vscode", False), ("claude-desktop", False), ("mystery", None)]

SKILL = Path(__file__).resolve().parents[2] / "skills" / "context-vigil"
LAUNCHER = SKILL / "scripts" / "context-vigil"

_STRIP = ("TMUX", "TMUX_PANE", "CLAUDE_PROJECT_DIR", "ZDOTDIR", "CLAUDE_SESSION_ID",
          "CLAUDE_CODE_ENTRYPOINT")

# Captured at import, before any monkeypatch, so they name the developer's real files.
_REAL_HOME = Path(os.path.expanduser("~"))
_REAL_ZDOTDIR = os.environ.get("ZDOTDIR")
_REAL_RCS = [_REAL_HOME / name for name in (".zshrc", ".bashrc", ".bash_profile", ".profile")]
if _REAL_ZDOTDIR:
    _REAL_RCS.append(Path(_REAL_ZDOTDIR) / ".zshrc")
# Claude settings files install/uninstall would edit if the pinning ever failed.
_REAL_RCS += [_REAL_HOME / ".claude" / "settings.json",
              _REAL_HOME / ".claude-personal" / "settings.json"]


# Secret-shaped names: scrubbed from every test's environment by ``iso``, and the
# real values (captured once, at import, held only in memory and never printed) are
# what ``no_real_secret_recorded`` hunts for in everything a test leaves on disk and
# everything it prints. Generic patterns plus the common names they miss.
#
# Never run this suite with `pytest -l` / `--showlocals` while real keys are exported:
# a failure would print frame locals. ``pytest_configure`` refuses the flag outright
# whenever a secret-shaped variable is set. (`-p no:cacheprovider` is safe either way:
# the cache holds test ids, which carry only the FAKE canaries.)
SECRET_NAME = re.compile(
    r"(KEY|TOKEN|SECRET|PASSW|PASSPHRASE|CREDENTIAL|AUTH|COOKIE|PRIVATE|CERT|DSN|WEBHOOK"
    r"|_PAT$|^PAT$|_PWD$|^PGPASS|DATABASE_URL|REDIS_URL|MONGO.*URL|AMQP_URL|_URI$)",
    re.IGNORECASE)
_SCRUB_PREFIXES = ("ANTHROPIC_", "AWS_", "OPENAI_", "GITHUB_", "GH_", "NPM_", "AZURE_",
                   "GOOGLE_", "GCP_", "GCLOUD_", "SLACK_", "STRIPE_", "HF_", "HUGGING",
                   "SENTRY_", "TWILIO_", "DOCKER_", "VAULT_", "DATADOG_", "DD_")
_MIN_SECRET_LEN = 8   # shorter values ("1", "true") are not secrets and would false-positive


def is_secret_name(name: str) -> bool:
    """A variable ``iso`` removes from every test's environment."""
    return name.upper().startswith(_SCRUB_PREFIXES) or bool(SECRET_NAME.search(name))


class Secrets(tuple):  # type: ignore[type-arg]
    """Real secret values, held as bytes. Its repr is ``<redacted>`` so that no
    failure report, ``-l`` frame dump or assertion rewrite can print one."""

    def __repr__(self) -> str:
        return "<redacted>"

    __str__ = __repr__


_REAL_SECRETS = Secrets(
    value.encode("utf-8", "surrogateescape") for name, value in os.environ.items()
    if SECRET_NAME.search(name) and len(value) >= _MIN_SECRET_LEN)


def check_showlocals(showlocals: bool, secrets: Secrets) -> None:
    """Refuse `-l`/`--showlocals` while real secret values are in the environment."""
    if showlocals and secrets:
        raise pytest.UsageError(
            "--showlocals is refused here: secret-shaped environment variables are set "
            "and a failure would print frame locals. Unset them or drop -l.")


def pytest_configure(config: pytest.Config) -> None:
    check_showlocals(bool(config.getoption("showlocals", False)), _REAL_SECRETS)


def leaked_text(text: str, secrets: Secrets) -> bool:
    """True when ``text`` holds any of ``secrets`` (compared in-process, never shown)."""
    data = text.encode("utf-8", "surrogateescape")
    return any(s in data for s in secrets)


def leaked_files(root: Path, secrets: Secrets) -> list[Path]:
    """Files under ``root`` that contain any of ``secrets`` (compared in-process)."""
    if not secrets:
        return []
    hits: list[Path] = []
    for path in root.rglob("*"):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if any(s in data for s in secrets):
            hits.append(path)
    return hits


@pytest.fixture(autouse=True)
def no_real_secret_recorded(tmp_path: Path):
    """Fail if any file a test (or a stub it ran) wrote holds a real secret env value.

    Names the file only: the value itself is never printed. Any error inside the
    guard is reported as a bare "guard error" (its traceback could hold a value)."""
    yield
    try:
        hits = leaked_files(tmp_path, _REAL_SECRETS)
    except BaseException:
        pytest.fail("secret guard error while scanning tmp_path", pytrace=False)
    if hits:
        pytest.fail("a real secret env value was recorded in: "
                    + ", ".join(str(p.relative_to(tmp_path)) for p in hits), pytrace=False)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):  # type: ignore[type-arg]
    """The same guard over what the test printed (captured stdout/stderr)."""
    outcome = yield
    report = outcome.get_result()
    try:
        leaked = bool(_REAL_SECRETS) and leaked_text(
            report.capstdout + report.capstderr, _REAL_SECRETS)
    except BaseException:
        leaked = True
    if leaked:
        report.outcome = "failed"
        report.longrepr = "a real secret env value reached the captured stdout/stderr"
        report.sections = [(k, "<withheld>") for k, _ in report.sections]


def _snapshot() -> dict[Path, tuple[bool, int, int]]:
    snap: dict[Path, tuple[bool, int, int]] = {}
    for rc in _REAL_RCS:
        try:
            st = rc.stat()
            snap[rc] = (True, st.st_mtime_ns, st.st_size)
        except OSError:
            snap[rc] = (False, 0, 0)
    return snap


@pytest.fixture(autouse=True)
def real_rc_tripwire():
    """Fail loudly if any test touches the developer's real shell rc and Claude settings files."""
    before = _snapshot()
    yield
    after = _snapshot()
    for rc, state in before.items():
        if after[rc] != state:
            pytest.fail(f"test modified real user file: {rc}")


@pytest.fixture(autouse=True)
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin every state root into tmp_path and strip tmux + context-vigil env.

    The developer runs this suite inside tmux: an inherited TMUX/TMUX_PANE
    would let a dispatch path type real keystrokes into their pane, and an
    unpinned CLAUDE_CONFIG_DIR would write into their real ~/.claude*.
    CONTEXT_VIGIL_TMUX_BIN names a missing binary: only a test's own stub is reachable.
    Secret-shaped names (and every ANTHROPIC_* / AWS_*) are removed too, so no
    subprocess or stub a test runs can ever see, log or echo a real credential.
    """
    for var in list(os.environ):
        if var.startswith("CONTEXT_VIGIL_") or var in _STRIP or is_secret_name(var):
            monkeypatch.delenv(var, raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "claude").mkdir()
    (tmp_path / "tmpdir").mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmpdir"))   # subprocess temp files too
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(tmp_path / "no-tmux-here"))
    return tmp_path


@pytest.fixture
def home(iso: Path) -> Path:
    return iso / "home"


@pytest.fixture
def cfg(iso: Path) -> Path:
    return iso / "claude"


@pytest.fixture
def repo(iso: Path) -> Path:
    path = iso / "repo"
    path.mkdir()
    return path


# ``iso`` strips the ones in _STRIP, so only a value a test set itself gets through.
_CLI_ENV_ALLOW = ("PATH", "HOME", "SHELL", "TMPDIR", "LANG", "USER", "LOGNAME", "TERM",
                  "CLAUDE_CONFIG_DIR", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", *_STRIP)


def cli_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """An explicit, minimal environment for a CLI subprocess: the allow-listed names
    (all pinned into tmp_path by ``iso`` where they matter), CONTEXT_VIGIL_*, LC_*,
    plus whatever the test sets — never the developer's ambient environment."""
    env = {k: v for k, v in os.environ.items()
           if k in _CLI_ENV_ALLOW or k.startswith(("CONTEXT_VIGIL_", "LC_"))}
    env.update(extra or {})
    return env


@pytest.fixture
def run_cli():
    def _run(*args: str, stdin: str = "", env: dict[str, str] | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["bash", str(LAUNCHER), *args], input=stdin, capture_output=True,
            text=True, env=cli_env(env), cwd=cwd, timeout=30,
        )
        if _REAL_SECRETS and leaked_text(result.stdout + result.stderr, _REAL_SECRETS):
            pytest.fail("a real secret env value reached the CLI's stdout/stderr",
                        pytrace=False)
        return result
    return _run


# --- shared test data helpers --------------------------------------------------------
# Hoisted from the test files that each redefined them. Nothing above this line (the
# guards: iso, no_real_secret_recorded, real_rc_tripwire, run_cli) was changed.

@pytest.fixture
def store_file(iso: Path) -> Path:
    """Where the census store lives (the data root is pinned into tmp_path by ``iso``)."""
    from context_vigil import paths
    return paths.census_path()


def read_store(store_file: Path) -> dict:
    """The census store as JSON."""
    import json
    return json.loads(store_file.read_text())


def census_payload(sid: str = "s1", cwd: str = "/wt/a", **extra: object) -> str:
    """A minimal status-line payload as the JSON ``census.ingest`` takes."""
    import json
    base: dict = {"session_id": sid, "cwd": cwd}
    base.update(extra)
    return json.dumps(base)


def statusline_payload(repo: Path, sid: str = "s1", pct: float = 42) -> str:
    """A status-line payload reporting ``pct`` for a session in ``repo``."""
    import json
    return json.dumps({"session_id": sid, "workspace": {"current_dir": str(repo)},
                       "context_window": {"used_percentage": pct}})


def read_settings(cfg: Path) -> dict:
    """The pinned ``settings.json`` as JSON."""
    import json
    return json.loads((cfg / "settings.json").read_text())


def write_settings(cfg: Path, data: dict) -> None:
    """Write the pinned ``settings.json`` (2-space indent, trailing newline)."""
    import json
    (cfg / "settings.json").write_text(json.dumps(data, indent=2) + "\n")


@pytest.fixture
def zsh(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """SHELL=zsh with a one-line ``~/.zshrc`` inside the pinned HOME."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n")
    return rc
