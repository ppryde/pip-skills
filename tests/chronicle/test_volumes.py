"""The docker layer: validation, listing, ranged reads, account whitelist, and
every way docker can fail. The subprocess boundary is faked (`fake_docker`);
no test here can reach a real docker."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts import store, volumes
from scripts.volumes import RemoteFile, VolumeError, VolumeSource

from .fake_docker import FakeDocker

MAIN = "-Users-me-repo/s1.jsonl"
SUB = "-Users-me-repo/s1/subagents/agent-a1.jsonl"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    projects = tmp_path / "vol" / ".config" / "claude" / "projects"
    projects.mkdir(parents=True)
    return tmp_path / "vol"


def put(root: Path, relpath: str, body: bytes, mtime: int = 1788260000) -> Path:
    path = root / ".config" / "claude" / "projects" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def docker(root: Path, monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    return FakeDocker({"wf": root}).install(monkeypatch)


class TestValidation:
    @pytest.mark.parametrize(("name", "claude_dir", "message"), [
        ("wf state", ".config/claude", "invalid volume name"),
        ("-wf", ".config/claude", "invalid volume name"),
        ("wf;rm -rf /", ".config/claude", "invalid volume name"),
        ("wf", "-rf", "invalid claude dir"),
        ("wf", "a/../../etc", "invalid claude dir"),
        ("wf", 'a"; rm -rf /', "invalid claude dir"),
        ("wf", "$(id)", "invalid claude dir"),
        ("wf", "/", "invalid claude dir"),
    ])
    def test_injection_shaped_values_never_reach_an_argv(self, docker, name, claude_dir, message):
        with pytest.raises(ValueError, match=message):
            VolumeSource(name, claude_dir)
        assert docker.calls == []

    def test_rejects_an_image_docker_would_read_as_an_option(self, docker):
        with pytest.raises(ValueError, match="invalid image"):
            VolumeSource("wf", image="alpine --privileged")
        with pytest.raises(ValueError, match="invalid image"):
            VolumeSource("wf", image="-v")
        VolumeSource("wf", image="ghcr.io/acme/helper:1.2@sha256:abc")   # registry/tag/digest pass

    def test_normalises_and_labels(self):
        source = VolumeSource("wf-state", "/home/me/.claude/")
        assert (source.name, source.claude_dir, source.label) == (
            "wf-state", "home/me/.claude", "docker://wf-state")
        assert source.key("-r/s.jsonl") == "docker://wf-state/-r/s.jsonl"

    def test_the_claude_dir_travels_as_an_argument_not_in_the_script(self, docker, root):
        put(root, MAIN, b"{}\n")
        VolumeSource("wf").list_files()
        argv, _ = docker.runs(volumes._LIST_SCRIPT)[0]
        assert argv[-1] == ".config/claude" and argv[-2] == "sh"
        assert ".config" not in volumes._LIST_SCRIPT


class TestListing:
    def test_parses_main_and_subagent_files(self, docker, root):
        put(root, MAIN, b"abc\n", mtime=1788260001)
        put(root, SUB, b"defgh\n", mtime=1788260002)
        files = VolumeSource("wf").list_files()
        assert sorted(files, key=lambda f: f.relpath) == [
            RemoteFile(MAIN, 1788260001.0, 4), RemoteFile(SUB, 1788260002.0, 6)]

    def test_one_helper_call_lists_everything(self, docker, root):
        for i in range(5):
            put(root, f"-r/s{i}.jsonl", b"x\n")
        VolumeSource("wf").list_files()
        assert len(docker.runs(volumes._LIST_SCRIPT)) == 1

    def test_paths_outside_the_alphabet_claude_writes_are_ignored(self, docker, root):
        put(root, MAIN, b"x\n")
        put(root, "-r/we ird name.jsonl", b"x\n")
        put(root, "-r/s2/subagents/agent-a$b.jsonl", b"x\n")
        assert [f.relpath for f in VolumeSource("wf").list_files()] == [MAIN]

    def test_unparseable_output_is_a_volume_error(self, monkeypatch, root):
        bad = subprocess.CompletedProcess([], 0, b"garbage\n", b"")
        FakeDocker({"wf": root}, failure=bad).install(monkeypatch)
        with pytest.raises(VolumeError, match="unexpected listing"):
            VolumeSource("wf").list_files()

    def test_an_empty_volume_lists_nothing(self, docker, root):
        assert VolumeSource("wf").list_files() == []

    def test_group_sessions_folds_subagents_and_drops_orphans(self):
        orphan = "-r/gone/subagents/agent-z.jsonl"
        sessions = volumes.group_sessions([
            RemoteFile(SUB, 1, 1), RemoteFile(MAIN, 2, 2), RemoteFile(orphan, 3, 3)])
        assert len(sessions) == 1
        s = sessions[0]
        assert (s.session_id, s.slug, s.main.relpath) == ("s1", "-Users-me-repo", MAIN)
        assert [(a, f.relpath) for a, f in s.subagents] == [("a1", SUB)]
        assert s.files == [s.main, s.subagents[0][1]]
        assert s.subagents[0][1].meta_relpath == "-Users-me-repo/s1/subagents/agent-a1.meta.json"


class TestRead:
    def test_reads_from_an_offset_in_one_call(self, docker, root):
        put(root, MAIN, b"line1\nline2\nline3\n")
        put(root, SUB, b"a\nb\n")
        out = VolumeSource("wf").read([(MAIN, 6), (SUB, 0)])
        assert out == {MAIN: b"line2\nline3\n", SUB: b"a\nb\n"}
        assert len(docker.reads()) == 1 and docker.reads()[0] == [(6, MAIN), (0, SUB)]

    def test_binary_safe_and_length_framed(self, docker, root):
        payload = b"\x00\xff\n 12 fake-header\nend"      # would confuse a naive parser
        put(root, MAIN, payload)
        assert VolumeSource("wf").read([(MAIN, 0)]) == {MAIN: payload}

    def test_a_vanished_file_is_simply_absent(self, docker, root):
        assert VolumeSource("wf").read([("-r/missing.jsonl", 0)]) == {}

    def test_no_requests_no_docker(self, docker):
        assert VolumeSource("wf").read([]) == {}
        assert docker.calls == []

    @pytest.mark.parametrize("relpath", ["../etc/passwd", "a b", "-r/s.jsonl\n0 /etc/passwd", ""])
    def test_refuses_an_unvetted_path(self, docker, relpath):
        with pytest.raises(VolumeError, match="refusing"):
            VolumeSource("wf").read([(relpath, 0)])
        assert docker.calls == []

    def test_truncated_output_is_a_volume_error(self, monkeypatch, root):
        short = subprocess.CompletedProcess([], 0, b"50 -r/s.jsonl\nabc", b"")
        FakeDocker({"wf": root}, failure=short).install(monkeypatch)
        with pytest.raises(VolumeError, match="unexpected read"):
            VolumeSource("wf").read([("-r/s.jsonl", 0)])


class TestHelperContainerIsReadOnlyAndOffline:
    def test_every_run_mounts_ro_with_no_network(self, docker, root):
        put(root, MAIN, b"x\n")
        source = VolumeSource("wf")
        source.list_files()
        source.read([(MAIN, 0)])
        source.read_account()
        runs = [c for c, _ in docker.calls if c[1] == "run"]
        assert len(runs) == 3
        for argv in runs:
            assert "wf:/v:ro" in argv and argv[argv.index("--network") + 1] == "none"
            assert "--rm" in argv


class TestAccount:
    def test_only_whitelisted_fields_cross(self, docker, root):
        (root / ".config" / "claude" / ".claude.json").write_text(json.dumps({
            "oauthAccount": {
                "accountUuid": "acc-1", "organizationUuid": "org-1",
                "organizationType": "claude_enterprise", "seatTier": "premium",
                "billingType": "stripe_subscription", "organizationRateLimitTier": "default_claude_max",
                "emailAddress": "someone@example.com", "fullName": "Some One",
                "displayName": "Some", "organizationName": "Acme Ltd", "somethingNew": "x"},
            "projects": {"/repo": {"history": ["secret prompt"]}}}))
        got = VolumeSource("wf").read_account()
        assert got == {"accountUuid": "acc-1", "organizationUuid": "org-1",
                       "organizationType": "claude_enterprise", "seatTier": "premium",
                       "billingType": "stripe_subscription",
                       "organizationRateLimitTier": "default_claude_max"}
        blob = json.dumps(got)
        for leaked in ("someone@example.com", "Some One", "Acme", "secret prompt", "somethingNew"):
            assert leaked not in blob

    def test_api_key_volume_is_an_empty_profile(self, docker, root):
        (root / ".config" / "claude" / ".claude.json").write_text("{}")
        assert VolumeSource("wf").read_account() == {}

    def test_missing_or_junk_file_is_none(self, docker, root):
        assert VolumeSource("wf").read_account() == {}     # empty output == empty JSON
        (root / ".config" / "claude" / ".claude.json").write_text("{oops")
        assert VolumeSource("wf").read_account() is None

    def test_a_docker_failure_is_none_not_a_raise(self, monkeypatch, root):
        FakeDocker({"wf": root}, failure=FileNotFoundError("docker")).install(monkeypatch)
        assert VolumeSource("wf").read_account() is None


class TestSoftFailures:
    """Docker absent, volume missing, non-zero exit, timeout: every one is a
    `VolumeError` with a message a person can read — never anything else."""

    def test_docker_not_installed(self, monkeypatch, root):
        FakeDocker({"wf": root}, inspect_failure=FileNotFoundError("docker")).install(monkeypatch)
        with pytest.raises(VolumeError, match="docker not found"):
            VolumeSource("wf").list_files()

    def test_volume_missing_is_checked_before_a_run_can_create_it(self, monkeypatch, root):
        docker = FakeDocker({"other": root}).install(monkeypatch)
        with pytest.raises(VolumeError, match="volume not found: wf"):
            VolumeSource("wf").list_files()
        assert docker.runs(volumes._LIST_SCRIPT) == []      # `docker run -v` would mint it

    def test_the_existence_check_is_made_once_per_source(self, docker, root):
        source = VolumeSource("wf")
        source.list_files()
        source.list_files()
        assert sum(1 for c, _ in docker.calls if c[1] == "volume") == 1

    def test_non_zero_exit_carries_stderr(self, monkeypatch, root):
        boom = subprocess.CompletedProcess([], 125, b"", b"docker: permission denied")
        FakeDocker({"wf": root}, failure=boom).install(monkeypatch)
        with pytest.raises(VolumeError, match="permission denied"):
            VolumeSource("wf").list_files()

    def test_timeout(self, monkeypatch, root):
        FakeDocker({"wf": root}, failure=subprocess.TimeoutExpired("docker", 30)).install(monkeypatch)
        with pytest.raises(VolumeError, match="timed out"):
            VolumeSource("wf").list_files()

    def test_daemon_down_on_inspect(self, monkeypatch, root):
        class Down(FakeDocker):
            def __call__(self, cmd, **kw):
                if cmd[1:3] == ["volume", "inspect"]:
                    return subprocess.CompletedProcess(
                        cmd, 1, b"", b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
                return super().__call__(cmd, **kw)
        Down({"wf": root}).install(monkeypatch)
        with pytest.raises(VolumeError, match="Cannot connect to the Docker daemon"):
            VolumeSource("wf").list_files()

    def test_generic_oserror(self, monkeypatch, root):
        FakeDocker({"wf": root}, failure=PermissionError("nope")).install(monkeypatch)
        with pytest.raises(VolumeError, match="docker failed"):
            VolumeSource("wf").list_files()


def test_source_of_a_configured_volume():
    source = VolumeSource.of(store.Volume("wf-state", "a/b"))
    assert (source.name, source.claude_dir) == ("wf-state", "a/b")
