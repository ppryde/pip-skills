#!/usr/bin/env python3
"""optimise-orm trigger scan: every INDEX trigger over the target files, one call.

    triggers.py [--index INDEX.md] [--groups a,b] [--max-lines N] [--thorough]
                [--batches --out-dir DIR] FILE_OR_DIR...

Reads each `Trigger` regex from checks/INDEX.md (default: ../checks/INDEX.md beside
this script), runs them all line by line over the given files, and prints one line
per nominated check:

    CODE severity group.md offset limit | file:line,line ... (+N)

`offset limit` are the arguments for a `Read` of that check's section. Every
`critical` row is nominated even without a hit (hits shown as `-`). `--groups`
restricts the scan to those group stems (the active groups after --only/--skip).
`--thorough` nominates every check of the active groups, hit or not.

`--batches --out-dir DIR` also splits the nominated checks into agent batches (at most
BATCH_CAP per batch; a group of BATCH_FLOOR or more is never packed with another; fewer than
BATCH_FLOOR nominated in all means no batches: open them inline), writes DIR/batch-K.md (the
nominated sections, copied from the group files, under a `# Batch K` heading) and prints one line each:

    batch K/N | groups | count | DIR/batch-K.md L1-<lines> | CODE,CODE,...

The two constants equal tools/batching.py's (a test keeps them equal).
Stdlib only. Exit 0 on success, 2 on a bad path, index, regex or --out-dir.
"""
import argparse
import re
import sys
from pathlib import Path

ROW = re.compile(
    r"^\| (?P<id>[A-Z]+-\d+) \| (?P<sev>\w+) \| (?P<kind>\w*) \| .* \| `(?P<trig>.*)` \| "
    r"(?P<file>\S+\.md) L(?P<a>\d+)-(?P<b>\d+) \|$"
)
BATCH_CAP = 30     # max checks per agent batch (tools/batching.py BATCH_CAP; a test keeps them equal)
BATCH_FLOOR = 8    # never spawn an agent for fewer (tools/batching.py BATCH_FLOOR)
SUFFIXES = {".py", ".html", ".htm", ".txt", ".cfg", ".toml"}
MAX_BYTES = 2 * 1024 * 1024
MAX_LINE = 2000  # longer lines (minified assets, data blobs) are truncated before matching
PRUNE = {".venv", "venv", "node_modules", "migrations", ".git", "__pycache__"}


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
            files += sorted(
                f for f in pp.rglob("*")
                if f.is_file() and f.suffix in SUFFIXES and not PRUNE.intersection(f.relative_to(pp).parts[:-1])
            )
        elif pp.is_file():
            files.append(pp)
        else:
            raise Bad(f"no such file or directory: {p}")
    return files


def scan(rows, files, groups=None, max_lines=4, notes=None, scanned=None, thorough=False, nominees=None):
    """Return nominated lines. `notes` collects skip/truncation notices, `scanned` the files read,
    `nominees` (a list) the nominated rows in output order; `thorough` nominates every row of the groups."""
    notes = notes if notes is not None else []
    scanned = scanned if scanned is not None else []
    texts = []
    for f in files:
        try:
            if f.stat().st_size > MAX_BYTES:
                notes.append(f"skipped: {f} (over {MAX_BYTES // 1024 // 1024} MB)")
                continue
            raw = f.read_bytes()
        except OSError as e:
            raise Bad(f"cannot read {f}: {e.strerror or e}")
        if b"\0" in raw[:8192]:
            notes.append(f"skipped: {f} (binary)")
            continue
        lines = raw.decode("utf-8", errors="replace").splitlines()
        long_n = sum(1 for ln in lines if len(ln) > MAX_LINE)
        if long_n:
            notes.append(f"truncated: {f} ({long_n} line(s) over {MAX_LINE} chars scanned to {MAX_LINE})")
            lines = [ln[:MAX_LINE] for ln in lines]
        texts.append((f, lines))
    scanned.extend(f for f, _ in texts)
    out = []
    for r in rows:
        if groups is not None and Path(r["file"]).stem not in groups:
            continue
        hits = []
        for f, lines in texts:
            nums = [n for n, ln in enumerate(lines, 1) if r["rx"].search(ln)]
            if nums:
                hits.append((f, nums))
        if not hits and r["sev"] != "critical" and not thorough:
            continue
        if hits:
            parts = []
            for f, nums in hits:
                shown = ",".join(map(str, nums[:max_lines]))
                more = f" +{len(nums) - max_lines}" if len(nums) > max_lines else ""
                parts.append(f"{f}:{shown}{more}")
            span = " ".join(parts)
        else:
            span = "- (critical, always opened)" if r["sev"] == "critical" else "- (thorough, every check opened)"
        if nominees is not None:
            nominees.append({"id": r["id"], "group": Path(r["file"]).stem, "file": r["file"], "a": r["a"], "b": r["b"]})
        out.append(f"{r['id']} {r['sev']} {r['file']} {r['a']} {r['b'] - r['a'] + 1} | {span}")
    return out


