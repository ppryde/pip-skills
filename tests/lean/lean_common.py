"""Shared helpers for the lean-skills tests (stdlib only)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUDGETS = Path(__file__).resolve().parent / "budgets.json"
SKIP_DIRS = {"node_modules", ".venv", ".git", "__pycache__", ".claude"}


def read_lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def size_lf(path: Path) -> int:
    """Byte size with CRLF counted as LF, so a Windows checkout measures the same."""
    return len(read_lf(path).encode("utf-8"))


def load_budgets() -> dict:
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def _walk(top: Path):
    for p in sorted(top.rglob("*.md")):
        rel_parts = p.relative_to(REPO).parts
        if SKIP_DIRS.intersection(rel_parts):
            continue
        yield p


def prompt_files(repo: Path = REPO) -> list[str]:
    """Repo-relative POSIX paths of every SKILL.md and commands/*.md under plugins/ and skills/."""
    out = []
    for top in ("plugins", "skills"):
        d = repo / top
        if not d.is_dir():
            continue
        for p in _walk(d):
            if p.name == "SKILL.md" or p.parent.name == "commands":
                out.append(p.relative_to(repo).as_posix())
    return sorted(out)


def plugin_root(skill_dir: Path) -> Path | None:
    """Nearest ancestor carrying .claude-plugin/ (None for standalone skills)."""
    for parent in [skill_dir, *skill_dir.parents]:
        if (parent / ".claude-plugin").is_dir():
            return parent
        if parent == REPO:
            return None
    return None


def skill_dirs(repo: Path = REPO) -> list[Path]:
    return sorted((repo / p).parent for p in prompt_files(repo) if p.endswith("/SKILL.md"))


def reachable_references(skill_dir: Path) -> tuple[set[Path], list[tuple[Path, str]]]:
    """Transitive reachability of files under skill_dir/references.

    Seeds: SKILL.md and every commands/*.md of the same plugin. A reference is
    reachable if a reachable file names it (as `references/<rel>` or by bare file
    name). Returns (reachable reference paths, dangling mentions as (source, text)).
    """
    refs_dir = skill_dir / "references"
    all_refs = sorted(p for p in refs_dir.rglob("*") if p.is_file()) if refs_dir.is_dir() else []
    seeds = [skill_dir / "SKILL.md"]
    root = plugin_root(skill_dir)
    if root is not None and (root / "commands").is_dir():
        seeds += sorted((root / "commands").glob("*.md"))

    token_re = re.compile(r"(?<![\w./-])((?:\.{1,2}/)*(?:[\w-]+/)*[\w-]+(?:\.[\w-]+)+)(?![\w-]|\.\w)")

    def mentioned(src: Path, text: str, src_is_reference: bool) -> set[Path]:
        """Reference files named in text. Seeds (SKILL.md, commands) must use `references/<rel>`;
        a reference links to its siblings relative to its own directory (`b.md`, `./b.md`, `../x/b.md`)."""
        out: set[Path] = set()
        for tok in token_re.findall(text):
            if tok.startswith("references/"):
                target = skill_dir / tok
            elif src_is_reference:
                target = src.parent / tok
            else:
                continue
            out.add(Path(os.path.normpath(target)))
        return out

    def exists(src: Path, mention: str) -> bool:
        if (skill_dir / mention).exists():
            return True
        # A command may point at any skill's references in the same plugin.
        return src.parent.name == "commands" and root is not None and any(root.glob(f"skills/*/{mention}"))

    reached: set[Path] = set()
    frontier = list(seeds)
    seen_src = set(seeds)
    dangling: list[tuple[Path, str]] = []
    while frontier:
        src = frontier.pop()
        text = read_lf(src)
        is_ref = src not in seeds
        for m in re.finditer(r"references/[A-Za-z0-9_./-]*[A-Za-z0-9_]\.[A-Za-z0-9]+", text):
            if not exists(src, m.group(0)):
                dangling.append((src, m.group(0)))
        hits = mentioned(src, text, is_ref)
        for ref in all_refs:
            if ref in reached:
                continue
            if Path(os.path.normpath(ref)) in hits:
                reached.add(ref)
                if ref not in seen_src and ref.suffix == ".md":
                    seen_src.add(ref)
                    frontier.append(ref)
    return reached, dangling
