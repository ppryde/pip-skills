# email-absolution Benchmark Templates

Five test templates for benchmarking the `elder` and `visitation` skills.
Templates range from obvious beginner mistakes to subtle gotchas. Use these
to verify skill output, regression-test after doctrine changes, and measure
how many planted violations the skill catches vs misses.

---

## Template Overview

| File | Stack | Difficulty | Planted violations |
|------|-------|------------|-------------------|
| `level-1-obvious.liquid` | Klaviyo / Liquid | ★☆☆☆☆ | 8 |
| `level-2-moderate.liquid` | Klaviyo / Liquid | ★★☆☆☆ | 7 |
| `level-3-handlebars.hbs` | SendGrid / Handlebars | ★★★☆☆ | 8 |
| `level-4-advanced.liquid` | Klaviyo / Liquid | ★★★★☆ | 7 |
| `level-5-gotchas.hbs` | SendGrid / Handlebars | ★★★★★ | 8 |

---

## Answer Key

### level-1-obvious.liquid — Expected mortal sins

| Rule | Violation |
|------|-----------|
| RENDER-001 | No `<!DOCTYPE>` declaration |
| ACCESS-004 | No `lang` attribute on `<html>` |
| RENDER-009 / GOTCHA-025 | Relative `src="/images/logo.png"` — no base URL in email clients |
| RENDER-009 / GOTCHA-025 | Relative `href="/dashboard"` on CTA — same problem |
| ACCESS-001 | `<img>` has no `alt` attribute |
| GOTCHA-024 | `var(--bg-color)` and `var(--link-color)` — CSS custom properties unsupported in Outlook and Gmail |
| RENDER-014 | `<a>` styled as button with `display: block` and `padding` — no VML fallback |
| UX-016 | No unsubscribe link — conditional or otherwise |

**Also expected (venial / counsel):**
- No `charset` meta (RENDER / ACCESS)
- No viewport meta
- No `role="presentation"` on any table
- `border-collapse` not set
- No `mso-table-lspace/rspace`
- No preheader
- No `margin: 0` on `<p>` elements
- No physical address

---

### level-2-moderate.liquid — Expected mortal sins

| Rule | Violation |
|------|-----------|
| UX-002 | Preheader uses `display: none` via CSS class `.preheader` — Gmail strips `<style>` block rules, so the preheader is not hidden and will show as body text in Gmail |
| RENDER-008 / GOTCHA-009 | `min-height: 80px` on `<td>` — ignored by Outlook 2007–2019 |
| RENDER-014 | `<a>` styled as button with `display: inline-block` and `padding` — no VML `<v:roundrect>` fallback |
| LIQ-001 | `{{ order.customer_name }}`, `{{ order.id }}`, `{{ order.item_count }}`, `{{ order.total }}`, `{{ item.name }}`, `{{ item.price }}` — all unfiltered with no `\| default:` |
| LIQ-012 | Variables use generic namespace (`order.*`, `customer.*`) — Klaviyo exposes data under `event.extra.*` and `person.*` |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table |
| DELIV-012 | No physical postal address in footer |

**Also expected (venial / counsel):**
- `border-collapse` not set explicitly on tables
- No `mso-table-lspace/rspace` on inner tables
- No `border="0"` on the image table wrapper
- No `height` HTML attribute on logo image
- `{% for %}` loop has no `{% else %}` fallback (LIQ-002)
- `{{ customer.unsubscribe_url }}` — wrong namespace for Klaviyo; also no `| escape`

---

### level-3-handlebars.hbs — Expected mortal sins

