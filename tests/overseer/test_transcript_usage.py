import json

from scripts.transcript_usage import budget_tokens, raw_total, sum_usage, zero_usage


def _assistant(msg_id, inp, read, create, out):
    return {"type": "assistant", "message": {"id": msg_id, "usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create, "output_tokens": out}}}


def _write(path, entries):
    path.write_text("\n".join(
        e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n")
    return path


def test_counts_each_message_once_across_content_blocks(tmp_path):
    # A message streamed as text + tool_use is written as two lines repeating
    # the same id and identical usage (verified on real 2.1.273 transcripts).
    t = _write(tmp_path / "a.jsonl", [
        {"type": "user", "message": {"content": "go"}},
        _assistant("m1", 2, 1000, 500, 40),
        _assistant("m1", 2, 1000, 500, 40),
        _assistant("m2", 1, 1500, 200, 60),
    ])
    totals = sum_usage(t)
    assert totals == {"input": 3, "cache_read": 2500, "cache_creation": 700, "output": 100}
    assert raw_total(totals) == 3303
    assert budget_tokens(totals) == 803


def test_messages_without_id_are_each_counted(tmp_path):
    t = _write(tmp_path / "a.jsonl", [_assistant(None, 1, 0, 0, 5), _assistant("", 1, 0, 0, 5)])
    assert sum_usage(t)["output"] == 10


def test_malformed_lines_and_missing_file_are_zero(tmp_path):
    t = _write(tmp_path / "a.jsonl", ["{not json", "[]", {"type": "assistant", "message": "x"},
                                      _assistant("m1", 1, 1, 1, 1)])
    assert raw_total(sum_usage(t)) == 4
    assert sum_usage(tmp_path / "missing.jsonl") == zero_usage()
