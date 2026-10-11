#!/usr/bin/env python3
"""optimise-orm trigger scan: every INDEX trigger over the target files, one call.

    triggers.py [--index INDEX.md] [--groups a,b] [--max-lines N] FILE_OR_DIR...

Reads each `Trigger` regex from checks/INDEX.md (default: ../checks/INDEX.md beside
this script), runs them all line by line over the given files, and prints one line
per nominated check:

    CODE severity group.md offset limit | file:line,line ... (+N)

`offset limit` are the arguments for a `Read` of that check's section. Every
`critical` row is nominated even without a hit (hits shown as `-`). `--groups`
restricts the scan to those group stems (the active groups after --only/--skip).
Stdlib only. Exit 0 on success, 2 on a bad path, index or regex.
"""
import argparse
import re
import sys
from pathlib import Path

ROW = re.compile(
    r"^\| (?P<id>[A-Z]+-\d+) \| (?P<sev>\w+) \| (?P<kind>\w*) \| .* \| `(?P<trig>.*)` \| "
    r"(?P<file>\S+\.md) L(?P<a>\d+)-(?P<b>\d+) \|$"
)
SUFFIXES = {".py", ".html", ".htm", ".txt", ".cfg", ".toml"}
MAX_BYTES = 2 * 1024 * 1024


class Bad(Exception):
    pass


def load_rows(index: Path):
    try:
        text = index.read_text(encoding="utf-8")
    except OSError as e:
        raise Bad(f"cannot read index {index}: {e.strerror or e}")
    rows = []
    for ln in text.splitlines():
        m = ROW.match(ln)
        if not m:
            continue
        pat = m["trig"].replace("\\|", "|")
        try:
            rx = re.compile(pat)
        except re.error as e:
            raise Bad(f"bad trigger regex for {m['id']}: {pat!r}: {e}")
        rows.append({**m.groupdict(), "rx": rx, "a": int(m["a"]), "b": int(m["b"])})
    if not rows:
        raise Bad(f"no check rows found in {index}")
    return rows


def collect(paths):
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(f for f in pp.rglob("*") if f.is_file() and f.suffix in SUFFIXES)
        elif pp.is_file():
            files.append(pp)
        else:
            raise Bad(f"no such file or directory: {p}")
    return files


def scan(rows, files, groups=None, max_lines=4):
    texts = []
    for f in files:
        try:
            if f.stat().st_size > MAX_BYTES:
                continue
            raw = f.read_bytes()
        except OSError as e:
            raise Bad(f"cannot read {f}: {e.strerror or e}")
        if b"\0" in raw[:8192]:
            continue
        texts.append((f, raw.decode("utf-8", errors="replace").splitlines()))
    out = []
    for r in rows:
        if groups is not None and Path(r["file"]).stem not in groups:
            continue
        hits = []
        for f, lines in texts:
            nums = [n for n, ln in enumerate(lines, 1) if r["rx"].search(ln)]
            if nums:
                hits.append((f, nums))
        if not hits and r["sev"] != "critical":
            continue
        if hits:
            parts = []
            for f, nums in hits:
                shown = ",".join(map(str, nums[:max_lines]))
                more = f" +{len(nums) - max_lines}" if len(nums) > max_lines else ""
                parts.append(f"{f}:{shown}{more}")
            span = " ".join(parts)
        else:
            span = "- (critical, always opened)"
        out.append(f"{r['id']} {r['sev']} {r['file']} {r['a']} {r['b'] - r['a'] + 1} | {span}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--index", default=str(Path(__file__).resolve().parent.parent / "checks" / "INDEX.md"))
    ap.add_argument("--groups", default=None, help="comma-separated group stems to scan")
    ap.add_argument("--max-lines", type=int, default=4)
    a = ap.parse_args(argv)
    try:
        rows = load_rows(Path(a.index))
        files = collect(a.paths)
        groups = set(a.groups.split(",")) if a.groups else None
        if groups is not None:
            known = {Path(r["file"]).stem for r in rows}
            if groups - known:
                raise Bad(f"unknown group(s): {', '.join(sorted(groups - known))}")
        lines = scan(rows, files, groups, a.max_lines)
    except Bad as e:
        print(f"triggers.py: {e}", file=sys.stderr)
        return 2
    print(f"Nominated {len(lines)} checks over {len(files)} file(s). Read each: Read(checks/<file>, offset, limit)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