| Rule | Violation |
|------|-----------|
| HBS-002 | `{{{body_content}}}` — triple-stache on a content variable; XSS risk if content is not pre-sanitised |
| HBS-001 | `{{cta_url}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — no `{{#if}}` guard; dead hrefs if variables are undefined |
| RENDER-006 | `table { border-collapse: collapse; }` — must be `separate`; `collapse` causes Outlook rendering artefacts |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table element |
| RENDER-012 | `background-color: rgba(26, 86, 219, 1)` on CTA — use hex `#1a56db`; `rgba()` unreliable in Outlook |
| RENDER-014 | No VML `<v:roundrect>` fallback on CTA button — `display: inline-block` with padding is invisible in Outlook 2007–2019 |
| HTML-006 | Footer `<a>` elements (Unsubscribe, Email preferences, Privacy policy) have no inline `color` or `text-decoration` — styled via `<style>` block `.footer a` only, which Gmail strips |

**Also expected (venial / counsel):**
- `<br><br>` spacer between the main card and the footer table (HTML-007)
- `<div>` preheader — technically correct pattern but missing `visibility: hidden; opacity: 0` for full client coverage
- No `mso-table-lspace/rspace` on tables
- No `bgcolor` attribute on background cells
- No `border="0"` on image
- `{{preheader}}` — no fallback if variable is empty; preheader element will render blank in some clients

---

### level-4-advanced.liquid — Expected mortal sins

| Rule | Violation |
|------|-----------|
| HTML-015 | `float: left` on `.two-col-left` and `.two-col-right` — float is stripped/broken in many email clients including Gmail; two-column layout must use nested tables |
| HTML-014 | `@font-face` `font-family: 'Inter'` declared and applied on `<body>` — Outlook 2007–2019 and Gmail ignore web fonts entirely; no safe system font fallback defined beyond `Arial, sans-serif` in the `<body>` style (the `@font-face` declaration itself is the violation — it implies usage without guaranteed fallback in the template) |
| GOTCHA-008 | `background-image: url(...)` in inline `style` attribute on the hero `<td>` — Gmail strips `background-image` from inline styles entirely; hero background will be invisible in Gmail |
| GOTCHA-024 | `color: rgba(255, 255, 255, 0.85)` on subtitle text — `rgba()` with alpha channel unsupported in Outlook; text will render in default colour |
| HTML-007 | Two-column layout uses `<div class="clearfix">` containing floated `<div>` elements — not table-based; Outlook ignores the entire layout |
| RENDER-024 | `line-height: 36px` on `<h1>` and `line-height: 26px` on `<p>` — `mso-line-height-rule: exactly` present on `<p>` but absent on `<h1>` |
| RENDER-016 | `background-size: cover` on hero `<td>` inline style — Outlook ignores `background-size`; hero background image will not scale |

**Also expected (venial / counsel):**
- `border-radius: 8px` inline on stat divs — Outlook ignores border-radius on divs
- `letter-spacing` — Outlook has unreliable support
- `text-transform: uppercase` — broadly supported but verify
- `{{ unsubscribe_url }}` — no `| escape` filter (LIQ-003)
- Stat `<div>` containers will not render in Outlook — floated divs with padding/border-radius are invisible

---

### level-5-gotchas.hbs — Expected violations

This template is intentionally well-structured. The violations are subtle:

| Rule | Violation | Why it's subtle |
|------|-----------|-----------------|
| RENDER-006 | `cellpadding="16"` on the main content `<table>` — should be `cellpadding="0"` with padding managed on `<td>` elements inline | The table looks right and renders fine in most clients; only Outlook's legacy engine is affected |
| ACCESS-011 | Data summary table has `<th>` column headers without `scope` attribute — `<th align="left">Detail` and `<th align="right">Value` both lack `scope="col"` | The table visually looks accessible; the `<th>` elements are present, just missing `scope` |
| HBS-001 | `{{preheader}}`, `{{cta_url}}`, `{{cta_label}}`, `{{body_copy}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — none have `{{#if}}` guards or default values | These look like correct Handlebars output tags; the missing fallbacks are invisible in the source |
| GOTCHA-020 | Preheader `<div>` is missing `mso-hide: all` in its inline style — has `display: none; visibility: hidden; opacity: 0` but the critical `mso-hide: all` pair is absent, meaning Outlook may render the preheader text visibly | The preheader has three of the four required hiding properties — the one missing is the Outlook-specific one |
| RENDER-023 | No `bgcolor` HTML attribute on main content `<table>` — only `style="background-color: #ffffff"` | The white background renders correctly in all modern clients; `bgcolor` is only needed for very old clients |
| HTML-002 | `<h1>` has `margin-top: 0; margin-bottom: 16px` as separate directional properties but no `margin: 0` shorthand reset first — some Outlook versions apply default left/right heading margins | Directional margins appear correct; the issue is what's not explicitly set |
| ACCESS-007 | No link text issues in CTA — but `{{#each line_items}}` renders data rows with no empty-state `{{else}}` block (HBS-006) — if `line_items` is empty the table renders column headers with no rows, which is semantically invalid and confusing for screen readers | The template looks complete; the missing `{{else}}` only manifests with empty data |
| RENDER-017 | `mso-table-lspace: 0pt; mso-table-rspace: 0pt` is present on the outer wrapper tables but absent on the inner data summary table | The outer tables are correct — the inner data table is the one that's missed |

---

## Scoring

When running the elder skill against these templates, record:

| Metric | How to measure |
|--------|---------------|
| **Catch rate** | Planted violations found ÷ total planted |
| **False positives** | Violations reported that are not in the answer key |
| **Rule ID accuracy** | Correct rule ID cited for each finding |
| **Severity accuracy** | Mortal/venial/counsel correctly assigned |
| **Location precision** | File location cited correctly |

A well-calibrated skill should score ≥ 90% catch rate on levels 1–3 and
≥ 70% on levels 4–5. False positives above 3 per template indicate a doctrine
rule is over-firing.
