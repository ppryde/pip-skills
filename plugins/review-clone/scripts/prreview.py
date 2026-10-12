#!/usr/bin/env python3
"""Post findings to a GitHub PR as ONE review, anchored to the PR diff.

Canonical copy: plugins/review-panel/scripts/prreview.py. review-clone ships a
byte-identical vendored copy (plugins/review-clone/scripts/prreview.py), made by
plugins/review-clone/sync-prreview.sh; a repo test fails on drift. Stdlib only
and run as a script, so it imports nothing from either plugin's `scripts`
package (the two packages share that name and cannot live in one process).

    python3 prreview.py plan --findings F.json --out PLAN.json [--pr N] [--no-dedup]
    python3 prreview.py post --plan PLAN.json --confirmed

Finding text never reaches argv or a shell: the caller writes F.json with the
Write tool and passes paths and a PR number only. `gh` is run as an argument
vector (shell=False).

F.json:
  {"prefix": "[review-panel]", "lead": "committee: 7 findings",
   "items": [{"id": "f1a2b3c4d5e", "path": "src/a.py", "line": 42,
              "side": "RIGHT", "severity": "error", "body": "markdown"}]}
`line`, `side` and `severity` are optional. No line = summary only. Comments
are single-line (no start_line). `id` is the finding fingerprint; it becomes
the idempotency marker `<!-- prreview:<id> -->`.

plan is read-only (it makes no write call). It prints a JSON object with
status ok | nothing-to-post | no-pr | stale | error, the counts, a `preview`
string and `plan_file`. post refuses to run without --confirmed; that flag is a
speed bump, the real gate is the caller asking the user and getting a yes.

Exit codes: 0 ok / posted / fallback_summary / nothing-to-post, 1 failed,
2 usage, 3 stale, 4 no-pr.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MAX_INLINE = 50
MAX_BODY = 60_000
MIN_GH = (2, 40)  # `gh api --paginate --slurp`
TIMEOUT = 60
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
MARKER_RE = re.compile(r"<!-- prreview:([A-Za-z0-9_-]+) -->")
RUN_MARKER = "<!-- prreview-run:{} -->"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class PrReviewError(Exception):
    """A usage or environment problem with a clear message."""


# ---------------------------------------------------------------- runner ----

def default_runner(argv: list[str], timeout: int = TIMEOUT) -> tuple[int, str, str]:
    """Run an argument vector without a shell. (returncode, stdout, stderr)."""
    exe = shutil.which(argv[0])
    if exe is None:
        return 127, "", f"{argv[0]}: command not found"
    try:
        p = subprocess.run([exe, *argv[1:]], capture_output=True, text=True,
                           timeout=timeout, shell=False, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return p.returncode, p.stdout, p.stderr


class Env:
    """Holds the runner so tests can inject a fake `gh`/`git`."""

    def __init__(self, runner=None):
        self.run = runner or default_runner
        self._gh_ok = False

    def gh_json(self, argv: list[str]):
        rc, out, err = self.run(["gh", *argv])
        if rc != 0:
            raise PrReviewError(f"gh {' '.join(argv[:3])} failed: {(err or out).strip()[:300]}")
        try:
            return json.loads(out) if out.strip() else None
        except ValueError as exc:
            raise PrReviewError(f"gh returned invalid JSON: {exc}") from exc

    def gh_pages(self, endpoint: str) -> list:
        """A paginated list endpoint, flattened (`--paginate --slurp`)."""
        self.check_gh()
        sep = "&" if "?" in endpoint else "?"
        data = self.gh_json(["api", "--paginate", "--slurp", f"{endpoint}{sep}per_page=100"])
        out: list = []
        for page in data or []:
            out += page if isinstance(page, list) else [page]
        return out

    def check_gh(self) -> None:
        if self._gh_ok:
            return
        rc, out, err = self.run(["gh", "--version"])
        m = re.search(r"gh version (\d+)\.(\d+)", out or "")
        if rc != 0 or not m:
            raise PrReviewError(f"cannot run gh: {(err or out).strip()[:200] or 'not found'}")
        if (int(m.group(1)), int(m.group(2))) < MIN_GH:
            raise PrReviewError(
                f"gh {m.group(1)}.{m.group(2)} is too old: inline posting needs gh >= "
                f"{MIN_GH[0]}.{MIN_GH[1]} (`gh api --paginate --slurp`). Upgrade gh.")
        self._gh_ok = True


# ---------------------------------------------------------- diff parsing ----

@dataclass
class FileAnchors:
    right: set[int] = field(default_factory=set)
    left: set[int] = field(default_factory=set)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_OCTAL_RE = re.compile(r"\\([0-7]{3})")
_ESCAPES = {"t": "\t", "n": "\n", '"': '"', "\\": "\\", "a": "\a", "b": "\b",
            "f": "\f", "r": "\r", "v": "\v"}


def _unquote(s: str) -> str:
    """Undo git's C-quoting of a path: "b/sp\\303\\251.py" -> b/spé.py."""
    if not (len(s) >= 2 and s.startswith('"') and s.endswith('"')):
        return s
    raw = bytearray()
    body = s[1:-1]
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            m = _OCTAL_RE.match(body, i)
            if m:
                raw.append(int(m.group(1), 8))
                i += 4
                continue
            raw += _ESCAPES.get(body[i + 1], body[i + 1]).encode()
            i += 2
            continue
        raw += ch.encode()
        i += 1
    return raw.decode("utf-8", "replace")


