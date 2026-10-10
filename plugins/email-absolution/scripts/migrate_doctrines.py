#!/usr/bin/env python3
"""One-shot, idempotent migration of doctrines/*.md to the rule-metadata format (WF-266 PR 1).

  python3 scripts/migrate_doctrines.py [--doctrines-dir DIR] [--stage1-only] [--report]

Stage 1 (structure only, no meaning change): front-matter, normalised detect grammar, flags.
Stage 2 (meaning): alias conversion, pattern-merge rulings, severity picks, `applies:` pass,
text fixes. Hard asserts: the rule-id set is unchanged (248), every regex that existed before
survives byte-identical except the named exceptions, severity changes are limited to the
table below, and everything the script writes lints clean. Running it twice changes nothing.

`--stage1-only --out DIR` exports the structure-normalised doctrines of an OLD tree; the golden
test captures its "before" set from that export so one parser (rules.py) sees both sides.
This script is deleted in a follow-up PR once the migration has shipped.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules as R  # noqa: E402

EXPECTED_RULES = 248

FILES = {  # file stem -> (prefix, kind, templating, scribe)
    "accessibility": ("ACCESS", "core", "", "constraints"),
    "content-ux": ("UX", "core", "", "constraints"),
    "deliverability": ("DELIV", "core", "", "constraints"),
    "gotchas": ("GOTCHA", "core", "", "constraints"),
    "html-css": ("HTML", "core", "", "constraints"),
    "rendering": ("RENDER", "core", "", "constraints"),
    "tooling": ("TOOL", "core", "", "skip"),
    "liquid": ("LIQ", "language", "liquid", "constraints"),
    "handlebars": ("HBS", "language", "handlebars", "constraints"),
    "mjml": ("MJML", "language", "mjml", "constraints"),
    "react-email": ("REMAIL", "language", "react-email", "constraints"),
    "maizzle": ("MZL", "language", "maizzle", "constraints"),
}

# ---------------------------------------------------------------- stage 1: detect grammar

SPECIAL_DETECT = {  # rule id -> new detect line (the ~15 irregular legacy lines)
    "ACCESS-007": "> `detect: regex` — pattern: `(?i)<a\\b[^>]*>\\s*(?:click here|read more|learn more|view more|see more|here|click)\\s*</a>` — case-insensitive",
    "ACCESS-010": "> `detect: regex` — patterns: `<p[^>]*>\\s*[•\\*\\-–▸▪►]\\s` | `<p[^>]*>\\s*\\d+[.)]\\s` — symbol bullet; numbered list in paragraph",
    "HTML-013": "> `detect: regex` — patterns: `<img(?![^>]*\\bwidth=)[^>]*>` | `<img(?![^>]*\\bheight=)[^>]*>`",
    "HTML-023": ("> `detect: hybrid` — pattern: `@font-face\\s*\\{` + check: if found, for each custom font name "
                 "in `@font-face` verify every `font-family` declaration using that name also includes a named "
                 "web-safe fallback (not just the generic `sans-serif`)"),
    "LIQ-019": ("> `detect: regex` — pattern: `\\{\\{[-\\s]*(?!person\\b|event\\b|organization\\b|unsubscribe_link\\b)"
                "[a-zA-Z_][a-zA-Z0-9_.]*[-\\s]*(?:\\|[^}]*)?\\}\\}` — matches output tags whose root variable "
                "is not in the four approved Klaviyo namespaces"),
    "MJML-001": ("> `detect: hybrid` — absence: trigger=`<mjml` require=`<mj-preview` + check: flag if a "
                 "hand-coded hidden div is present in source instead of `<mj-preview>`"),
    "MJML-005": "> `detect: regex` — pattern: `\"mjml\"\\s*:\\s*\"[\\^~]` — in package.json",
    "MJML-006": "> `detect: regex` — pattern: `\"mjml\"\\s*:\\s*\"[^\"]*(?:5\\.\\d|beta|alpha|rc\\d|canary)` — in package.json",
    "MJML-007": "> `detect: regex` — absence: trigger=`<mjml` require=`<mj-breakpoint`",
    "MJML-012": "> `detect: regex` — absence: trigger=`<mjml` require=`<mj-title`",
    "RENDER-006": ("> `detect: regex` — patterns: `<table(?![^>]*\\bcellpadding=)[^>]*>` | "
                   "`<table(?![^>]*\\bcellspacing=)[^>]*>` | `<table(?![^>]*\\bborder=)[^>]*>` | "
                   "`border-collapse\\s*:\\s*collapse` — each flags a `<table>` missing that attribute; "
                   "`collapse` anywhere in styles"),
    "HTML-003": ("> `detect: hybrid` — pattern: `style=\"(?![^\"]*mso-hide)[^\"]*display:\\s*none` + check: the "
                 "pattern inspects the whole `style` attribute, so mso-hide before or after display:none is "
                 "accepted; for every display:none inside a style block, check that the same rule also "
                 "contains mso-hide: all"),
    "HTML-005": ("> `detect: regex` — pattern: `font-family\\s*:\\s*(?:'[^',;\"]*'|\"[^\",;]*\"|"
                 "(?!(?:inherit|initial|unset)\\b)[A-Za-z][^,;\"'}]*)\\s*[;\"}]` — it nominates a declaration "
                 "naming a single font (no comma), so a full fallback stack, or inherit, is not flagged; "
                 "confirm the line before reporting"),
}
STAGE1_FLAGS = {  # structural: recorded caveats the old text already carried (EL-1 / multi-line pattern)
    "HTML-001": "verify", "HTML-003": "verify", "HTML-005": "verify", "RENDER-006": "verify",
    "GOTCHA-020": "multiline", "HTML-006": "multiline",
}

_GENERIC = re.compile(r"^> `detect: (regex|hybrid)` — pattern: `([^`]+)`(.*)$")


def _unwrap(tail: str) -> str:
    tail = tail.strip()
    if tail.startswith("(") and tail.endswith(")"):
        return tail[1:-1].strip()
    return tail


def normalise_detect(rule_id: str, line: str) -> str:
    if rule_id in SPECIAL_DETECT:
        return SPECIAL_DETECT[rule_id]
    d, err = R.parse_detect(line)
    if not err:
        return line
    m = _GENERIC.match(line)
    if not m:
        raise SystemExit(f"{rule_id}: detect line needs a SPECIAL_DETECT entry: {line[:100]}")
    kind, pat, tail = m.groups()
    note = _unwrap(tail)
    out = f"> `detect: {kind}` — pattern: `{pat}`"
    if note:
        out += f" — {note}"
    return out


def front_matter(stem: str) -> list:
    prefix, kind, templ, scribe = FILES[stem]
    fm = ["---", f"doctrine: {stem}", f"prefix: {prefix}", f"kind: {kind}"]
    if templ:
        fm.append(f"templating: {templ}")
    fm += [f"scribe: {scribe}", "---", ""]
    return fm


def split_blocks(lines):
    """Yield (start, end) spans of rule blocks in a line list (header .. before next boundary)."""
    n, i, spans = len(lines), 0, []
    while i < n:
        if R.HEADER_START.match(lines[i]):
            j = i + 1
            while j < n and not (R.HEADER_START.match(lines[j]) or lines[j].startswith("## ")
                                 or lines[j].strip() == "---"):
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def rid_of(line):
    m = re.match(r"^\*\*\[([A-Z]+-\d{3})\]\*\*", line)
    return m.group(1) if m else None


def stage1(stem: str, text: str) -> str:
    lines = text.split("\n")
    if lines[0].strip() != "---":
        lines = front_matter(stem) + lines
    out, last = [], 0
    for s, e in split_blocks(lines):
        out += lines[last:s]
        block = lines[s:e]
        rid = rid_of(block[0])
        new = [block[0]]
        for bl in block[1:]:
            if bl.startswith("> `detect:"):
                bl = normalise_detect(rid, bl)
            new.append(bl)
        new = set_flags(new, [STAGE1_FLAGS[rid]] if rid in STAGE1_FLAGS else None, keep_existing=True)
        out += new
        last = e
    out += lines[last:]
    return "\n".join(out)


def set_flags(block, flags, keep_existing=False):
    existing = [bl for bl in block if bl.startswith("> `flags:")]
    if keep_existing and existing:
        return block
    block = [bl for bl in block if not bl.startswith("> `flags:")]
    if not flags:
        return block
    idx = max(i for i, bl in enumerate(block) if bl.startswith("> `detect:"))
    block.insert(idx + 1, f"> `flags: {', '.join(flags)}`")
    return block


# ---------------------------------------------------------------- stage 2: meaning

ALIASES = {  # alias -> canonical (EL-4; ids are never removed)
    "DELIV-005": "RENDER-010",
    "GOTCHA-003": "RENDER-016",
    "GOTCHA-001": "RENDER-001",
    "GOTCHA-025": "RENDER-009",
    "GOTCHA-009": "RENDER-008",
    "GOTCHA-004": "RENDER-004",
    "RENDER-007": "ACCESS-003",
    "RENDER-020": "HTML-008",
    "RENDER-019": "HTML-006",
}

SEVERITY = {  # id -> (transactional, marketing); the only intended severity moves
    "RENDER-016": ("mortal", "mortal"),
    "GOTCHA-002": ("venial", "venial"),
}
SEVERITY_REASON = {
    "RENDER-016": "Gmail drops a <style> block over 16 KB wholesale; GOTCHA-003 (M/M) had it right",
    "GOTCHA-002": "80 KB is a margin against the as-delivered 102,400 B clip: should fix, not mortal",
}

# Named exceptions to "every regex survives byte-identical" - each has a test.
PATTERN_EXCEPTIONS = {
    "RENDER-009": ("merged GOTCHA-025's coverage (plain-relative, ./ ../, www., any-case http:) behind a guard that "
                   "excludes https:, mailto:, tel:, cid:, # and template delimiters ({{ {% *| %% <% ${ [[), so it no "
                   "longer fires on href=\"{{ url }}\""),
    "RENDER-008": "keeps both patterns (GOTCHA-009's min-height\\s*: also covers <style> blocks)",
    "RENDER-004": "extended to percentage components (GOTCHA-004's ReDoS pattern dropped)",
    "HTML-006": ("new multiline pattern <a\\s(?![^>]*(?<=\\s)style\\s*=)[^>]*href= (RENDER-019's inspected the "
                 "anchor text, not attributes; data-style= does not count)"),
    "HTML-010": "narrowed to position only (float moves to GOTCHA-012)",
    "GOTCHA-028": "own contextual detect (its regex was HTML-003's defect)",
    "HBS-002": "[^}] -> [^}{]: linear on a hostile run of '{{{' (was quadratic)",
    "HBS-008": "[^}]* -> [^}{]*: linear on a hostile run of '{{' (was quadratic)",
    "HBS-010": "same matches, written so the closing }} is checked once up front (was quadratic on a hostile '<' run)",
    "RENDER-022": "meta tags only (was identical to HTML-017's color-scheme, which is the CSS declaration)",
}
ALIAS_PATTERN_DROPS = {
    "GOTCHA-001": "RENDER-001's url\\s*\\( is a superset",
    "GOTCHA-025": "its coverage is merged into RENDER-009 with a template-delimiter guard",
    "GOTCHA-009": "kept in RENDER-008 patterns",
    "GOTCHA-004": "ReDoS (4.25 s on 20 KB) and fires on comma syntax; RENDER-004 extended",
    "RENDER-007": "identical to ACCESS-003",
    "RENDER-020": "HTML-008's pattern is identical modulo \\b",
    "RENDER-019": "HTML-006's new pattern replaces it",
}

APPLIES = {}
ESP_RULES = {"HBS-003": "sendgrid", "HBS-004": "postmark", "HBS-017": "sendgrid", "LIQ-012": "klaviyo",
             "LIQ-019": "klaviyo", "TOOL-008": "sendgrid,postmark,mailchimp"}
for _id, _v in ESP_RULES.items():
    APPLIES[_id] = f"esp={_v}"
OUTLOOK_ONLY = ["ACCESS-020", "GOTCHA-010", "HTML-003", "HTML-011", "HTML-014", "MJML-021", "MZL-012",
                "REMAIL-011", "RENDER-008", "RENDER-011", "RENDER-012", "RENDER-013", "RENDER-014",
                "RENDER-015", "RENDER-017", "RENDER-018", "RENDER-024"]
for _id in OUTLOOK_ONLY:
    APPLIES[_id] = "targets=outlook-2019"
GEN_NO = ["DELIV-001", "DELIV-002", "DELIV-003", "DELIV-006", "DELIV-011", "DELIV-016", "DELIV-017",
          "DELIV-018", "DELIV-019", "DELIV-020"]
for _id in GEN_NO:
    APPLIES[_id] = "gen=no"
# TOOL-008 is esp-conditional and audit-only (tooling.md is already scribe: skip, so no gen key needed)

# Absolute block rewrites: header statement, rationale line(s) and detect. Idempotent by construction.
REWRITE = {
    "GOTCHA-002": dict(
        header=("venial", "venial",
                "Keep total compiled HTML under 80 KB — a margin below the 102,400-byte Gmail clip (RENDER-010)."),
        rationale=("> Gmail clips at 102,400 bytes of the HTML *as delivered*, not as authored: ESP link rewriting "
                   "(every tracked `href` becomes a 200+ character redirect URL), the tracking pixel, merge-tag "
                   "expansion and quoted-printable inflation all add bytes after your build. A 90 KB source "
                   "template routinely arrives over 102 KB. 80 KB at source is therefore a real margin, so the "
                   "finding is venial (should fix) rather than counsel; the hard limit stays RENDER-010 (mortal). "
                   "Inline CSS is the primary cause of size inflation. Source: Litmus \"Gmail Clipping\"; caniemail.com."),
        detect="> `detect: contextual` — estimate compiled HTML byte count; flag from 80 KB (the clip itself, 102,400 B, is RENDER-010)",
    ),
    "RENDER-016": dict(
        header=("mortal", "mortal", None),
        rationale=("> Gmail drops a `<style>` block that exceeds 16,384 bytes wholesale, with no visible error: for a "
                   "responsive marketing email that is total layout failure in the largest consumer client. This is "
                   "distinct from the 102 KB HTML clip. Keep `<style>` blocks lean; inline critical layout properties "
                   "if a block grows large. Source: [caniemail.com/features/html-style](https://www.caniemail.com/features/html-style/); hteumeuleu/email-bugs."),
        detect="> `detect: contextual` — estimate size of each `<style>` block; flag if approaching or over 16 KB",
    ),
    "GOTCHA-012": dict(
        header=("mortal", "mortal",
                "Do not use `float` for layout: Outlook 2007–2019 crops the following text; other clients collapse it."),
        rationale=("> In Outlook Windows, placing a table with `float` inside a `<td>` with a background colour causes "
                   "text content following the floated table to be cropped and not displayed; elsewhere `float` is "
                   "partially supported and collapses unpredictably in webmail. Use MSO conditional table columns for "
                   "all multi-column layouts. Source: hteumeuleu/email-bugs #158."),
        detect="> `detect: regex` — pattern: `float\\s*:\\s*(?:left|right)`",
    ),
    "HTML-010": dict(
        header=("mortal", "venial",
                "Do not use `position: absolute`, `relative` or `fixed` for structural layout."),
        rationale=("> `position` is unsupported in most webmail clients and unreliable elsewhere. Use table-based "
                   "layout for all structural positioning. `float` is GOTCHA-012."),
        detect="> `detect: regex` — pattern: `style=\"[^\"]*position\\s*:\\s*(?:absolute|relative|fixed)`",
    ),
    "GOTCHA-028": dict(
        header=("venial", "venial", None),
        rationale=None,
        detect=("> `detect: contextual` — check the preheader: the first hidden `<div>` inside `<body>` must carry all "
                "six properties (display:none, visibility:hidden, opacity:0, max-height:0, overflow:hidden, "
                "mso-hide:all); the bare display:none/mso-hide pair is HTML-003"),
    ),
    "HTML-006": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — pattern: `<a\\s(?![^>]*(?<=\\s)style\\s*=)[^>]*href=` — a linked anchor with "
                "no inline style attribute at all (matched over the whole tag, so wrapped anchors work; "
                "`data-style=` and `title=\"style=1\"` are not a style attribute)"),
    ),
    "HTML-004": dict(
        header=(None, None,
                "Do not nest `<table>` elements more than 3–4 levels deep (MSO ghost tables are not counted)."),
        rationale=None,
        detect=("> `detect: contextual` — count table nesting depth, excluding tables inside MSO conditional "
                "comments (`<!--[if mso]>` ghost tables); flag structures exceeding 4 levels"),
    ),
    "RENDER-018": dict(
        header=(None, None,
                "Set the Outlook width with the `width` attribute or an MSO table — `max-width` is ignored by Outlook "
                "2007–2019; apply `max-width` via inline CSS on `<td>` or a wrapper `<div>` for modern clients."),
        rationale=None,
        detect=None,
    ),
    "RENDER-009": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — pattern: `(?i)(?:src|href)=[\"'](?!https:|mailto:|tel:|cid:|#|\\{|<%|\\$\\{|\\[\\[|"
                "\\*\\||%%)[^\"']+[\"']` — any src/href that is not https:, mailto:, tel:, cid:, an anchor or a "
                "template placeholder: root-relative, plain-relative (`logo.png`, `./a`, `../a`), protocol-relative, "
                "`www.`, and http: in any case"),
    ),
    "RENDER-008": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — patterns: `style=\"[^\"]*min-height\\s*:` | `min-height\\s*:` — the second "
                "also covers `<style>` blocks"),
    ),
    "HBS-002": dict(
        header=(None, None, None),
        rationale=None,
        detect="> `detect: regex` — pattern: `\\{\\{\\{[^}{]+\\}\\}\\}` — a triple-stache tag",
    ),
    "HBS-008": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — pattern: `\\{\\{[^}{]*[Dd]ate[^}{]*\\}\\}(?![^{]*formatDate)` — date variable "
                "without format helper"),
    ),
    "HBS-010": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — pattern: `\\{\\{#if(?=[^}]*\\}\\})[^}]*(?:===|!==|>=|<=|>|<)` — "
                "a comparison operator inside an {{#if}} tag"),
    ),
    "RENDER-022": dict(
        header=(None, None, None),
        rationale=None,
        detect="> `detect: regex` — pattern: `<meta[^>]*\\bcolor-scheme` — check for presence in head",
    ),
    "RENDER-004": dict(
        header=(None, None, None),
        rationale=None,
        detect=("> `detect: regex` — pattern: `rgba?\\(\\s*[\\d.]+%?\\s+[\\d.]+%?\\s+[\\d.]+%?` — whitespace-separated "
                "components (CSS Color Level 4)"),
    ),
}
RATIONALE_APPEND = {
    "HTML-008": "Padding is honoured on `<td>` and ignored on `<p>`, `<div>`, `<a>` and `<img>` in Outlook, so apply it to the `<td>`.",
}

HEADER_RE = re.compile(r"^(\*\*\[[A-Z]+-\d{3}\]\*\*)\s+(.*?)\s+—\s+(.*)$")


def stage2(stem: str, text: str) -> str:
    lines = text.split("\n")
    out, last = [], 0
    for s, e in split_blocks(lines):
        out += lines[last:s]
        block = lines[s:e]
        rid = rid_of(block[0])
        out += rewrite_block(rid, block)
        last = e
    out += lines[last:]
    return "\n".join(out)


def rewrite_block(rid, block):
    m = HEADER_RE.match(block[0])
    tag, sevtok, stmt = m.groups()
    meta = [bl for bl in block[1:] if bl.startswith(("> `detect:", "> `applies:", "> `flags:"))]
    body = [bl for bl in block[1:] if bl not in meta]  # rationale + trailing blanks
    detect = next((bl for bl in meta if bl.startswith("> `detect:")), None)
    flags = next((bl for bl in meta if bl.startswith("> `flags:")), None)

    if rid in ALIASES:
        header = f"{tag} `alias of {ALIASES[rid]}` — {stmt}"
        return [header] + body  # no detect, applies or flags

    rw = REWRITE.get(rid)
    sev_t, sev_m = (None, None)
    if rid in SEVERITY:
        sev_t, sev_m = SEVERITY[rid]
    if rw:
        t, mk, st = rw["header"]
        sev_t, sev_m = t or sev_t, mk or sev_m
        stmt = st or stmt
        if rw["detect"]:
            detect = rw["detect"]
        if rw["rationale"]:
            ri = [i for i, bl in enumerate(body) if bl.startswith("> ")]
            body = body[:ri[0]] + [rw["rationale"]] + body[ri[-1] + 1:] if ri else body
    if sev_t:
        sevtok = f"`transactional: {sev_t} | marketing: {sev_m}`"
    sentence = RATIONALE_APPEND.get(rid)
    if sentence and not any(sentence in bl for bl in body):
        for i, bl in enumerate(body):
            if bl.startswith("> ") and " Source:" in bl:
                body[i] = bl.replace(" Source:", f" {sentence} Source:", 1)
                break
    header = f"{tag} {sevtok} — {stmt}"

    new = [header]
    # trailing blank lines stay at the very end
    trail = []
    while body and not body[-1].strip():
        trail.insert(0, body.pop())
    new += body
    if rid in APPLIES:
        new.append(f"> `applies: {APPLIES[rid]}`")
    if detect:
        new.append(detect)
    if flags:
        new.append(flags)
    return new + trail


# ---------------------------------------------------------------- driver and asserts

def old_headers(ddir: Path):
    out = {}
    for p in R.doctrine_files(ddir):
        for line in p.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^\*\*\[([A-Z]+-\d{3})\]\*\*\s+`transactional: (\w+) \| marketing: (\w+)`", line)
            if m:
                out[m.group(1)] = (m.group(2), m.group(3))
    return out


def severity_diff(before, after):
    rows = []
    for rid in sorted(before):
        ob, nb = before[rid], after.get(rid)
        if nb is None:
            continue
        if ob == nb:
            continue
        for track, o, n in (("transactional", ob[0], nb[0]), ("marketing", ob[1], nb[1])):
            if o != n:
                rows.append((rid, track, o, n, SEVERITY_REASON.get(rid, "")))
    return rows


def run(ddir: Path, stage1_only=False, out_dir: Path = None, report=False, quiet=False):
    files = {p.stem: p for p in R.doctrine_files(ddir)}
    if set(files) != set(FILES):
        raise SystemExit(f"doctrine set differs from the known twelve: {sorted(set(files) ^ set(FILES))}")
    old_text = {s: p.read_text(encoding="utf-8") for s, p in files.items()}
    new_text = {}
    for stem, text in old_text.items():
        t = stage1(stem, text)
        if not stage1_only:
            t = stage2(stem, t)
        new_text[stem] = t

    # asserts on the result, in a scratch dir (nothing is written until they pass)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for stem, t in new_text.items():
            (tdp / f"{stem}.md").write_text(t, encoding="utf-8")
        docs, problems = R.load(tdp)
        if problems:
            raise SystemExit("migrated doctrines do not parse:\n" + "\n".join(f"{a}:{b}: {c}" for a, b, c in problems))
        new_ids = [r.id for r in R.all_rules(docs)]
        old_ids = []
        for t in old_text.values():
            old_ids += re.findall(r"^\*\*\[([A-Z]+-\d{3})\]\*\*", t, re.M)
        assert sorted(old_ids) == sorted(new_ids), "rule-id multiset changed"
        assert len(set(new_ids)) == len(new_ids) == EXPECTED_RULES, f"expected {EXPECTED_RULES} rules, got {len(new_ids)}"
        if not stage1_only:
            _, lint_problems = R.lint(tdp)
            if lint_problems:
                raise SystemExit("migrated doctrines do not lint:\n" + "\n".join(f"{a}:{b}: {c}" for a, b, c in lint_problems))
            _assert_patterns(old_text, new_text, docs)
        after = {r.id: (r.transactional, r.marketing) for r in R.all_rules(docs) if not r.is_alias}

    before = old_headers(ddir)
    rows = []
    if not stage1_only:
        rows = severity_diff(before, after)
        # aliases lose their own severity: report them too
        for rid, canon in sorted(ALIASES.items()):
            if rid in before:
                rows.append((rid, "both", "/".join(before[rid]), f"alias of {canon}", "EL-4 duplicate"))
        allowed = set(SEVERITY) | set(ALIASES)
        stray = {r[0] for r in rows} - allowed
        # severity of canonicals that rewrite headers (float/position) must be unchanged unless listed
        assert not stray, f"unexpected severity changes: {sorted(stray)}"

    target = out_dir or ddir
    target.mkdir(parents=True, exist_ok=True)
    changed = []
    for stem, t in new_text.items():
        dest = target / f"{stem}.md"
        if not dest.exists() or dest.read_text(encoding="utf-8") != t:
            dest.write_text(t, encoding="utf-8")
            changed.append(stem)
    if not stage1_only and out_dir is None:
        if not quiet:
            print(f"migrate: {len(changed)} file(s) changed; {EXPECTED_RULES} rules, ids unchanged")
    if report or not quiet:
        _print_report(rows, new_text, stage1_only)
    return rows


def _assert_patterns(old_text, stage1_text, docs):
    """Every pre-migration regex survives byte-identical except named exceptions."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for stem, t in old_text.items():
            (tdp / f"{stem}.md").write_text(stage1(stem, t), encoding="utf-8")
        pre_docs, probs = R.load(tdp)
        assert not probs, probs
    pre = {r.id: r for r in R.all_rules(pre_docs)}
    post = {r.id: r for r in R.all_rules(docs)}
    for rid, pr in pre.items():
        if pr.detect is None or pr.detect.kind == "contextual":
            continue
        po = post[rid]
        if rid in ALIASES:
            assert rid in ALIAS_PATTERN_DROPS or not (pr.detect.patterns or pr.detect.absence), \
                f"alias {rid} drops a pattern without a ruling"
            continue
        if rid in PATTERN_EXCEPTIONS:
            continue
        have = set(po.detect.patterns if po.detect else []) | set(po.detect.absence if po.detect else ())
        want = set(pr.detect.patterns) | set(pr.detect.absence)
        assert want <= have, f"{rid}: pattern changed without a named exception: {want - have}"


