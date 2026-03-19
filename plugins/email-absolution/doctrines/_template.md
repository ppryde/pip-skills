# [Doctrine Name] — Email Doctrine

## Purpose

One paragraph: what this doctrine covers, what category of email heresy it guards against, and why it matters in production.

## Rule Catalog

Rules are numbered, severity-rated, and specify their detection method. Visitation applies all rules in this catalog when auditing a template.

**Severity levels:**
- `mortal` — Must be resolved before the template ships. These break rendering, accessibility, or deliverability.
- `venial` — Should be resolved. Counsel given, not blocking unless strictness is set to `strict`.
- `counsel` — Best practice. Aspirational guidance. Never blocking.

**Detection methods:**
- `detect: regex` — Visitation runs the pattern match mechanically against the HTML source.
- `detect: contextual` — Visitation applies judgment. No single pattern catches this.
- `detect: hybrid` — Regex catches obvious cases; contextual reasoning catches nuanced ones.

---

**[PREFIX-001]** `mortal` — Rule statement here.
> Why it matters. Which client is affected. Source: [source name](url).
> `detect: regex` — pattern: `your-regex-here`

**[PREFIX-002]** `venial` — Rule statement here.
> Why it matters. Source: [source name](url).
> `detect: contextual` — judgment criterion

**[PREFIX-003]** `counsel` — Rule statement here.
> Why it matters. Source: [source name](url).
> `detect: hybrid` — regex: `pattern` + contextual fallback

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
