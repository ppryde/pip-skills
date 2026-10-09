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


class TestReviewRound2:
    def test_missing_end_leaves_the_script_untouched(self):
        broken = SCRIPT + sl.START + "\nprintf nothing\necho precious\n"
        assert sl.remove_block(broken) == broken

    def test_start_after_end_is_not_a_block(self):
        odd = SCRIPT + sl.END + "\n" + sl.START + "\necho precious\n"
        assert sl.remove_block(odd) == odd

    def test_a_commented_anchor_is_not_the_anchor(self):
        text = "#!/bin/bash\n# input=$(cat) is read below\necho hi\ninput=$(cat)\necho done\n"
        out = sl.add_block(text)
        assert out.index(sl.START) > out.index("echo hi")

    def test_existing_lines_are_kept_byte_for_byte(self):
        text = "#!/bin/bash\ninput=$(cat)\necho last"  # no final newline
        out = sl.add_block(text)
        assert sl.remove_block(out) == text

    def test_unterminated_anchor_line_round_trips(self):
        text = "#!/bin/bash\ninput=$(cat)"
        assert sl.remove_block(sl.add_block(text)) == text

    def test_crlf_lines_survive(self):
        text = "#!/bin/bash\r\ninput=$(cat)\r\necho hi\r\n"
        out = sl.add_block(text)
        assert "echo hi\r\n" in out and sl.remove_block(out).count("\r\n") == 3

    def test_ingest_command_names_the_launcher(self):
        assert sl.ingest_command("/o'brien/census") == "printf '%s' \"$input\" | '/o'\"'\"'brien/census' ingest 2>/dev/null || true"
        assert sl.ingest_command() == sl.INGEST
        assert "/x/census ingest" in sl.add_block(SCRIPT, ingest=sl.ingest_command("/x/census"))