def _header_path(rest: str, prefix: str) -> str | None:
    """Path from the text after `--- ` / `+++ `; None for /dev/null."""
    rest = rest.split("\t")[0] if not rest.startswith('"') else rest
    rest = _unquote(rest.rstrip())
    if rest == "/dev/null":
        return None
    return rest[2:] if rest.startswith(prefix) else rest


def parse_diff(text: str) -> dict[str, FileAnchors]:
    """Map path -> the old/new line numbers a review comment may anchor to."""
    files: dict[str, FileAnchors] = {}
    old_path: str | None = None
    new_path: str | None = None
    cur: FileAnchors | None = None
    old_n = new_n = old_left = new_left = 0
    in_header_pair = False
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        line = raw.removesuffix("\r")
        if old_left > 0 or new_left > 0:  # inside a hunk body
            tag = line[:1]
            if tag == "\\":
                continue
            if tag == "+":
                if cur is not None:
                    cur.right.add(new_n)
                new_n += 1
                new_left -= 1
            elif tag == "-":
                if cur is not None:
                    cur.left.add(old_n)
                old_n += 1
                old_left -= 1
            else:  # context (a bare empty line is a context line stripped of its space)
                if cur is not None:
                    cur.right.add(new_n)
                    cur.left.add(old_n)
                old_n += 1
                new_n += 1
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("diff --git "):
            old_path = new_path = None
            cur = None
            in_header_pair = False
            continue
        if line.startswith("--- "):
            old_path = _header_path(line[4:], "a/")
            in_header_pair = True
            continue
        if line.startswith("+++ ") and in_header_pair:
            new_path = _header_path(line[4:], "b/")
            key = new_path if new_path is not None else old_path
            if key is None:
                cur = None
            else:
                cur = files.setdefault(key, FileAnchors())
            in_header_pair = False
            continue
        m = _HUNK_RE.match(line)
        if m and cur is not None:
            old_n = int(m.group(1))
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_n = int(m.group(3))
            new_left = int(m.group(4)) if m.group(4) is not None else 1
    return files


def files_to_diff(files: list[dict]) -> str:
    """Rebuild a unified diff from `GET /pulls/N/files` entries (fallback when
    the whole diff is too large). A file without `patch` has no anchors."""
    parts: list[str] = []
    for f in files:
        patch = f.get("patch")
        name = f.get("filename")
        if not patch or not name:
            continue
        status = f.get("status")
        old = f.get("previous_filename") or name
        a = "/dev/null" if status == "added" else f"a/{old}"
        b = "/dev/null" if status == "removed" else f"b/{name}"
        parts.append(f"diff --git a/{old} b/{name}\n--- {a}\n+++ {b}\n{patch}")
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------- placement ----

