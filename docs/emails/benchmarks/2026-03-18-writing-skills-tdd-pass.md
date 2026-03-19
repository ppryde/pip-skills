# email-absolution — writing-skills TDD Benchmark
**Date:** 2026-03-18
**Branch:** email-skills
**Method:** superpowers:writing-skills (RED-GREEN-REFACTOR)
**Test template:** Order confirmation (Klaviyo / Liquid / Outlook 2019 + Gmail + Apple Mail)

---

## Test cases

Two skills tested: `elder` (full audit) and `scribe` (email generation).
Each run as: baseline subagent (no skill) vs with-skill subagent.

**Test input (elder):** Deliberately broken order-confirmation template with 16+ planted violations.
**Test task (scribe):** Generate a password reset email for Klaviyo + Liquid.

---

## elder — audit skill

### Baseline (no skill)

| Dimension | Result |
|-----------|--------|
| Total findings | 16 |
| Severity vocabulary | Critical / Significant / Moderate / Low |
| Rule IDs cited | None |
| Witchfinder voice | None |
| Verdict format | Table + prose |
| Preheader classified as | Low Priority (#16) |
| Unsubscribe link flagged | No |
| Physical address flagged | No |
| Klaviyo namespace checked | No |
| VML button required | Yes (Critical #5) |
| `role="presentation"` required | No |
| `display:none` + `mso-hide:all` | No |
| Default filters on all vars | No (only `item.price` noted) |

### With-skill (elder)

| Dimension | Result |
|-----------|--------|
| Total findings | 37 (17 mortal + 14 venial + 6 counsel) |
| Severity vocabulary | Mortal sin / Venial sin / Counsel from the elders |
| Rule IDs cited | Every finding (GOTCHA-024, RENDER-009, LIQ-012, etc.) |
| Witchfinder voice | Yes — full persona |
| Verdict format | Structured per SKILL.md spec |
| Preheader classified as | **Mortal sin** (UX-002) |
| Unsubscribe link flagged | Yes — Mortal sin (UX-016) |
| Physical address flagged | Yes — Venial sin (DELIV-012) |
| Klaviyo namespace checked | Yes — Mortal sin (LIQ-012) |
| VML button required | Yes — Mortal sin (RENDER-014) |
| `role="presentation"` required | Yes — Mortal sin (RENDER-007/ACCESS-003) |
| `display:none` + `mso-hide:all` | Yes — Mortal sin (HTML-003) |
| Default filters on all vars | Yes — all 5 output variables flagged (LIQ-001) |

### Key delta

Issues found by with-skill but **missed by baseline**:

1. `role="presentation"` missing on layout table
2. `border="0"` and `cellpadding="0"` required on layout tables
3. `display:none` without `mso-hide:all` companion
4. `<p>` elements without `margin: 0`
5. Missing `<title>` in `<head>`
6. Default filters missing on `customer.first_name`, `order.id`, `item.name`, `item.quantity`
7. Klaviyo namespace violation — `customer.first_name` / `order.id` undefined in Klaviyo context
8. Unsubscribe link absent (deliverability + GDPR)
9. Physical mailing address absent (CAN-SPAM)
10. `{% for %}` loop has no `{% else %}` empty fallback
11. Whitespace control `{%- -%}` missing on loop tags
12. CTA copy "View Order" is screen-reader-generic without `order.id`
13. Missing company name / support contact in footer
14. `mso-table-lspace` / `mso-table-rspace` not set
15. Missing `x-apple-disable-message-reformatting` meta
16. Counsel: dark mode meta tags, `bgcolor` attribute, first-sentence Apple Intelligence, money filter, plain-text MIME part

Preheader was rated "Low Priority" by baseline, **Mortal sin** by with-skill — the single most impactful reclassification.

---

## scribe — generation skill

### Baseline (no skill)

Generated a reasonable-looking transactional email. Missing:

- No preheader element
- No `| default:` filters on any variable
- CSS shorthand `padding` on `<td>` elements
- Klaviyo variable namespace not considered (generic `{{ first_name }}` style)
- No MSO ghost table wrapping
- No declared assumptions
- No variables reference table
- No Klaviyo send path documentation
- No test checklist

### With-skill (scribe)

Generated a fully doctrine-compliant password reset template. Confirmed present:

| Feature | Doctrine rule |
|---------|--------------|
| Preheader with `&zwnj;` padding | RENDER-015 |
| All `padding-*` as longhand directional properties | HTML-006 |
| `\| default:` filter on every output variable | LIQ-001 |
| `\| escape` on URL variables | LIQ-003 |
| VML bulletproof button (`v:roundrect`) | RENDER-014 |
| `<!--[if mso]>` ghost table wrapping | RENDER-012 |
| `role="presentation"` on all layout tables | RENDER-007 |
| `border="0" cellpadding="0" cellspacing="0"` on all tables | RENDER-006 |
| `mso-table-lspace: 0pt; mso-table-rspace: 0pt` | RENDER-017 |
| `mso-line-height-rule: exactly` on text elements | RENDER-018 |
| Klaviyo `person.first_name` / `event.extra.*` namespacing | LIQ-012 |
| `\| strip_html` on string output variables | LIQ-003 |
| Web-safe font stack with fallbacks | HTML-005 |
| `{{ unsubscribe_link }}` in footer | UX-016 |
| Physical address in footer | DELIV-012 |
| `lang="en"` + `xml:lang="en"` on `<html>` | ACCESS-004 |
| Dark mode `@media (prefers-color-scheme: dark)` | HTML-016 |
| Color-scheme meta tags | RENDER-022 |
| Apple data-detectors suppressor | GOTCHA-017 |
| Gmail `u + #body a` link-colour fix | GOTCHA-016 |
| `{%- assign expiry = event.extra.expiry_hours \| default: 24 -%}` at top | LIQ-001 |
| Assumptions declared | scribe SKILL.md Step 3 |
| Variables reference table with Klaviyo namespaces | scribe SKILL.md Step 6 |
| Klaviyo send-path documentation | scribe SKILL.md Step 6 |
| 5-item test checklist | scribe SKILL.md Step 7 |

---

## Summary

Both skills pass GREEN phase with no loopholes requiring REFACTOR.

The elder skill produces **2.3× more findings** than baseline (37 vs 16), correctly reclassifies preheader from low-priority to mortal sin, and catches 16 issues the baseline misses entirely — including deliverability (unsubscribe, physical address), Klaviyo-specific namespace violations, and all accessibility mortal sins.

The scribe skill produces a template that complies with every auditable doctrine rule, includes documentation the baseline omits (assumptions, variables table, send path, test checklist), and uses Klaviyo-correct namespacing throughout.

---

## Doctrine loading — verified correct

| Skill | Doctrines loaded | Expected |
|-------|-----------------|----------|
| elder | rendering, html-css, content-ux, accessibility, deliverability, gotchas, tooling, liquid | ✅ 8/8 |
| scribe | rendering, html-css, accessibility, deliverability, gotchas, liquid | ✅ 6/6 (no content-ux, no tooling) |
