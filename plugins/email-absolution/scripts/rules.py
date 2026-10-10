#!/usr/bin/env python3
"""Doctrine rule index for email-absolution (stdlib only, Python 3.9+).

Subcommands
  build [--check]        write (or verify) doctrines/INDEX.md
  lint [--overlaps]      structural checks on every doctrine; exit 1 on any error
  select ...             the active checklist for a config (never reads config files)
  show ID [ID...]        the full rule block(s), with file:line
  constraints ...        Scribe view: binding statements only (honours gen=no)
  scan --files F... ...  Phase 1 for a config: file:line | id | matched line for every active
                         regex rule (line by line; binary and >2 MiB files are listed as skipped;
                         5 s per-file timer on POSIX; matched lines cut to 200 characters)
  fire FILE...           first hit per regex rule, ignoring config (used by the golden test)

The doctrine markdown stays canonical. This script only parses it. `--doctrines-dir`
points every subcommand at another copy (the golden test uses an export of old doctrines).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCTRINES = PLUGIN_ROOT / "doctrines"
INDEX_NAME = "INDEX.md"

# Single vocabulary list. _template.md mirrors it and a test asserts the two are equal.
VOCAB = {
    "esp": ["klaviyo", "sendgrid", "postmark", "mailchimp", "resend", "custom"],
    "templating": ["liquid", "handlebars", "mjml", "react-email", "maizzle", "html"],
    "targets": ["outlook-2019", "outlook-new", "gmail", "apple-mail", "yahoo"],
    "type": ["marketing", "transactional"],
    "gen": ["no"],
}
SEVERITIES = ("counsel", "venial", "mortal")  # weakest first
RANK = {s: i for i, s in enumerate(SEVERITIES)}
KINDS = ("core", "language")
SCRIBE_VALUES = ("constraints", "skip")
FLAGS = ("verify", "multiline")
FRONT_KEYS = ("doctrine", "prefix", "kind", "templating", "scribe")
REGEX_BUDGET_S = 0.100
HOSTILE_LEN = 64 * 1024

HEADER_START = re.compile(r"^\*\*\[")
HEADER = re.compile(
    r"^\*\*\[([A-Z]+)-(\d{3})\]\*\*\s+"
    r"(?:`transactional: (\w+) \| marketing: (\w+)`|`alias of ([A-Z]+-\d{3})`)"
    r"\s+—\s+(\S.*)$"
)
DETECT_LINE = re.compile(r"^> `detect: (regex|contextual|hybrid)` — (.*)$")
SPAN = re.compile(r"`([^`]+)`")


@dataclass
class Detect:
    kind: str                      # regex | contextual | hybrid
    patterns: list = field(default_factory=list)
    absence: tuple = ()            # (trigger, require)
    check: str = ""
    advisory: bool = False
    note: str = ""


@dataclass
class Rule:
    id: str
    prefix: str
    doctrine: str
    file: Path
    line: int
    end: int
    transactional: str = ""
    marketing: str = ""
    alias_of: str = ""
    statement: str = ""
    detect: Detect = None
    applies: dict = field(default_factory=dict)
    flags: tuple = ()

    @property
    def is_alias(self) -> bool:
        return bool(self.alias_of)

    def severity(self, email_type: str) -> str:
        return self.transactional if email_type == "transactional" else self.marketing


@dataclass
class Doctrine:
    name: str
    path: Path
    front: dict
    rules: list


class Problems(list):
    def add(self, path, line, msg):
        self.append((Path(path).name, line, msg))


# --------------------------------------------------------------------------- parsing

def doctrine_files(ddir: Path):
    return sorted(
        p for p in ddir.glob("*.md") if not p.name.startswith("_") and p.name != INDEX_NAME
    )


def parse_front(lines, path, problems):
    """Return (front dict, index of first body line)."""
    if not lines or lines[0].strip() != "---":
        problems.add(path, 1, "missing front-matter block")
        return {}, 0
    front = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return front, i + 1
        raw = lines[i].split("#", 1)[0].strip()
        if not raw:
            continue
        if ":" not in raw:
            problems.add(path, i + 1, f"bad front-matter line: {lines[i]!r}")
            continue
        k, v = raw.split(":", 1)
        front[k.strip()] = v.strip()
    problems.add(path, 1, "front-matter block is not closed")
    return front, len(lines)


def parse_detect(line: str):
    """Parse one `> `detect: ...`` line. Returns (Detect, error)."""
    m = DETECT_LINE.match(line)
    if not m:
        return None, "detect line does not match '> `detect: regex|contextual|hybrid` — ...'"
    kind, rest = m.group(1), m.group(2).strip()
    if kind == "contextual":
        if not rest:
            return None, "contextual detect has no check text"
        mm = re.match(r"(advisory(?: note)?|selection guidance)(?:;\s*(.*))?$", rest)
        if mm:
            return Detect("contextual", check=(mm.group(2) or "").strip(), advisory=True), None
        return Detect("contextual", check=rest), None
    head, check = rest, ""
    if kind == "hybrid":
        if " + check: " not in rest:
            return None, "hybrid detect needs '<pattern head> + check: <text>'"
        head, check = rest.split(" + check: ", 1)
        if not check.strip():
            return None, "hybrid detect has an empty check"
    elif " + check: " in rest:
        return None, "regex detect must not carry '+ check:' (use hybrid)"
    d = Detect(kind, check=check.strip())
    pm = re.match(r"pattern: `([^`]+)`(.*)$", head)
    if pm:
        d.patterns, tail = [pm.group(1)], pm.group(2)
    else:
        sm = re.match(r"patterns: `([^`]+)`((?: \| `[^`]+`)*)(.*)$", head)
        am = re.match(r"absence: trigger=`([^`]+)` require=`([^`]+)`(.*)$", head)
        if sm:
            d.patterns = [sm.group(1)] + SPAN.findall(sm.group(2))
            tail = sm.group(3)
        elif am:
            d.absence, tail = (am.group(1), am.group(2)), am.group(3)
        else:
            return None, ("regex/hybrid detect must start with 'pattern: `RE`', "
                          "'patterns: `RE` | `RE`' or 'absence: trigger=`RE` require=`RE`'")
    tail = tail.rstrip()
    if tail and not tail.startswith(" — "):
        return None, f"text after the pattern must be introduced by ' — ' (got {tail[:40]!r})"
    d.note = tail[3:].strip() if tail else ""
    return d, None


def parse_applies(text: str):
    """'esp=a,b; targets=c' -> ({'esp': [...], ...}, error)."""
    out = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return None, f"applies entry {part!r} is not key=value"
        k, v = part.split("=", 1)
        k = k.strip()
        vals = [x.strip() for x in v.split(",") if x.strip()]
        if k not in VOCAB:
            return None, f"unknown applies key {k!r}"
        if k in out:
            return None, f"applies key {k!r} repeated"
        if not vals:
            return None, f"applies key {k!r} has no values"
        bad = [x for x in vals if x not in VOCAB[k]]
        if bad:
            return None, f"unknown {k} value(s) {bad} (allowed: {', '.join(VOCAB[k])})"
        out[k] = vals
    return out, None


def parse_file(path: Path, problems: Problems) -> Doctrine:
    lines = path.read_text(encoding="utf-8").split("\n")
    front, body_at = parse_front(lines, path, problems)
    name = path.stem
    prefix = front.get("prefix", "")
    rules = []
    i = body_at
    n = len(lines)
    while i < n:
        if not HEADER_START.match(lines[i]):
            i += 1
            continue
        start = i
        j = i + 1
        while j < n and not (
            HEADER_START.match(lines[j]) or lines[j].startswith("## ") or lines[j].strip() == "---"
        ):
            j += 1
        block = lines[start:j]
        i = j
        m = HEADER.match(block[0])
        if not m:
            problems.add(path, start + 1, f"rule header does not parse: {block[0][:80]!r}")
            continue
        pfx, num, tr, mk, alias, stmt = m.groups()
        r = Rule(id=f"{pfx}-{num}", prefix=pfx, doctrine=name, file=path, line=start + 1,
                 end=j, statement=stmt.strip(), alias_of=alias or "")
        if not alias:
            r.transactional, r.marketing = tr, mk
        detect_lines = []
        for off, bl in enumerate(block[1:], start=start + 2):
            if bl.startswith("> `detect:"):
                detect_lines.append((off, bl))
            elif bl.startswith("> `applies:"):
                am = re.match(r"^> `applies: (.*)`$", bl)
                if not am:
                    problems.add(path, off, f"{r.id}: malformed applies line")
                    continue
                ap, err = parse_applies(am.group(1))
                if err:
                    problems.add(path, off, f"{r.id}: {err}")
                else:
                    r.applies = ap
            elif bl.startswith("> `flags:"):
                fm = re.match(r"^> `flags: (.*)`$", bl)
                if not fm:
                    problems.add(path, off, f"{r.id}: malformed flags line")
                    continue
                fl = tuple(x.strip() for x in fm.group(1).split(",") if x.strip())
                bad = [x for x in fl if x not in FLAGS]
                if bad:
                    problems.add(path, off, f"{r.id}: unknown flag(s) {bad}")
                r.flags = fl
        if len(detect_lines) > 1:
            problems.add(path, detect_lines[1][0], f"{r.id}: more than one detect line")
        if detect_lines:
            d, err = parse_detect(detect_lines[0][1])
            if err:
                problems.add(path, detect_lines[0][0], f"{r.id}: {err}")
            r.detect = d
        rules.append(r)
        if prefix and pfx != prefix:
            problems.add(path, start + 1, f"{r.id}: prefix {pfx} != front-matter prefix {prefix}")
    return Doctrine(name=name, path=path, front=front, rules=rules)


def load(ddir: Path = DEFAULT_DOCTRINES):
    """Parse all doctrines. Returns (doctrines, problems)."""
    problems = Problems()
    docs = [parse_file(p, problems) for p in doctrine_files(ddir)]
    return docs, problems


def all_rules(docs):
    return [r for d in docs for r in d.rules]


def sha_of_set(ddir: Path) -> str:
    h = hashlib.sha256()
    for p in doctrine_files(ddir):
        h.update(p.name.encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------- lint

try:  # Python 3.11+
    from re import _constants as _sc, _parser as _sp
except ImportError:  # pragma: no cover - 3.9 / 3.10
    import sre_constants as _sc
    import sre_parse as _sp


def _literal_prefix(pattern: str) -> str:
    """The literal characters every match must start with, e.g. 'rgb(' for (?:rgb|rgba)\\(..."""
    out = []

    def walk(items):
        for op, arg in items:
            if op == _sc.LITERAL:
                out.append(chr(arg))
            elif op == _sc.SUBPATTERN:
                if not walk(arg[-1]):
                    return False
            elif op == _sc.BRANCH:
                if not walk(arg[1][0]):  # follow the first alternative only
                    return False
            elif op in (_sc.ASSERT, _sc.ASSERT_NOT, _sc.AT):
                continue
            else:
                return False
        return True

    try:
        walk(_sp.parse(pattern))
    except Exception:  # fall back to a plain textual prefix
        out = []
        for ch in pattern:
            if ch in "\\.^$*+?{}[]()|":
                break
            out.append(ch)
    return "".join(out)


def hostile_corpora(pattern: str):
    prefix = _literal_prefix(pattern)
    for unit in (" ", '"', "<", "{{", "' "):
        yield prefix + unit * (HOSTILE_LEN // len(unit))


class _Budget(Exception):
    pass


def regex_within_budget(compiled, corpus: str, budget: float = REGEX_BUDGET_S):
    """True if search finishes in budget. POSIX uses an interval timer (re polls signals)."""
    if not hasattr(signal, "setitimer"):
        return True  # no portable timeout; lint is a dev tool, scan has its own guards

    def _alarm(signum, frame):
        raise _Budget()

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        compiled.search(corpus)
        return True
    except _Budget:
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def lint(ddir: Path, overlaps: bool = False, budget: float = REGEX_BUDGET_S):
    docs, problems = load(ddir)
    files = doctrine_files(ddir)
    if not files:
        problems.add(ddir, 0, "no doctrine files found")
    seen_names = {}
    prefixes = {}
    for d in docs:
        fm = d.front
        for k in fm:
            if k not in FRONT_KEYS:
                problems.add(d.path, 1, f"unknown front-matter key {k!r}")
        if fm.get("doctrine") != d.name:
            problems.add(d.path, 1, f"front-matter doctrine {fm.get('doctrine')!r} != file name {d.name!r}")
        if not fm.get("prefix"):
            problems.add(d.path, 1, "front-matter needs prefix")
        else:
            if fm["prefix"] in prefixes:
                problems.add(d.path, 1, f"prefix {fm['prefix']} also used by {prefixes[fm['prefix']]}")
            prefixes[fm["prefix"]] = d.name
        kind = fm.get("kind")
        if kind not in KINDS:
            problems.add(d.path, 1, f"kind must be one of {KINDS} (got {kind!r})")
        if kind == "language":
            if fm.get("templating") not in VOCAB["templating"]:
                problems.add(d.path, 1, "language doctrine needs templating from the vocabulary")
        elif "templating" in fm:
            problems.add(d.path, 1, "core doctrine must not set templating")
        if fm.get("scribe") not in SCRIBE_VALUES:
            problems.add(d.path, 1, f"scribe must be one of {SCRIBE_VALUES} (got {fm.get('scribe')!r})")
        if not d.rules:
            problems.add(d.path, 1, "doctrine has no rules")

    rules = all_rules(docs)
    by_id = {}
    for r in rules:
        if r.id in by_id:
            problems.add(r.file, r.line, f"duplicate id {r.id} (also {by_id[r.id].file.name}:{by_id[r.id].line})")
        by_id[r.id] = r

    compiled = {}
    for r in rules:
        if r.is_alias:
            tgt = by_id.get(r.alias_of)
            if tgt is None:
                problems.add(r.file, r.line, f"{r.id}: alias target {r.alias_of} does not exist")
            elif tgt.is_alias:
                problems.add(r.file, r.line, f"{r.id}: alias target {r.alias_of} is itself an alias (one hop only)")
            if r.detect is not None or r.applies or r.flags:
                problems.add(r.file, r.line, f"{r.id}: an alias carries no detect, applies or flags")
            continue
        if r.transactional in RANK and r.marketing in RANK and RANK[r.transactional] < RANK[r.marketing]:
            problems.add(r.file, r.line,
                         f"{r.id}: transactional ({r.transactional}) is weaker than marketing ({r.marketing}); "
                         "exempt a track with `applies: type=` or check text, never by inverting")
        for tok in (r.transactional, r.marketing):
            if tok not in RANK:
                problems.add(r.file, r.line, f"{r.id}: unknown severity {tok!r}")
        if r.detect is None:
            problems.add(r.file, r.line, f"{r.id}: no detect line")
            continue
        if r.applies.get("gen") not in (None, ["no"]):
            problems.add(r.file, r.line, f"{r.id}: gen may only be 'no'")
        d = r.detect
        if d.kind != "contextual" and not d.patterns and not d.absence:
            problems.add(r.file, r.line, f"{r.id}: {d.kind} detect has no pattern")
        if d.kind == "contextual" and r.flags:
            problems.add(r.file, r.line, f"{r.id}: flags need a regex or hybrid detect")
        res = list(d.patterns) + list(d.absence)
        for pat in res:
            try:
                c = re.compile(pat)
            except re.error as e:
                problems.add(r.file, r.line, f"{r.id}: regex does not compile ({e}): {pat[:60]}")
                continue
            compiled[(r.id, pat)] = c

    # identical regex on two canonical rules regrows EL-4: hard error
    owner = {}
    for r in rules:
        if r.is_alias or r.detect is None:
            continue
        for pat in r.detect.patterns:
            if pat in owner and owner[pat] != r.id:
                problems.add(r.file, r.line, f"{r.id}: identical regex to {owner[pat]} (make one an alias)")
            owner.setdefault(pat, r.id)

    # hostile corpus budget
    for (rid, pat), c in compiled.items():
        for corpus in hostile_corpora(pat):
            if not regex_within_budget(c, corpus, budget):
                r = by_id[rid]
                problems.add(r.file, r.line,
                             f"{rid}: regex exceeds the {int(budget * 1000)} ms hostile-corpus budget: {pat[:60]}")
                break

    out = list(problems)
    if overlaps:
        toks = {r.id: set(re.findall(r"[a-z0-9-]+", r.statement.lower())) for r in rules if not r.is_alias}
        ids = sorted(toks)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                x, y = toks[ids[a]], toks[ids[b]]
                if x and y and len(x & y) / len(x | y) > 0.8:
                    out.append(("overlaps", 0, f"candidate pair {ids[a]} / {ids[b]}"))
    return docs, out


# --------------------------------------------------------------------------- selection

@dataclass
class Config:
    email_type: str
    esp: str = ""
    templating: str = ""
    targets: tuple = ()
    doctrine: str = ""


def _csv(s):
    return tuple(x.strip() for x in (s or "").split(",") if x.strip())


def select_rules(docs, cfg: Config):
    """Returns (active rules, filtered counts, warnings). Aliases never come back."""
    warnings = []
    filt = {"esp": 0, "templating": 0, "targets": 0, "type": 0, "alias": 0, "doctrine": 0}
    use_targets = bool(cfg.targets)
    if cfg.targets:
        bad = [t for t in cfg.targets if t not in VOCAB["targets"]]
        if bad:
            use_targets = False
            warnings.append(
                f"warning: unknown rendering_targets {', '.join(bad)} (allowed: "
                f"{', '.join(VOCAB['targets'])}); target filtering disabled for this run")
    use_templ = bool(cfg.templating)
    if cfg.templating and cfg.templating not in VOCAB["templating"]:
        use_templ = False
        warnings.append(
            f"warning: unknown templating {cfg.templating!r} (allowed: "
            f"{', '.join(VOCAB['templating'])}); templating filtering disabled for this run")
    if cfg.esp and cfg.esp not in VOCAB["esp"]:
        warnings.append(
            f"warning: unknown esp {cfg.esp!r} (allowed: {', '.join(VOCAB['esp'])}); "
            "esp-conditional rules are filtered out")
    if cfg.doctrine and cfg.doctrine not in {d.name for d in docs}:
        warnings.append(
            f"warning: unknown doctrine {cfg.doctrine!r} (available: {', '.join(d.name for d in docs)}); "
            "the checklist below is empty")
    active = []
    for d in docs:
        if cfg.doctrine and d.name != cfg.doctrine:
            filt["doctrine"] += len(d.rules)
            continue
        implicit = d.front.get("templating") if d.front.get("kind") == "language" else None
        for r in d.rules:
            if r.is_alias:
                filt["alias"] += 1
                continue
            ap = dict(r.applies)
            if implicit:
                ap["templating"] = [implicit]
            # esp-conditional rules need a known esp: with none configured they are skipped
            # (the behaviour on origin/main), unlike templating/targets/type.
            if "esp" in ap and cfg.esp not in ap["esp"]:
                filt["esp"] += 1
                continue
            if use_templ and "templating" in ap and cfg.templating not in ap["templating"]:
                filt["templating"] += 1
                continue
            if use_targets and "targets" in ap and not set(ap["targets"]) & set(cfg.targets):
                filt["targets"] += 1
                continue
            if "type" in ap and cfg.email_type not in ap["type"]:
                filt["type"] += 1
                continue
            active.append(r)
    return active, filt, warnings


def _check_text(r: Rule) -> str:
    d = r.detect
    if d.kind == "contextual":
        return d.check or r.statement
    if d.kind == "hybrid":
        return d.check
    return r.statement


def _pattern_rows(r: Rule):
    d = r.detect
    rows = [p for p in d.patterns]
    if d.absence:
        rows.append(f"absent: trigger={d.absence[0]} require={d.absence[1]}")
    return rows


def render_select(docs, cfg: Config) -> str:
    active, filt, warnings = select_rules(docs, cfg)
    names = sorted({r.doctrine for r in active})
    reasons = " ".join(f"{k}:{v}" for k, v in filt.items() if v)
    out = [f"# doctrines: {' '.join(names)} | {len(active)} active, "
           f"{sum(filt.values())} filtered ({reasons or 'none'})"]
    out += warnings
    out.append(f"# email_type={cfg.email_type} esp={cfg.esp or '-'} templating={cfg.templating or '-'} "
               f"targets={','.join(cfg.targets) or '-'}")
    rx = [r for r in active if r.detect.kind in ("regex", "hybrid")]
    cx = [r for r in active if r.detect.kind in ("contextual", "hybrid")]
    out.append("## REGEX   (id | sev | flags | pattern)")
    for r in rx:
        for row in _pattern_rows(r):
            out.append(f"{r.id} | {r.severity(cfg.email_type)} | {','.join(r.flags) or '-'} | {row}")
    out.append("## CONTEXTUAL   (id | sev | check)")
    for r in cx:
        tag = " [advisory]" if r.detect.advisory else ""
        out.append(f"{r.id} | {r.severity(cfg.email_type)} | {_check_text(r)}{tag}")
    return "\n".join(out) + "\n"


def render_constraints(docs, cfg: Config) -> str:
    """Scribe view. Honours gen=no (select/scan never do) and scribe: skip."""
    keep = [d for d in docs if d.front.get("scribe") == "constraints"]
    active, filt, warnings = select_rules(keep, cfg)
    active = [r for r in active if r.applies.get("gen") != ["no"]]
    out = [f"# constraints: {len(active)} rules"] + warnings
    for sev, title in (("mortal", "binding (met, never violated)"), ("venial", "should be met"),
                       ("counsel", "optional guidance")):
        out.append(f"## {sev.upper()}  {title}")
        for r in active:
            if r.severity(cfg.email_type) == sev:
                out.append(f"{r.id} | {r.statement}")
    return "\n".join(out) + "\n"


def render_show(docs, ids) -> tuple:
    by_id = {r.id: r for r in all_rules(docs)}
    out, missing = [], []
    for i in ids:
        r = by_id.get(i.upper())
        if r is None:
            missing.append(i)
            continue
        lines = r.file.read_text(encoding="utf-8").split("\n")[r.line - 1:r.end]
        while lines and not lines[-1].strip():
            lines.pop()
        out.append(f"<!-- {r.file.name}:{r.line} -->")
        out.extend(lines)
        out.append("")
    return "\n".join(out), missing


# --------------------------------------------------------------------------- overrides

def resolve_overrides(overrides: dict, docs):
    """Re-key a decisions.yml `overrides` map onto canonical ids.

    An entry keyed on an alias applies to its canonical rule. If both an alias and its
    canonical are keyed, the canonical's own entry wins and a note records the conflict.
    Unknown ids pass through untouched (the caller decides whether to warn).
    Returns ({canonical id: entry}, [notes]).
    """
    alias_to = {r.id: r.alias_of for r in all_rules(docs) if r.is_alias}
    resolved, notes = {}, []
    for key, entry in overrides.items():
        if key not in alias_to:
            resolved[key] = entry
    for key, entry in overrides.items():
        if key in alias_to:
            canon = alias_to[key]
            if canon in overrides:
                notes.append(f"override for {key} ignored: {canon} has its own entry, which wins")
            elif canon in resolved:
                notes.append(f"override for {key} ignored: another alias already set {canon}")
            else:
                resolved[canon] = entry
    return resolved, notes


# --------------------------------------------------------------------------- scan seed

MAX_SCAN_BYTES = 2 * 1024 * 1024


def read_scannable(path: Path):
    """(text, skipped_reason). Binary (NUL in the first 8 KB) and >2 MiB files are skipped, never silently."""
    try:
        size = path.stat().st_size
        if size > MAX_SCAN_BYTES:
            return "", f"over {MAX_SCAN_BYTES // (1024 * 1024)} MiB"
        raw = path.read_bytes()
    except OSError as e:
        return "", f"unreadable: {e.strerror or e}"
    if b"\0" in raw[:8192]:
        return "", "binary"
    return raw.decode("utf-8", errors="replace"), ""


def fire_ids(rules, text: str) -> dict:
    """{rule id: first matching line number} for regex/hybrid rules, line by line.

    A `multiline` rule is matched against the whole text. Absence rules fire at line 1
    when the trigger is present and the required pattern is not.
    """
    lines = text.split("\n")
    hits = {}
    for r in rules:
        if r.is_alias or r.detect is None or r.detect.kind == "contextual":
            continue
        d = r.detect
        if d.absence:
            if re.search(d.absence[0], text) and not re.search(d.absence[1], text):
                hits[r.id] = 1
            continue
        for pat in d.patterns:
            c = re.compile(pat)
            if "multiline" in r.flags:
                m = c.search(text)
                if m:
                    hits.setdefault(r.id, text.count("\n", 0, m.start()) + 1)
            else:
                for n, ln in enumerate(lines, 1):
                    if c.search(ln):
                        hits.setdefault(r.id, n)
                        break
    return hits


# --------------------------------------------------------------------------- scan

SCAN_FILE_TIMEOUT_S = 5.0   # per file, POSIX only (setitimer)
SCAN_LINE_CHARS = 200       # echoed matched lines are truncated: template content is data
SCAN_MAX_HITS = 20          # per rule per file; the rest is summarised, not listed


class ScanTimeout(Exception):
    pass


def _short(line: str) -> str:
    line = line.strip()
    return line if len(line) <= SCAN_LINE_CHARS else line[: SCAN_LINE_CHARS - 1] + "…"


def scan_text(rules, text: str):
    """Phase 1 over one file's text: [(line, id, matched line, flags)] plus {id: extra hits not listed}.

    Line by line, so a pattern's backtracking is bounded by one line. A rule flagged
    `multiline` is matched against the whole text instead. Absence rules report line 1
    when the trigger is present and the required pattern is not. Aliases and contextual
    rules never run; `gen` is ignored (an audit checks everything). A rule flagged `verify`,
    or whose detect note says "check ...", only nominates: scan marks it `[verify]`.
    """
    lines = text.split("\n")
    out, extra = [], {}
    for r in rules:
        if r.is_alias or r.detect is None or r.detect.kind == "contextual":
            continue
        d = r.detect
        # a detect note that says "check ..." means the pattern only nominates (as `flags: verify`)
        flags = ",".join(r.flags) + (",verify" if d.note and re.search(r"\bcheck\b", d.note, re.I) else "")
        if d.absence:
            if re.search(d.absence[0], text) and not re.search(d.absence[1], text):
                out.append((1, r.id, "absence: trigger present, required pattern missing", flags))
            continue
        seen = set()
        for pat in d.patterns:
            c = re.compile(pat)
            if "multiline" in r.flags:
                for m in c.finditer(text):
                    n = text.count("\n", 0, m.start()) + 1
                    seen.add((n, _short(lines[n - 1])))
            else:
                for n, ln in enumerate(lines, 1):
                    if c.search(ln):
                        seen.add((n, _short(ln)))
        hits = sorted(seen)
        for n, shown in hits[:SCAN_MAX_HITS]:
            out.append((n, r.id, shown, flags))
        if len(hits) > SCAN_MAX_HITS:
            extra[r.id] = len(hits) - SCAN_MAX_HITS
    out.sort(key=lambda h: (h[0], h[1]))
    return out, extra


def scan_with_timeout(rules, text: str, seconds: float = None):
    """scan_text under a per-file interval timer; raises ScanTimeout. Without setitimer (Windows) no timer runs."""
    seconds = SCAN_FILE_TIMEOUT_S if seconds is None else seconds
    if not hasattr(signal, "setitimer"):
        return scan_text(rules, text)

    def _alarm(signum, frame):
        raise ScanTimeout()

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return scan_text(rules, text)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def render_scan(docs, cfg: Config, files) -> str:
    active, _filt, warnings = select_rules(docs, cfg)
    rx = [r for r in active if r.detect is not None and r.detect.kind in ("regex", "hybrid")]
    out = list(warnings)
    out.append(f"# scan: {len(rx)} regex rules x {len(files)} file(s) | file:line | id | matched line "
               "([verify] = read the line and confirm before recording a finding)")
    skipped, timed_out, total = [], [], 0
    for fp in files:
        text, why = read_scannable(Path(fp))
        if why:
            skipped.append(f"skipped: {fp} ({why})")
            continue
        try:
            hits, extra = scan_with_timeout(rx, text)
        except ScanTimeout:
            timed_out.append(fp)
            continue
        for n, rid, shown, flags in hits:
            out.append(f"{fp}:{n} | {rid} | {shown}" + (" [verify]" if "verify" in flags else ""))
            total += 1
        for rid, more in sorted(extra.items()):
            out.append(f"{fp} | {rid} | (+{more} more matching lines not listed)")
    out += skipped
    out += [f"scan timed out: {fp} (apply Phase 1 to this file by hand)" for fp in timed_out]
    out.append(f"# scan done: {total} hit(s), {len(skipped)} skipped, {len(timed_out)} timed out")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- index

LETTER = {"mortal": "M", "venial": "V", "counsel": "C"}
DET = {"regex": "rx", "contextual": "ctx", "hybrid": "hyb"}


def _cell(s: str, width: int = 110) -> str:
    s = re.sub(r"\s+", " ", s).strip().replace("|", "\\|")
    return s if len(s) <= width else s[: width - 1].rstrip() + "…"


def _applies_cell(r: Rule) -> str:
    return _cell("; ".join(f"{k}={','.join(v)}" for k, v in r.applies.items()), 60)


def build_index(ddir: Path) -> str:
    docs, problems = load(ddir)
    if problems:
        raise SystemExit("cannot build INDEX.md: doctrines do not parse (run `rules.py lint`)")
    rules = all_rules(docs)
    aliases = [r for r in rules if r.is_alias]
    out = [
        "# Doctrine index",
        "",
        "<!-- GENERATED by scripts/rules.py build. Do not edit; edit the doctrines and rebuild. -->",
        "",
        f"rules: {len(rules)} ({len(rules) - len(aliases)} canonical, {len(aliases)} aliases) · "
        f"doctrines: {len(docs)} · sha256: {sha_of_set(ddir)}",
        "",
        "T / M = transactional / marketing severity (M mortal, V venial, C counsel). "
        "det: rx regex, ctx contextual, adv advisory (contextual, guidance only), hyb hybrid; "
        "`!` = verify the matched line. "
        "Regexes live in the doctrines (`rules.py select` / `show`), not here.",
    ]
    for d in docs:
        fm = d.front
        scope = f"{fm.get('kind')}" + (f", templating={fm['templating']}" if fm.get("templating") else "")
        out += ["", f"## {d.name}  ({d.path.name} · {scope} · scribe: {fm.get('scribe')})", "",
                "| ID | T | M | det | applies | check | line |", "|---|---|---|---|---|---|---|"]
        for r in d.rules:
            if r.is_alias:
                continue
            det = "adv" if r.detect.advisory else DET[r.detect.kind]
            det += "!" if "verify" in r.flags else ""
            out.append(f"| {r.id} | {LETTER[r.transactional]} | {LETTER[r.marketing]} | {det} | "
                       f"{_applies_cell(r)} | {_cell(_check_text(r))} | {r.line} |")
    out += ["", "## Aliases", "",
            "An alias is never checked: report the finding under the canonical id with `also: <alias>`.", "",
            "| alias | canonical | line |", "|---|---|---|"]
    for r in aliases:
        out.append(f"| {r.id} | {r.alias_of} | {r.doctrine}.md:{r.line} |")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- cli

def _add_cfg(p):
    p.add_argument("--email-type", required=True, choices=VOCAB["type"])
    p.add_argument("--esp", default="")
    p.add_argument("--templating", default="")
    p.add_argument("--targets", default="", help="comma list of rendering_targets")
    p.add_argument("--doctrine", default="")


def _cfg(a) -> Config:
    return Config(a.email_type, a.esp, a.templating, _csv(a.targets), a.doctrine)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rules.py", description=__doc__.split("\n")[0])
    ap.add_argument("--doctrines-dir", default=str(DEFAULT_DOCTRINES))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--check", action="store_true")
    lp = sub.add_parser("lint")
    lp.add_argument("--overlaps", action="store_true")
    _add_cfg(sub.add_parser("select"))
    _add_cfg(sub.add_parser("constraints"))
    sc = sub.add_parser("scan")
    _add_cfg(sc)
    sc.add_argument("--files", nargs="+", required=True)
    s = sub.add_parser("show")
    s.add_argument("ids", nargs="+")
    f = sub.add_parser("fire")
    f.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    ddir = Path(a.doctrines_dir)

    if a.cmd == "build":
        text = build_index(ddir)
        target = ddir / INDEX_NAME
        if a.check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                print(f"{INDEX_NAME} is out of date: run `python3 scripts/rules.py build`", file=sys.stderr)
                return 1
            return 0
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
        return 0
    if a.cmd == "lint":
        _, probs = lint(ddir, overlaps=a.overlaps)
        errs = [p for p in probs if p[0] != "overlaps"]
        for name, line, msg in probs:
            print(f"{name}:{line}: {msg}", file=sys.stderr if name != "overlaps" else sys.stdout)
        if errs:
            print(f"lint: {len(errs)} problem(s)", file=sys.stderr)
            return 1
        docs, _ = load(ddir)
        print(f"lint: ok ({len(all_rules(docs))} rules, {len(docs)} doctrines)")
        return 0
    docs, problems = load(ddir)
    if problems:
        for name, line, msg in problems:
            print(f"{name}:{line}: {msg}", file=sys.stderr)
        return 3
    if a.cmd == "select":
        sys.stdout.write(render_select(docs, _cfg(a)))
        return 0
    if a.cmd == "constraints":
        sys.stdout.write(render_constraints(docs, _cfg(a)))
        return 0
    if a.cmd == "scan":
        sys.stdout.write(render_scan(docs, _cfg(a), a.files))
        return 0
    if a.cmd == "show":
        text, missing = render_show(docs, a.ids)
        sys.stdout.write(text)
        if missing:
            print(f"unknown rule id(s): {', '.join(missing)}", file=sys.stderr)
            return 2
        return 0
    if a.cmd == "fire":
        rules = all_rules(docs)
        for fp in a.files:
            text, skipped = read_scannable(Path(fp))
            if skipped:
                print(f"skipped: {fp} ({skipped})", file=sys.stderr)
                continue
            for rid, ln in sorted(fire_ids(rules, text).items()):
                print(f"{fp}:{ln} | {rid}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
