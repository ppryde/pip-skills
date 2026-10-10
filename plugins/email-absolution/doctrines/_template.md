---
doctrine: name            # = the file's basename (this file is never loaded: names starting with `_` are ignored)
prefix: PREFIX            # the id prefix every rule in the file uses, e.g. LIQ
kind: core                # core | language
templating: liquid        # language kind only: implicit `templating=` for every rule in the file
scribe: constraints       # constraints | skip   (skip = audit-only file the Scribe never loads)
---

# [Doctrine Name] — Email Doctrine

## Purpose

One paragraph: what this doctrine covers, what category of email heresy it guards against, and why it matters in production.

## Rule Catalog

Rules are numbered, severity-rated, and specify their detection method. Visitation applies all rules in this catalog when auditing a template. `scripts/rules.py lint` enforces everything below; `scripts/rules.py build` regenerates `doctrines/INDEX.md` (never hand-edit it).

**Severity levels (dual-track):**
- Each rule declares **transactional** and **marketing** severity.
- Transactional must be **equal or stricter** than marketing. To exempt a track, use `applies: type=...` or conditional check text — never invert the two tracks.
- `mortal` — Must be resolved before the template ships. These break rendering, accessibility, or deliverability.
- `venial` — Should be resolved. Counsel given, not blocking unless strictness is set to `strict`.
- `counsel` — Best practice. Aspirational guidance. Never blocking.

**One defect, one rule.** Every defect has ONE canonical rule id that carries severity and detection. A duplicate stays in its own doctrine as an *alias* (see below): its id is preserved, it carries no severity and no detect, and a finding is reported once, under the canonical id, with `also: <alias ids>`. Two non-alias rules with an identical regex are a lint error.

**Detection methods (the grammar `lint` enforces):**
- `detect: regex` — Visitation runs the pattern match mechanically against the HTML source, line by line.
  - `pattern: `RE`` — one Python `re` pattern.
  - `patterns: `RE1` | `RE2`` — any match fires.
  - `absence: trigger=`RE` require=`RE`` — fires when the file matches the trigger but not the requirement.
  - Optional trailing note after ` — `. Keep every pattern linear-time: `lint` runs each one against a 64 KB hostile corpus with a 100 ms budget.
- `detect: contextual` — Visitation applies judgment. No single pattern catches this.
  - Free-text check, or `advisory[; check]` / `selection guidance[; check]` for rules that are guidance only. With no check text after `advisory`, the rule statement is the check.
- `detect: hybrid` — `pattern: `RE` + check: <text>` (or `patterns:` / `absence:` head). Regex catches the obvious cases; the check text is the contextual part.
- Optional `> `flags: verify`` — Phase-1 hits are candidates only; the model must read the matched line before reporting. `multiline` matches the pattern against the whole file instead of line by line.

**Applicability (optional `> `applies: ...`` line, absent = always):** `key=v1,v2; key=v3`. AND across keys, OR within a key's list. A config key that is absent or empty does not filter (run everything), with one exception: an `esp=` rule needs a configured `stack.esp`, and is skipped without one (as before the metadata existed). Language doctrines add an implicit `templating=<front-matter value>`. A `targets=` annotation is allowed only when EVERY client the rule's body names as a victim is in the list; a body that says "Outlook ... and some webmail/Gmail" gets no `targets`. `gen=no` marks an audit-only rule (infrastructure, DNS, headers): the Scribe skips it; audits ignore `gen`.

Vocabulary (mirrored from `scripts/rules.py`; a test asserts the two are equal):

- `esp`: klaviyo sendgrid postmark mailchimp resend custom
- `templating`: liquid handlebars mjml react-email maizzle html
- `targets`: outlook-2019 outlook-new gmail apple-mail yahoo
- `type`: marketing transactional
- `gen`: no

---

**[PREFIX-001]** `transactional: mortal | marketing: venial` — Rule statement here.
> Why it matters. Which client is affected. Source: [source name](url).
> `detect: regex` — pattern: `your-regex-here`

**[PREFIX-002]** `transactional: venial | marketing: counsel` — Rule statement here.
> Why it matters. Source: [source name](url).
> `applies: targets=outlook-2019`
> `detect: contextual` — judgment criterion

**[PREFIX-003]** `transactional: counsel | marketing: counsel` — Rule statement here.
> Why it matters. Source: [source name](url).
> `detect: hybrid` — pattern: `pattern` + check: contextual fallback
> `flags: verify`

**[PREFIX-004]** `alias of OTHER-001` — Same defect as OTHER-001, stated in this doctrine's own words.
> Kept for context and so that existing ids and overrides keep working. No severity, no detect, no applies.

---

## Support Matrix

Table of client support for key features in this domain. Columns: Feature | Safe (works everywhere) | Partial (works in some) | Risky (avoid).

| Feature | Safe | Partial | Risky |
|---------|------|---------|-------|
| Example | `<table>` layout | CSS Grid | `position: absolute` |

## Patterns & Code Examples

Concrete code examples. Label each CORRECT or INCORRECT. Prefer minimal examples that isolate the point.

```html
<!-- INCORRECT: [reason] -->
<example>bad code here</example>

<!-- CORRECT: [reason] -->
<example>good code here</example>
```

## Known Afflictions

Named client-specific bugs relevant to this doctrine. For each: symptom, affected clients, fix.

**[Affliction name]** — Symptom description.
Affects: [client list]. Source: hteumeuleu/email-bugs #NNN or other source.
Fix: `code or description`

## Sources

1. **Source name** — url. Used for: [which rules].
2. **Source name** — url. Used for: [which rules].
