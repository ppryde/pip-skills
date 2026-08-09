"""Aggregate pytest JUnit XML into per-file and per-directory wall-clock.

    python aggregate_junit.py AFTER.xml                 # profile one run
    python aggregate_junit.py AFTER.xml --compare BEFORE.xml

With --compare, prints the per-file movers AND the check that matters most:
whether the test set and every test's status are identical. "The suite got
faster" and "the suite stopped running things" produce the same headline
number, so a timing claim without this check is unproven.
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def _statuses(xml_path: str) -> dict[str, str]:
    """node id -> passed | failure | error | skipped."""
    out: dict[str, str] = {}
    for tc in ET.parse(xml_path).getroot().iter("testcase"):
        kind = "passed"
        for child in tc:
            if child.tag in ("failure", "error", "skipped"):
                kind = child.tag
        out[f"{tc.get('classname')}::{tc.get('name')}"] = kind
    return out


def _per_file(xml_path: str) -> dict[str, float]:
    d: dict[str, float] = defaultdict(float)
    for tc in ET.parse(xml_path).getroot().iter("testcase"):
        f = tc.get("file") or tc.get("classname", "").replace(".", "/") + ".py"
        d[f] += float(tc.get("time", 0))
    return d


if "--compare" in sys.argv:
    after_path = sys.argv[1]
    before_path = sys.argv[sys.argv.index("--compare") + 1]

    before, after = _per_file(before_path), _per_file(after_path)
    tb, ta = sum(before.values()), sum(after.values())
    print(f"  TOTAL {tb:.1f}s -> {ta:.1f}s   ({(ta - tb) / tb * 100:+.1f}%, {tb - ta:.1f}s saved)\n")
    print(f"  {'before':>8} {'after':>8} {'delta':>8}  file")
    movers = sorted(set(before) | set(after), key=lambda f: before.get(f, 0) - after.get(f, 0))
    for f in reversed(movers[-12:]):
        print(f"  {before.get(f, 0):8.2f} {after.get(f, 0):8.2f} {after.get(f, 0) - before.get(f, 0):+8.2f}  {f}")

    sb, sa = _statuses(before_path), _statuses(after_path)
    added, removed = sorted(set(sa) - set(sb)), sorted(set(sb) - set(sa))
    changed = sorted(k for k in set(sb) & set(sa) if sb[k] != sa[k])
    print(f"\n  tests {len(sb)} -> {len(sa)}")
    print(f"  removed={len(removed)}  status-changed={len(changed)}  added={len(added)}")
    for k in removed:
        print(f"      - {k}")
    for k in changed:
        print(f"      ~ {k}: {sb[k]} -> {sa[k]}")
    for k in added:
        print(f"      + {k}")
    if removed or changed:
        sys.exit("\n  REGRESSION: a test was removed or changed status. The speedup is unproven.")
    print("\n  OK: nothing removed, nothing changed status.")
    print("  (Explain each addition individually — meta-guards that scan every file gain a case per new file.)")
    raise SystemExit(0)

path = sys.argv[1]
tree = ET.parse(path)
root = tree.getroot()

per_file = defaultdict(lambda: [0.0, 0])  # file -> [seconds, count]
total = 0.0
n = 0
slowest = []

for tc in root.iter("testcase"):
    f = tc.get("file") or tc.get("classname", "").replace(".", "/") + ".py"
    t = float(tc.get("time", 0))
    per_file[f][0] += t
    per_file[f][1] += 1
    total += t
    n += 1
    slowest.append((t, f, tc.get("name")))

print(f"TOTAL: {total:.1f}s across {n} tests ({total / 60:.1f} min of measured test time)\n")

per_dir = defaultdict(lambda: [0.0, 0])
for f, (t, c) in per_file.items():
    d = "/".join(f.split("/")[:2])
    per_dir[d][0] += t
    per_dir[d][1] += c

print("=== BY TOP-LEVEL DIR ===")
for d, (t, c) in sorted(per_dir.items(), key=lambda x: -x[1][0]):
    print(f"  {t:8.1f}s  {t / total * 100:5.1f}%  {c:6d} tests  {t / c * 1000:7.1f}ms/test  {d}")

print("\n=== TOP 40 FILES BY TOTAL TIME ===")
print(f"  {'secs':>8} {'%':>6} {'tests':>6} {'ms/test':>9}  file")
cum = 0.0
for f, (t, c) in sorted(per_file.items(), key=lambda x: -x[1][0])[:40]:
    cum += t
    print(f"  {t:8.1f} {t / total * 100:5.1f}% {c:6d} {t / c * 1000:8.1f}   {f}")
print(f"  -> top 40 files = {cum:.1f}s ({cum / total * 100:.1f}% of total)")

print("\n=== TOP 25 INDIVIDUAL SLOWEST TESTS ===")
for t, f, name in sorted(slowest, reverse=True)[:25]:
    print(f"  {t:7.2f}s  {f}::{name}")

print("\n=== CONCENTRATION ===")
ordered = sorted(per_file.values(), key=lambda x: -x[0])
run = 0.0
for pct in (50, 80, 90):
    run = 0.0
    for i, (t, c) in enumerate(ordered, 1):
        run += t
        if run >= total * pct / 100:
            print(f"  {pct}% of wall-clock is in {i} files ({i / len(ordered) * 100:.1f}% of files)")
            break