def normalise_path(path) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/"):
        return None
    return p


def place(item: dict, files: dict[str, FileAnchors]) -> tuple[str, str | None, str | None]:
    """(status, side, reason): status is 'placed' or 'unplaced'.

    No snapping to a nearby line: a comment on code the finding is not about
    misleads. With `side` omitted a line placed LEFT only when the path has no
    RIGHT anchors at all (a deleted file or deletion-only diff)."""
    path = normalise_path(item.get("path"))
    line = item.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return "unplaced", None, "no-line"
    if path is None or path not in files:
        return "unplaced", None, "file-not-in-diff"
    fa = files[path]
    side = item.get("side")
    if side not in ("LEFT", "RIGHT"):
        if line in fa.right:
            return "placed", "RIGHT", None
        if not fa.right and line in fa.left:
            return "placed", "LEFT", None
        return "unplaced", None, "line-not-in-diff"
    mine, other = (fa.right, fa.left) if side == "RIGHT" else (fa.left, fa.right)
    if line in mine:
        return "placed", side, None
    return "unplaced", None, "side-not-in-diff" if line in other else "line-not-in-diff"


# ---------------------------------------------------------------- bodies ----

_MENTION_RE = re.compile(r"(?<![\w`@/])@([A-Za-z0-9][A-Za-z0-9_/-]*)")


def defang(text: str) -> str:
    """Stop a hostile diff from pinging users or forging markers."""
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return _MENTION_RE.sub(lambda m: f"`@{m.group(1)}`", text)


def _trunc(s: str, limit: int = MAX_BODY) -> str:
    return s if len(s) <= limit else s[: limit - 20] + "\n...(truncated)"


def comment_body(prefix: str, item: dict) -> str:
    return _trunc(f"{prefix} {defang(str(item.get('body', '')))}\n\n<!-- prreview:{item['id']} -->")


def bullet(item: dict, reason: str | None) -> str:
    where = item.get("path") or "general"
    if isinstance(item.get("line"), int) and not isinstance(item.get("line"), bool):
        where += f":{item['line']}"
    why = f" ({reason})" if reason else ""
    text = defang(str(item.get("body", ""))).replace("\n", "\n  ")
    return f"- `{where}`{why} {text}\n  <!-- prreview:{item['id']} -->"


def review_body(prefix: str, lead: str, bullets: list[str], run_id: str) -> str:
    head = f"{prefix} {defang(lead)}".strip()
    tail = f"\n\n{RUN_MARKER.format(run_id)}"
    out = head
    used = len(head) + len(tail) + 40
    kept: list[str] = []
    for n, b in enumerate(bullets):
        if used + len(b) + 1 > MAX_BODY:
            kept.append(f"... {len(bullets) - n} more; see the report file")
            break
        kept.append(b)
        used += len(b) + 1
    if kept:
        out += "\n\n" + "\n".join(kept)
    return out + tail


# ------------------------------------------------------------------ plan ----

def _resolve_pr(env: Env, pr: str | None) -> dict | None:
    argv = ["pr", "view"] + ([pr] if pr else []) + ["--json", "number,url,headRefOid"]
    rc, out, _ = env.run(["gh", *argv])
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)", str(data.get("url", "")))
    if not m or not data.get("headRefOid"):
        return None
    owner, repo = m.group(1), m.group(2)
    if not (_SLUG_RE.match(owner) and _SLUG_RE.match(repo)):
        return None
    return {"owner": owner, "repo": repo, "number": int(m.group(3)),
            "head": str(data["headRefOid"]), "url": data["url"]}


def _fetch_diff(env: Env, info: dict) -> dict[str, FileAnchors]:
    base = f"repos/{info['owner']}/{info['repo']}/pulls/{info['number']}"
    rc, out, _ = env.run(["gh", "api", base, "-H", "Accept: application/vnd.github.v3.diff"])
    if rc == 0 and out.strip():
        return parse_diff(out)
    return parse_diff(files_to_diff(env.gh_pages(f"{base}/files")))