def _even_chunks(items):
    """Fewest chunks of at most BATCH_CAP, as even as possible, order kept."""
    k = -(-len(items) // BATCH_CAP)
    size, extra = divmod(len(items), k)
    out, i = [], 0
    for c in range(k):
        n = size + (1 if c < extra else 0)
        out.append(items[i:i + n])
        i += n
    return out


def plan_batches(nominees):
    """Agent batches over the nominated checks (lists of nominee dicts, INDEX order kept).

    A group of BATCH_FLOOR or more is its own batch (split evenly if over BATCH_CAP, which no group is today:
    the largest has 14); smaller groups pack together up to BATCH_CAP; a packed batch still under the floor joins
    the previous batch when it fits. Under BATCH_FLOOR nominees in all: no batches.
    """
    if len(nominees) < BATCH_FLOOR:
        return []
    by_group = {}
    for n in nominees:
        by_group.setdefault(n["group"], []).append(n)
    own, small = [], []
    for items in by_group.values():
        if len(items) >= BATCH_FLOOR:
            own += _even_chunks(items) if len(items) > BATCH_CAP else [items]
        else:
            small.append(items)
    packed, cur = [], []
    for items in small:
        if cur and len(cur) + len(items) > BATCH_CAP:
            packed.append(cur)
            cur = []
        cur = cur + items
    if cur:
        packed.append(cur)
    out = []
    for b in own + packed:
        if len(b) < BATCH_FLOOR and out and len(out[-1]) + len(b) <= BATCH_CAP:
            out[-1] = out[-1] + b
        else:
            out.append(b)
    return out


def write_batches(batches, index: Path, out_dir: Path):
    """Write DIR/batch-K.md for each batch; return the printed lines."""
    lines = []
    for k, b in enumerate(batches, 1):
        groups = []
        for n in b:
            if n["group"] not in groups:
                groups.append(n["group"])
        text = [f"# Batch {k}: {'+'.join(groups)} ({len(b)} checks)", ""]
        for n in b:
            src = (index.parent / n["file"]).read_text(encoding="utf-8").splitlines()
            text += src[n["a"] - 1:n["b"]]
            text.append("")
        body = "\n".join(text)
        path = out_dir / f"batch-{k}.md"
        path.write_text(body, encoding="utf-8")
        lines.append(f"batch {k}/{len(batches)} | {'+'.join(groups)} | {len(b)} | {path} L1-{len(body.splitlines())} | "
                     f"{','.join(n['id'] for n in b)}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--index", default=str(Path(__file__).resolve().parent.parent / "checks" / "INDEX.md"))
    ap.add_argument("--groups", default=None, help="comma-separated group stems to scan")
    ap.add_argument("--max-lines", type=int, default=4)
    ap.add_argument("--thorough", action="store_true", help="nominate every check of the active groups")
    ap.add_argument("--batches", action="store_true", help="split the nominated checks into agent batches (needs --out-dir)")
    ap.add_argument("--out-dir", default=None, help="absolute scratch directory for --batches")
    a = ap.parse_args(argv)
    try:
        rows = load_rows(Path(a.index))
        files = collect(a.paths)
        groups = None
        if a.groups is not None:
            groups = {g for g in a.groups.split(",") if g}
            if not groups:
                raise Bad("--groups is empty: name at least one group, or omit the option")
            known = {Path(r["file"]).stem for r in rows}
            if groups - known:
                raise Bad(f"unknown group(s): {', '.join(sorted(groups - known))}")
        out_dir = None
        if a.batches:
            if not a.out_dir or not Path(a.out_dir).is_absolute():
                raise Bad("--batches needs --out-dir, an absolute path")
            out_dir = Path(a.out_dir)
            if str(out_dir.resolve()).startswith(str(Path(a.index).resolve().parent.parent)):
                raise Bad("--out-dir must be outside the skill directory")
        notes, scanned, nominees = [], [], []
        lines = scan(rows, files, groups, a.max_lines, notes, scanned, a.thorough, nominees)
        batch_lines = []
        if out_dir is not None:
            plan = plan_batches(nominees)
            if plan:
                out_dir.mkdir(parents=True, exist_ok=True)
                batch_lines = write_batches(plan, Path(a.index), out_dir)
            else:
                batch_lines = [f"# batches: none ({len(nominees)} nominated, under {BATCH_FLOOR}: open them inline)"]
    except Bad as e:
        print(f"triggers.py: {e}", file=sys.stderr)
        return 2
    for n in notes:
        print(n)
    print(f"Nominated {len(lines)} checks over {len(scanned)} file(s). Read each: Read(checks/<file>, offset, limit)")
    print("\n".join(lines))
    for ln in batch_lines:
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
