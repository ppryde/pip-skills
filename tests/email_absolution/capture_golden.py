#!/usr/bin/env python3
"""Capture which regex rules fire on each planted template (line by line, via rules.py).

Used once, BEFORE the migration landed, against a structure-normalised export of the old
doctrines, so the "before" and "after" sets come from the same parser:

  git show origin/main:plugins/email-absolution/doctrines/<f>.md   # for every doctrine, into OLD/
  python3 plugins/email-absolution/scripts/migrate_doctrines.py --doctrines-dir OLD --stage1-only --out S1
  python3 tests/email_absolution/capture_golden.py S1 tests/email_absolution/golden_before.json

Not a test; nothing imports it.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "email-absolution"


def load_rules():
    spec = importlib.util.spec_from_file_location("email_rules_capture", PLUGIN / "scripts" / "rules.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def capture(doctrines_dir: Path) -> dict:
    R = load_rules()
    docs, problems = R.load(doctrines_dir)
    assert not problems, problems
    rules = R.all_rules(docs)
    out = {}
    for tpl in sorted((PLUGIN / "tests" / "templates").glob("level-*")):
        hits = R.fire_ids(rules, tpl.read_text(encoding="utf-8"))
        out[tpl.name] = sorted(hits)
    return out


if __name__ == "__main__":
    data = capture(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print({k: len(v) for k, v in data.items()})