def _head_distance(env: Env, pr_head: str) -> str:
    rc, out, _ = env.run(["git", "rev-list", "--left-right", "--count", f"HEAD...{pr_head}"])
    m = re.match(r"\s*(\d+)\s+(\d+)", out or "") if rc == 0 else None
    if m:
        ahead, behind = int(m.group(1)), int(m.group(2))
        return f"local HEAD is {ahead} commit(s) ahead and {behind} behind the PR"
    return "local HEAD differs from the PR head"


def _existing_markers(env: Env, info: dict) -> tuple[dict[str, set[str]], set[str]]:
    """({id: paths with a live (not outdated) inline comment}, ids in review summaries)."""
    base = f"repos/{info['owner']}/{info['repo']}/pulls/{info['number']}"
    inline: dict[str, set[str]] = {}
    for c in env.gh_pages(f"{base}/comments"):
        if not isinstance(c, dict) or c.get("position") is None:
            continue  # outdated: the code moved or changed, so re-post
        for fid in MARKER_RE.findall(str(c.get("body", ""))):
            inline.setdefault(fid, set()).add(str(c.get("path", "")))
    summary: set[str] = set()
    for r in env.gh_pages(f"{base}/reviews"):
        if isinstance(r, dict):
            summary.update(MARKER_RE.findall(str(r.get("body") or "")))
    return inline, summary


