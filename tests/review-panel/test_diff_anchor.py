"""parse_diff: which old/new line numbers can a review comment anchor to."""
import pytest

from scripts.prreview import files_to_diff, parse_diff, place


def A(text):
    return parse_diff(text)


def hunk(header, body):
    return f"--- a/f.py\n+++ b/f.py\n{header}\n{body}"


def test_single_hunk_context_and_added_anchor_right_removed_left():
    f = A(hunk("@@ -1,3 +1,3 @@", " a\n-b\n+B\n c\n"))["f.py"]
    assert f.right == {1, 2, 3}
    assert f.left == {1, 2, 3}


def test_added_line_is_not_a_left_anchor_and_removed_not_right():
    f = A(hunk("@@ -1,2 +1,2 @@", " a\n-b\n+B\n"))["f.py"]
    assert 2 in f.right and 2 in f.left
    f = A(hunk("@@ -5,1 +5,2 @@", " x\n+y\n"))["f.py"]
    assert f.right == {5, 6} and f.left == {5}


def test_multi_hunk():
    f = A(hunk("@@ -1,1 +1,2 @@", " a\n+b\n") + "@@ -20,1 +21,1 @@\n-z\n+Z\n")["f.py"]
    assert f.right == {1, 2, 21}
    assert f.left == {1, 20}


def test_default_counts_of_one():
    f = A(hunk("@@ -3 +3 @@", "-x\n+y\n"))["f.py"]
    assert f.left == {3} and f.right == {3}


def test_empty_old_side_new_file():
    f = A("--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,2 @@\n+a\n+b\n")["n.py"]
    assert f.right == {1, 2} and f.left == set()


def test_deleted_file_is_left_only():
    f = A("--- a/d.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n")["d.py"]
    assert f.right == set() and f.left == {1, 2}


def test_pure_deletion_hunk_has_no_right_lines():
    f = A(hunk("@@ -4,2 +3,0 @@", "-x\n-y\n"))["f.py"]
    assert f.right == set() and f.left == {4, 5}


def test_rename_with_edits_keys_new_path():
    d = ("diff --git a/o.py b/n.py\nsimilarity index 90%\nrename from o.py\nrename to n.py\n"
         "--- a/o.py\n+++ b/n.py\n@@ -1,1 +1,2 @@\n a\n+b\n")
    files = A(d)
    assert "n.py" in files and "o.py" not in files
    assert files["n.py"].right == {1, 2}


def test_rename_only_anchors_nothing():
    d = "diff --git a/o.py b/n.py\nsimilarity index 100%\nrename from o.py\nrename to n.py\n"
    assert A(d) == {}


def test_binary_file_anchors_nothing():
    d = "diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n"
    assert A(d) == {}


def test_quoted_unicode_path():
    d = '--- "a/sp\\303\\251.py"\n+++ "b/sp\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n'
    assert "spé.py" in A(d)


def test_quoted_tab_path():
    d = '--- "a/t\\tab.py"\n+++ "b/t\\tab.py"\n@@ -1 +1 @@\n-a\n+b\n'
    assert "t\tab.py" in A(d)


def test_no_newline_marker_ignored():
    f = A(hunk("@@ -1,1 +1,1 @@", "-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n"))["f.py"]
    assert f.right == {1} and f.left == {1}


def test_crlf_input():
    f = A("--- a/f.py\r\n+++ b/f.py\r\n@@ -1,2 +1,2 @@\r\n a\r\n-b\r\n+c\r\n")["f.py"]
    assert f.right == {1, 2} and f.left == {1, 2}


def test_removed_line_that_looks_like_a_header_is_content():
    # '--- x' as a removed line (content '-- x') must not start a new file
    f = A(hunk("@@ -1,2 +1,1 @@", "--- x\n a\n"))["f.py"]
    assert f.left == {1, 2} and f.right == {1}


def test_bare_empty_line_is_context():
    f = A(hunk("@@ -1,3 +1,3 @@", " a\n\n b\n"))["f.py"]
    assert f.right == {1, 2, 3}


@pytest.mark.parametrize("line,ok", [(0, False), (1, True), (3, True), (4, False)])
def test_hunk_boundaries(line, ok):
    f = A(hunk("@@ -1,3 +1,3 @@", " a\n b\n c\n"))
    st, _, _ = place({"path": "f.py", "line": line}, f)
    assert (st == "placed") is ok


def test_files_fallback_builds_anchors_and_skips_patchless():
    entries = [
        {"filename": "a.py", "status": "modified", "patch": "@@ -1,1 +1,2 @@\n a\n+b"},
        {"filename": "big.bin", "status": "modified"},
        {"filename": "n.py", "previous_filename": "o.py", "status": "renamed",
         "patch": "@@ -1,1 +1,1 @@\n-a\n+b"},
        {"filename": "gone.py", "status": "removed", "patch": "@@ -1,1 +0,0 @@\n-a"},
    ]
    files = parse_diff(files_to_diff(entries))
    assert files["a.py"].right == {1, 2}
    assert "big.bin" not in files and "o.py" not in files
    assert files["n.py"].right == {1}
    assert files["gone.py"].left == {1} and not files["gone.py"].right


# place() rules
def test_place_reasons():
    files = A(hunk("@@ -1,2 +1,2 @@", " a\n-b\n+c\n"))
    p = lambda **k: place({"path": "f.py", **k}, files)  # noqa: E731
    assert p(line=1) == ("placed", "RIGHT", None)
    assert p() == ("unplaced", None, "no-line")
    assert p(line="3") == ("unplaced", None, "no-line")
    assert p(line=True) == ("unplaced", None, "no-line")
    assert p(line=9) == ("unplaced", None, "line-not-in-diff")
    assert place({"path": "x.py", "line": 1}, files)[2] == "file-not-in-diff"
    assert place({"path": "../x.py", "line": 1}, files)[2] == "file-not-in-diff"
    assert place({"path": "/abs/f.py", "line": 1}, files)[2] == "file-not-in-diff"
    assert place({"path": "./f.py", "line": 1}, files)[0] == "placed"


def test_explicit_side_rules():
    files = A(hunk("@@ -1,2 +1,3 @@", " a\n-b\n+c\n+d\n"))
    p = lambda **k: place({"path": "f.py", **k}, files)  # noqa: E731
    assert p(line=3, side="LEFT") == ("unplaced", None, "side-not-in-diff")
    assert p(line=9, side="LEFT") == ("unplaced", None, "line-not-in-diff")
    assert p(line=3, side="RIGHT")[0] == "placed"
    files = A(hunk("@@ -1,2 +1,1 @@", " a\n-b\n"))
    assert place({"path": "f.py", "line": 2, "side": "RIGHT"}, files)[2] == "side-not-in-diff"
    files = A("--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,1 @@\n a\n-x\n-y\n@@ -9,1 +7,1 @@\n-p\n+q\n")
    # line 3 is LEFT-only; RIGHT has anchors so side omitted does not flip to LEFT
    assert place({"path": "f.py", "line": 3}, files)[2] == "line-not-in-diff"
    assert place({"path": "f.py", "line": 3, "side": "LEFT"}, files)[0] == "placed"


def test_deleted_file_side_omitted_places_left():
    files = A("--- a/d.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n")
    assert place({"path": "d.py", "line": 2}, files) == ("placed", "LEFT", None)
    # explicit RIGHT on a deleted file: the line is on the other side
    assert place({"path": "d.py", "line": 2, "side": "RIGHT"}, files)[2] == "side-not-in-diff"
