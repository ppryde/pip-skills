from scripts import statusline as sl

SCRIPT = "#!/usr/bin/env bash\ninput=$(cat)\nmodel=$(echo \"$input\" | jq -r .model)\n"


class TestAddBlock:
    def test_inserts_after_anchor(self):
        out = sl.add_block(SCRIPT)
        assert sl.START in out and sl.END in out and sl.INGEST in out
        # block sits after the `input=$(cat)` line, before the model line
        assert out.index("input=$(cat)") < out.index(sl.START) < out.index("model=")

    def test_idempotent(self):
        once = sl.add_block(SCRIPT)
        twice = sl.add_block(once)
        assert once == twice
        assert once.count(sl.START) == 1

    def test_appends_when_no_anchor(self):
        text = "#!/usr/bin/env bash\necho hello\n"
        out = sl.add_block(text)
        assert out.startswith(text)
        assert sl.START in out

    def test_appends_to_empty(self):
        out = sl.add_block("")
        assert sl.START in out


class TestRemoveBlock:
    def test_round_trip_restores_original(self):
        installed = sl.add_block(SCRIPT)
        assert sl.remove_block(installed) == SCRIPT

    def test_idempotent_when_absent(self):
        assert sl.remove_block(SCRIPT) == SCRIPT

    def test_is_installed(self):
        assert not sl.is_installed(SCRIPT)
        assert sl.is_installed(sl.add_block(SCRIPT))