def _write_private(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_items(path: str) -> tuple[str, str, list[dict]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrReviewError(f"cannot read findings {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise PrReviewError("findings file must be an object with an `items` list")
    items: list[dict] = []
    seen: set[str] = set()
    for n, it in enumerate(data["items"]):
        if not isinstance(it, dict):
            continue
        if it.get("id") in (None, ""):
            # No id supplied (review-as): derive a stable one from the content so a
            # second run on the same PR is not mistaken for the first.
            basis = "\x00".join([str(data.get("prefix", "")), str(it.get("path", "")),
                                 str(it.get("line", "")), str(it.get("body", ""))])
            fid = "c" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
        else:
            fid = str(it.get("id"))
        if not _ID_RE.match(fid):
            fid = f"i{n}"
        if fid in seen:
            fid = f"{fid}-{n}"
        seen.add(fid)
        items.append({**it, "id": fid})
    return str(data.get("prefix", "")), str(data.get("lead", "")), items


def _sev(item: dict) -> int:
    return SEVERITY_ORDER.get(str(item.get("severity", "info")), 2)


def _sort_key(item: dict):
    line = item.get("line")
    return (_sev(item), str(item.get("path", "")),
            line if isinstance(line, int) and not isinstance(line, bool) else 0)


def make_plan(env: Env, findings: str, out: str, pr: str | None, dedup: bool) -> tuple[dict, int]:
    prefix, lead, items = _load_items(findings)
    env.check_gh()
    info = _resolve_pr(env, pr)
    if info is None:
        return {"status": "no-pr"}, 4
    files = None
    for _attempt in range(2):
        files = _fetch_diff(env, info)
        again = _resolve_pr(env, str(info["number"]))
        if again is not None and again["head"] == info["head"]:
            break
        if again is not None:
            info = again
        files = None
    if files is None:
        return {"status": "stale", "message": "the PR head moved while planning; re-run plan"}, 3

    rc, local, _ = env.run(["git", "rev-parse", "HEAD"])
    head_differs = rc != 0 or local.strip() != info["head"]
    notes: list[str] = []
    if head_differs:
        notes.append(_head_distance(env, info["head"]) +
                     "; push or check out the PR head and re-run for inline placement")

    inline_done, summary_done = ({}, set())
    if dedup:
        inline_done, summary_done = _existing_markers(env, info)

    placed: list[dict] = []
    unplaced: list[dict] = []
    skipped: list[dict] = []
    for it in items:
        if dedup and it["id"] in summary_done:
            skipped.append({"id": it["id"], "reason": "already-posted (summary)"})
            continue
        status, side, reason = place(it, files)
        path = normalise_path(it.get("path"))
        if head_differs:
            status, reason = "unplaced", reason if reason == "no-line" else "local-head-differs"
        if status == "placed" and dedup and path in inline_done.get(it["id"], set()):
            skipped.append({"id": it["id"], "reason": "already-posted"})
            continue
        if status == "placed":
            rc2, dirty, _ = env.run(["git", "status", "--porcelain", "--untracked-files=no",
                                     "--", f":(top){path}"])
            if rc2 == 0 and dirty.strip():
                status, reason = "unplaced", "working-tree-dirty"
        rec = {"id": it["id"], "path": it.get("path"), "line": it.get("line"),
               "severity": it.get("severity", "info"), "body": str(it.get("body", ""))}
        if status == "placed":
            placed.append({**rec, "path": path, "side": side})
        else:
            unplaced.append({**rec, "reason": reason})

    placed.sort(key=_sort_key)
    for extra in placed[MAX_INLINE:]:
        unplaced.append({k: v for k, v in extra.items() if k != "side"} | {"reason": "over-cap"})
    placed = placed[:MAX_INLINE]

    reasons: dict[str, int] = {}
    for u in unplaced:
        reasons[u["reason"]] = reasons.get(u["reason"], 0) + 1
    counts = {"placed": len(placed), "summary": len(unplaced), "skipped": len(skipped),
              "reasons": reasons}

    if not placed and not unplaced:
        return {"status": "nothing-to-post", "counts": counts, "skipped": skipped,
                "notes": notes}, 0

    run_id = uuid.uuid4().hex
    body = review_body(prefix, lead, [bullet(u, u["reason"]) for u in unplaced], run_id)
    payload = {"commit_id": info["head"], "event": "COMMENT", "body": body,
               "comments": [{"path": p["path"], "line": p["line"], "side": p["side"],
                             "body": comment_body(prefix, p)} for p in placed]}
    out_path = Path(out)
    payload_path = out_path.with_name(out_path.name + ".payload.json")
    plan = {"repo": f"{info['owner']}/{info['repo']}", "pr": info["number"],
            "head_sha": info["head"], "run_id": run_id, "prefix": prefix, "lead": lead,
            "placed": placed, "unplaced": unplaced, "skipped": skipped, "counts": counts,
            "payload_file": str(payload_path)}
    _write_private(payload_path, json.dumps(payload))
    _write_private(out_path, json.dumps(plan))

    why = ", ".join(f"{n} {r}" for r, n in sorted(reasons.items()))
    preview = f"About to post to PR #{info['number']}: {len(placed)} inline + {len(unplaced)} in summary"
    preview += f" ({why})" if why else ""
    if skipped:
        preview += f"; {len(skipped)} already posted"
    preview += "."
    dirty_n = reasons.get("working-tree-dirty", 0)
    if dirty_n:
        preview += (f" {dirty_n} findings on files with uncommitted changes: "
                    "commit or stash, then re-run.")
    for n in notes:
        preview += f" {n[0].upper()}{n[1:]}."
    return {"status": "ok", "plan_file": str(out_path), "pr": info["number"],
            "counts": counts, "notes": notes, "preview": preview}, 0


# ------------------------------------------------------------------ post ----

def classify(rc: int, out: str, err: str) -> str:
    """ok | pending | unprocessable | fatal | ambiguous. A 422 is atomic: nothing landed."""
    if rc == 0:
        return "ok"
    text = f"{err}\n{out}"
    m = re.search(r"HTTP (\d{3})", text) or re.search(r'"status"\s*:\s*"?(\d{3})', text)
    code = int(m.group(1)) if m else 0
    if code == 422:
        return "pending" if re.search(r"\bpending review\b", text, re.IGNORECASE) else "unprocessable"
    if code in (401, 403, 404, 429) or 400 <= code < 500:
        return "fatal"
    return "ambiguous"  # timeout, 5xx, empty or unparsable


def _submit(env: Env, repo: str, pr: int, payload_file: str):
    rc, out, err = env.run(["gh", "api", "-X", "POST", f"repos/{repo}/pulls/{pr}/reviews",
                            "--input", payload_file])
    return classify(rc, out, err), out, err


def _marker_posted(env: Env, repo: str, pr: int, run_id: str) -> str | None:
    marker = RUN_MARKER.format(run_id)
    try:
        for r in env.gh_pages(f"repos/{repo}/pulls/{pr}/reviews"):
            if isinstance(r, dict) and marker in str(r.get("body") or ""):
                return str(r.get("html_url") or "")
    except PrReviewError:
        return None
    return None


def _url(out: str) -> str:
    try:
        return str(json.loads(out).get("html_url", ""))
    except (ValueError, AttributeError):
        return ""


def run_post(env: Env, plan_file: str) -> tuple[dict, int]:
    try:
        plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))
        repo, pr, head = str(plan["repo"]), int(plan["pr"]), str(plan["head_sha"])
        payload_file = str(plan["payload_file"])
        run_id = str(plan["run_id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PrReviewError(f"cannot read plan {plan_file}: {exc}") from exc
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo):
        raise PrReviewError("plan has an invalid repo")
    n_inline, n_sum = len(plan.get("placed", [])), len(plan.get("unplaced", []))

    env.check_gh()
    cur = _resolve_pr(env, str(pr))
    if cur is None or cur["head"] != head:
        return {"status": "stale", "message": "the PR head moved since plan; re-run plan"}, 3

    kind, out, err = _submit(env, repo, pr, payload_file)
    if kind == "ambiguous":
        url = _marker_posted(env, repo, pr, run_id)
        if url is not None:
            return {"status": "posted", "url": url, "inline": n_inline, "summary": n_sum}, 0
        kind, out, err = _submit(env, repo, pr, payload_file)  # one retry, same payload
        if kind == "ambiguous":
            url = _marker_posted(env, repo, pr, run_id)
            if url is not None:
                return {"status": "posted", "url": url, "inline": n_inline, "summary": n_sum}, 0
            return {"status": "failed", "error": (err or out).strip()[:500] or "no response"}, 1
    if kind == "ok":
        return {"status": "posted", "url": _url(out), "inline": n_inline, "summary": n_sum}, 0
    if kind == "pending":
        return {"status": "failed",
                "error": "you have a pending (draft) review on this PR: submit or discard it, then re-run",
                "detail": (err or out).strip()[:300]}, 1
    if kind == "unprocessable":
        # Atomic 422: nothing landed. One summary-only retry carrying every item.
        payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        bullets = [bullet(p, "inline rejected") for p in plan.get("placed", [])]
        bullets += [bullet(u, u.get("reason")) for u in plan.get("unplaced", [])]
        payload["body"] = review_body(str(plan.get("prefix", "")), str(plan.get("lead", "")),
                                      bullets, run_id)
        payload["comments"] = []
        fb = Path(payload_file).with_name(Path(payload_file).name + ".summary.json")
        _write_private(fb, json.dumps(payload))
        kind2, out2, err2 = _submit(env, repo, pr, str(fb))
        if kind2 == "ok":
            return {"status": "fallback_summary", "url": _url(out2), "inline": 0,
                    "summary": n_inline + n_sum}, 0
        return {"status": "failed", "error": (err2 or out2).strip()[:500]}, 1
    return {"status": "failed", "error": (err or out).strip()[:500]}, 1  # 403/404/429...: no retry


# ------------------------------------------------------------------- cli ----

def main(argv: list[str] | None = None, runner=None) -> int:
    ap = argparse.ArgumentParser(prog="prreview.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--findings", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--pr", default=None)
    p.add_argument("--no-dedup", action="store_true")
    q = sub.add_parser("post")
    q.add_argument("--plan", required=True)
    q.add_argument("--confirmed", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    env = Env(runner)
    try:
        if args.cmd == "plan":
            if args.pr is not None and not re.fullmatch(r"\d{1,9}", args.pr):
                raise PrReviewError("--pr must be a PR number")
            result, code = make_plan(env, args.findings, args.out, args.pr, not args.no_dedup)
        else:
            if not args.confirmed:
                raise PrReviewError("refusing to post without --confirmed "
                                    "(ask the user, get an explicit yes, then pass it)")
            result, code = run_post(env, args.plan)
    except PrReviewError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 2 if "--confirmed" in str(exc) or "--pr" in str(exc) else 1
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
