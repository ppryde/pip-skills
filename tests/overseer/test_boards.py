"""`overseer boards` / `merge-boards` — one repo, several boards (a second
account's config dir, or the legacy plain folder), folded into the resolved
one with the newer card winning and nothing deleted."""
import json
from pathlib import Path

from factories import git_init, make_card
from scripts import boards, config, db
from scripts.cli import main


def _board_under(config_dir: Path, repo: Path, monkeypatch, cards):
    """Raise a board for ``repo`` as if from a session under ``config_dir``."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    conn = db.connect(repo)
    try:
        for card in cards:
            db.save_card(conn, card)
    finally:
        conn.close()
    return config.central_root(repo)


def _setup(tmp_path, monkeypatch):
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
    primary = tmp_path / "claude"
    personal = tmp_path / "claude-personal"
    for d in (primary, personal):
        d.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    git_init(repo)
    return primary, personal, repo


class TestFindBoards:
    def test_one_board_is_just_the_active_one(self, tmp_path, monkeypatch):
        primary, _personal, repo = _setup(tmp_path, monkeypatch)
        folder = _board_under(primary, repo, monkeypatch, [make_card("WF-1")])
        found = boards.find_boards(repo)
        assert [(b["path"], b["active"], b["cards"]) for b in found] == [(str(folder), True, 1)]

    def test_lists_the_other_accounts_board_once_watched(self, tmp_path, monkeypatch):
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        elsewhere = _board_under(personal, repo, monkeypatch, [make_card("WF-1"), make_card("WF-2")])
        active = _board_under(primary, repo, monkeypatch, [make_card("WF-1")])
        assert [b["path"] for b in boards.find_boards(repo)] == [str(active)]  # not watched yet
        config.add_claude_dir(personal)
        found = boards.find_boards(repo)
        assert [(b["path"], b["active"], b["cards"]) for b in found] == [
            (str(active), True, 1),
            (str(elsewhere), False, 2),
        ]

    def test_lists_the_legacy_plain_folder_beside_the_hashed_one(self, tmp_path, monkeypatch):
        primary, _personal, repo = _setup(tmp_path, monkeypatch)
        active = _board_under(primary, repo, monkeypatch, [make_card("WF-1")])
        plain = active.parent / active.name.rsplit("-", 1)[0]
        plain.mkdir()
        # The pre-hash layout: `overseer/<label>/board.db`, raised via the
        # OVERSEER_DB file override so it carries this repo's meta.
        monkeypatch.setenv("OVERSEER_DB", str(plain / "board.db"))
        c = db.connect(repo)
        db.save_card(c, make_card("WF-9"))
        c.close()
        monkeypatch.delenv("OVERSEER_DB")
        paths = [b["path"] for b in boards.find_boards(repo)]
        assert paths == [str(active), str(plain)]


class TestMergeBoards:
    def test_merges_newer_wins_and_renames_the_absorbed_folder(self, tmp_path, monkeypatch, capsys):
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        elsewhere = _board_under(personal, repo, monkeypatch, [
            make_card("WF-1", title="newer here", updated="2026-09-02T10:00"),
            make_card("WF-2", title="older here", updated="2026-08-01T10:00"),
            make_card("WF-3", title="only here", status="done"),
        ])
        pc = db.connect(repo)
        db.set_label_color(pc, "infra", "slate")
        db.set_label_color(pc, "shared", "plum")
        pc.close()
        # Sidecars only the other board has: they should travel to the target.
        (elsewhere / "knowledge").mkdir()
        (elsewhere / "knowledge" / "facts.jsonl").write_text("{}\n")
        (elsewhere / "usage.jsonl").write_text("{}\n")
        active = _board_under(primary, repo, monkeypatch, [
            make_card("WF-1", title="older there", updated="2026-08-15T10:00"),
            make_card("WF-2", title="newer there", updated="2026-09-01T10:00"),
        ])
        ac = db.connect(repo)
        db.set_label_color(ac, "shared", "sage")
        ac.close()
        config.add_claude_dir(personal)

        # Dry run: reports, touches nothing.
        plan = boards.merge_boards(repo, dry_run=True)
        assert plan["absorbed"][0]["added"] == 1
        assert plan["absorbed"][0]["updated"] == 1
        assert plan["absorbed"][0]["kept"] == 1
        assert elsewhere.is_dir()
        conn = db.connect(repo)
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
        conn.close()

        result = boards.merge_boards(repo, now=1_800_000_000)
        assert result["target"] == str(active)
        absorbed = result["absorbed"][0]
        assert (absorbed["added"], absorbed["updated"], absorbed["kept"]) == (1, 1, 1)
        assert absorbed["label_colors"] == 1  # infra added; shared kept as sage
        assert not elsewhere.exists()
        renamed = Path(absorbed["renamed_to"])
        assert renamed.is_dir() and renamed.name.startswith(f"{elsewhere.name}.absorbed-")
        assert (renamed / "board.db").is_file()  # nothing deleted
        assert absorbed["moved"] == ["knowledge", "usage.jsonl"]
        assert (active / "knowledge" / "facts.jsonl").is_file()
        assert (active / "usage.jsonl").is_file()
        assert not (renamed / "usage.jsonl").exists()

        conn = db.connect(repo)
        titles = dict(conn.execute("SELECT id, title FROM cards").fetchall())
        assert titles == {"WF-1": "newer here", "WF-2": "newer there", "WF-3": "only here"}
        assert db.load_label_colors(conn) == {"infra": "slate", "shared": "sage"}
        conn.close()
        # Idempotent: nothing left to absorb, and the repo now has one board.
        assert boards.merge_boards(repo)["absorbed"] == []
        assert len(boards.find_boards(repo)) == 1

    def test_same_id_different_card_is_a_conflict_not_an_overwrite(self, tmp_path, monkeypatch):
        # Two boards minted independently both hold WF-1 — unrelated tasks.
        # The newer `updated` must NOT win: the target's card is kept and the
        # id is reported. A shared id with the same `created` IS the same card.
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        _board_under(personal, repo, monkeypatch, [
            make_card("WF-1", title="personal's own WF-1", created="2026-08-20", updated="2026-09-03T10:00"),
            make_card("WF-2", title="shared lineage, newer", created="2026-07-01", updated="2026-09-03T10:00"),
        ])
        _board_under(primary, repo, monkeypatch, [
            make_card("WF-1", title="work's own WF-1", created="2026-08-01", updated="2026-08-02T10:00"),
            make_card("WF-2", title="shared lineage, older", created="2026-07-01", updated="2026-08-02T10:00"),
        ])
        config.add_claude_dir(personal)
        result = boards.merge_boards(repo)
        absorbed = result["absorbed"][0]
        assert absorbed["conflicts"] == ["WF-1"]
        assert (absorbed["added"], absorbed["updated"], absorbed["kept"]) == (0, 1, 0)
        conn = db.connect(repo)
        titles = dict(conn.execute("SELECT id, title FROM cards").fetchall())
        conn.close()
        assert titles == {"WF-1": "work's own WF-1", "WF-2": "shared lineage, newer"}

    def test_absorbs_a_board_with_an_older_schema(self, tmp_path, monkeypatch):
        # The legacy plain folder predates columns like `labels`; its rows
        # must still convert (missing columns read as their defaults).
        import sqlite3
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        elsewhere = _board_under(personal, repo, monkeypatch, [make_card("WF-OLD", labels=["x"])])
        legacy = sqlite3.connect(elsewhere / "board.db")
        legacy.execute("ALTER TABLE cards DROP COLUMN labels")
        legacy.execute("ALTER TABLE cards DROP COLUMN claim_nudged")
        legacy.execute("DROP TABLE label_colors")
        legacy.commit()
        legacy.close()
        active = _board_under(primary, repo, monkeypatch, [make_card("WF-1")])
        config.add_claude_dir(personal)
        result = boards.merge_boards(repo)
        assert result["absorbed"][0]["added"] == 1
        conn = db.connect(repo)
        old = db.load_card(conn, "WF-OLD")
        conn.close()
        assert old is not None and old.labels == [] and old.claim_nudged is False
        assert str(active) == result["target"]

    def test_dry_run_creates_nothing_and_ignores_the_db_file_override(self, tmp_path, monkeypatch):
        # The resolved folder does not exist yet (OVERSEER_CENTRAL names a
        # fresh one — the env override wins resolution) while another
        # account's board does. A dry run must report against an empty target
        # without creating it — and the merge must open the RESOLVED folder
        # even if OVERSEER_DB points elsewhere (find_boards and the merge agree).
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        _board_under(personal, repo, monkeypatch, [make_card("WF-1"), make_card("WF-2")])
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
        config.add_claude_dir(personal)
        monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "fresh-central"))
        target = config.central_root(repo)
        assert target == tmp_path / "fresh-central"
        assert not target.exists()
        monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "somewhere-else.db"))
        plan = boards.merge_boards(repo, dry_run=True)
        assert plan["target"] == str(target)
        assert plan["absorbed"][0]["added"] == 2
        assert not target.exists()
        assert not (tmp_path / "somewhere-else.db").exists()
        # The real run creates the resolved folder and fills it.
        result = boards.merge_boards(repo)
        assert (target / "board.db").is_file()
        assert result["absorbed"][0]["added"] == 2
        assert not (tmp_path / "somewhere-else.db").exists()

    def test_cli_verbs(self, tmp_path, monkeypatch, capsys):
        primary, personal, repo = _setup(tmp_path, monkeypatch)
        _board_under(personal, repo, monkeypatch, [make_card("WF-1"), make_card("WF-2")])
        _board_under(primary, repo, monkeypatch, [make_card("WF-1")])
        config.add_claude_dir(personal)
        capsys.readouterr()

        assert main(["--root", str(repo), "boards", "--json"]) == 0
        listed = json.loads(capsys.readouterr().out)["boards"]
        assert [b["active"] for b in listed] == [True, False]

        assert main(["--root", str(repo), "merge-boards", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "would absorb" in out and "+1 cards" in out

        assert main(["--root", str(repo), "merge-boards", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["absorbed"][0]["added"] == 1

        assert main(["--root", str(repo), "boards"]) == 0
        assert "1 boards" not in capsys.readouterr().out  # the "N boards for one repo" line is gone