def _print_report(rows, new_text, stage1_only):
    if stage1_only:
        return
    print("\n## Severity diff (id | track | old | new | reason)")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print("\n## Pattern-merge rulings")
    for rid, why in PATTERN_EXCEPTIONS.items():
        print(f"- {rid}: {why}")
    for rid, why in ALIAS_PATTERN_DROPS.items():
        print(f"- {rid} (alias of {ALIASES[rid]}): pattern dropped - {why}")
    print("\n## applies: list with evidence")
    docs_text = "\n".join(new_text.values())
    for rid, val in sorted(APPLIES.items()):
        ev = _evidence(rid, docs_text, val)
        print(f"- {rid}: {val} | {ev}")


def _evidence(rid, text, val):
    if val == "gen=no":
        return "infrastructure/header/DNS check, not a template property"
    m = re.search(r"^\*\*\[" + rid + r"\]\*\*(.*?)(?=^\*\*\[|^## |^---)", text, re.S | re.M)
    body = m.group(1) if m else ""
    key = re.compile(r"Outlook|MSO|sendgrid|postmark|klaviyo", re.I)
    statement = body.split("\n", 1)[0].split(" — ", 1)[-1].strip()
    rationale = [ln for ln in body.split("\n")[1:] if ln.startswith("> ") and not ln.startswith("> `")]
    for sent in re.split(r"(?<=[.!?])\s+", " ".join(x[2:] for x in rationale)) + [statement]:
        if key.search(sent):
            return sent.strip().replace("|", "/")[:200]
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--doctrines-dir", default=str(R.DEFAULT_DOCTRINES))
    ap.add_argument("--stage1-only", action="store_true")
    ap.add_argument("--out", default="", help="write here instead of in place (stage-1 export)")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    run(Path(a.doctrines_dir), stage1_only=a.stage1_only, out_dir=Path(a.out) if a.out else None,
        report=a.report)
    if not a.stage1_only and not a.out:
        # the index is generated, never hand-written
        (Path(a.doctrines_dir) / R.INDEX_NAME).write_text(R.build_index(Path(a.doctrines_dir)), encoding="utf-8")
        print(f"wrote {R.INDEX_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
