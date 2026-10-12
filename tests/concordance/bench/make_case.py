"""Build a bench case: a fresh two-commit repo whose PR is HEAD vs HEAD~1, with no history to
read the fix from. Modes: plant a bug by reversing a fix's non-test part; replay a commit
range; or apply a hand-written patch on a commit.
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

_TEST = re.compile(
    r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?tsx?$"
)


def _git(cwd: Path, *args: str, input: bytes | None = None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], input=input, check=True,
                          capture_output=True).stdout.decode()


def _export(source: Path, sha: str, out: Path) -> None:
    data = subprocess.run(["git", "-C", str(source), "archive", sha], check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(out, filter="data")


def _commit(case: Path, msg: str) -> None:
    _git(case, "add", "-A")
    _git(case, "-c", "user.email=bench@local", "-c", "user.name=bench", "commit", "-q",
         "--allow-empty", "-m", msg)


def build_case(source: Path, out: Path, *, plant_reverse: str | None = None,
               range_: tuple[str, str] | None = None, patch: Path | None = None,
               on: str | None = None) -> Path:
    out.mkdir(parents=True)
    _git(out, "init", "-q", "-b", "main")
    if plant_reverse is not None:
        _export(source, plant_reverse, out)
        _commit(out, "base")
        changed = _git(source, "diff", "--name-only", "-z", f"{plant_reverse}^", plant_reverse)
        for path in [p for p in changed.split("\0") if p and not _TEST.search(p)]:
            target = out / path
            try:
                old = subprocess.run(
                    ["git", "-C", str(source), "show", f"{plant_reverse}^:{path}"],
                    check=True, capture_output=True).stdout
            except subprocess.CalledProcessError:
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(old)
    elif range_ is not None:
        _export(source, range_[0], out)
        _commit(out, "base")
        for child in out.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        _export(source, range_[1], out)
    elif patch is not None and on is not None:
        _export(source, on, out)
        _commit(out, "base")
        _git(out, "apply", str(patch.resolve()))
    else:
        raise SystemExit("choose --plant-reverse, --range, or --patch with --on")
    _commit(out, "pr")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--plant-reverse")
    p.add_argument("--range", nargs=2, metavar=("BASE", "HEAD"))
    p.add_argument("--patch", type=Path)
    p.add_argument("--on")
    a = p.parse_args()
    case = build_case(a.source, a.out, plant_reverse=a.plant_reverse,
                      range_=tuple(a.range) if a.range else None, patch=a.patch, on=a.on)
    print(case)


if __name__ == "__main__":
    main()
