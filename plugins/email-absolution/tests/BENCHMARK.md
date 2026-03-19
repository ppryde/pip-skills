# email-absolution Benchmark Templates

Five test templates for benchmarking the `elder` and `visitation` skills.
Templates range from obvious beginner mistakes to subtle gotchas. Use these
to verify skill output, regression-test after doctrine changes, and measure
how many planted violations the skill catches vs misses.

---

## Template Overview

| File | Stack | Difficulty | Planted violations |
|------|-------|------------|-------------------|
| `level-1-obvious.liquid` | Klaviyo / Liquid | ★☆☆☆☆☆ | 12 |
| `level-2-moderate.liquid` | Klaviyo / Liquid | ★★☆☆☆☆ | 11 |
| `level-3-handlebars.hbs` | SendGrid / Handlebars | ★★★☆☆☆ | 12 |
| `level-4-advanced.liquid` | Klaviyo / Liquid | ★★★★☆☆ | 11 |
| `level-5-gotchas.hbs` | SendGrid / Handlebars | ★★★★★☆ | 11 |
| `level-6-mjml.mjml` | SendGrid / MJML | ★★★★★★ | 10 |

---

## Answer Key

### level-1-obvious.liquid — Expected violations

**Mortal sins (8):**

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

**Venial / counsel (4):**

| Rule | Violation |
|------|-----------|
| LIQ-001 | `{{ customer.first_name }}` — no `\| default:` filter; renders blank if variable is undefined |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table element |
| ACCESS / RENDER | No `charset` meta in `<head>` — missing `<meta http-equiv="Content-Type" content="text/html; charset=utf-8">` |
| HTML-016 | `<td style="padding: 30px">` — shorthand padding; Outlook may apply differently per-side; should use directional longhand |

**Also expected (not scored):**
- No viewport meta
- `border-collapse` not set on tables
- No `mso-table-lspace/rspace`
- No preheader
- No `margin: 0` on `<p>` elements
- No physical address

---

### level-2-moderate.liquid — Expected violations

**Mortal sins (7):**

| Rule | Violation |
|------|-----------|
| UX-002 | Preheader uses `display: none` via CSS class `.preheader` — Gmail strips `<style>` block rules, so the preheader shows as body text in Gmail |
| RENDER-008 / GOTCHA-009 | `min-height: 80px` on `<td>` — ignored by Outlook 2007–2019 |
| RENDER-014 | `<a>` styled as button with `display: inline-block` and `padding` — no VML `<v:roundrect>` fallback |
| LIQ-001 | `{{ order.customer_name }}`, `{{ order.id }}`, `{{ order.item_count }}`, `{{ order.total }}`, `{{ item.name }}`, `{{ item.price }}` — all unfiltered with no `\| default:` |
| LIQ-012 | Variables use generic namespace (`order.*`, `customer.*`) — Klaviyo exposes data under `event.extra.*` and `person.*` |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table |
| DELIV-012 | No physical postal address in footer |

**Venial / counsel (4):**

| Rule | Violation |
|------|-----------|
| HTML-003 | Logo `<img>` has no `border="0"` HTML attribute — some clients add default borders |
| RENDER-011 | Logo `<img>` has no `height` HTML attribute — Outlook may collapse image height |
| LIQ-002 | `{% for item in order.items %}` loop has no `{% else %}` fallback — renders empty table if items is empty |
| LIQ-012 / LIQ-003 | `{{ customer.unsubscribe_url }}` — wrong Klaviyo namespace (should be `{{ unsubscribe_url }}`) and no `\| escape` filter |

**Also expected (not scored):**
- `border-collapse` not set explicitly on tables
- No `mso-table-lspace/rspace` on inner tables
- `<td style="padding: 0 40px 30px">` shorthand padding on body cell

---

### level-3-handlebars.hbs — Expected violations

**Mortal sins (8):**

| Rule | Violation |
|------|-----------|
| HBS-002 | `{{{body_content}}}` — triple-stache on a content variable; XSS risk if content is not pre-sanitised |
| HBS-001 | `{{cta_url}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — no `{{#if}}` guard; dead hrefs if variables are undefined |
| RENDER-006 | `table { border-collapse: collapse; }` — must be `separate`; `collapse` causes Outlook rendering artefacts |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table element |
| RENDER-012 | `background-color: rgba(26, 86, 219, 1)` on CTA — use hex `#1a56db`; `rgba()` unreliable in Outlook |
| RENDER-014 | No VML `<v:roundrect>` fallback on CTA button — `display: inline-block` with padding is invisible in Outlook 2007–2019 |
| HTML-006 | Footer `<a>` elements have no inline `color` or `text-decoration` — styled via `<style>` block `.footer a` only, which Gmail strips |

**Venial / counsel (4):**

| Rule | Violation |
|------|-----------|
| HTML-007 | `<br><br>` spacer between main card and footer table — should use `<table><tr><td height="X"></td></tr></table>` spacer |
| RENDER-017 | No `mso-table-lspace: 0pt; mso-table-rspace: 0pt` on outer wrapper tables |
| HBS-001 | `{{preheader}}` — no `{{#if}}` guard or default value; blank preheader element renders in some clients |
| GOTCHA-020 | Preheader `<div>` only has `display: none; max-height: 0; overflow: hidden; mso-hide: all` — missing `visibility: hidden; opacity: 0; color: transparent` for full client coverage |

**Also expected (not scored):**
- No `bgcolor` attribute on background cells
- No `border="0"` on images

---

### level-4-advanced.liquid — Expected violations

**Mortal sins (7):**

| Rule | Violation |
|------|-----------|
| HTML-015 | `float: left` on `.two-col-left` and `.two-col-right` — float is stripped/broken in many email clients including Gmail; two-column layout must use nested tables |
| HTML-014 | `@font-face` `font-family: 'Inter'` declared and applied on `<body>` — Outlook 2007–2019 and Gmail ignore web fonts; no guaranteed safe fallback in the compiled output |
| GOTCHA-008 | `background-image: url(...)` in inline `style` attribute on the hero `<td>` — Gmail strips `background-image` from inline styles entirely |
| GOTCHA-024 | `color: rgba(255, 255, 255, 0.85)` on subtitle text — `rgba()` with alpha channel unsupported in Outlook; text renders in default colour |
| HTML-007 | Two-column layout uses `<div class="clearfix">` containing floated `<div>` elements — Outlook ignores the entire layout |
| RENDER-024 | `line-height: 36px` on `<h1>` without `mso-line-height-rule: exactly` — Outlook applies its own line-height; combined with absent rule, heading spacing is broken |
| RENDER-016 | `background-size: cover` on hero `<td>` inline style — Outlook ignores `background-size`; hero background image will not scale |

**Venial / counsel (4):**

| Rule | Violation |
|------|-----------|
| LIQ-012 / LIQ-003 | `{{ unsubscribe_url }}` — wrong Klaviyo variable name (Klaviyo uses `{{ unsubscribe_link }}`) and no `\| escape` filter |
| GOTCHA-020 | Preheader `<div>` has `display: none; visibility: hidden; mso-hide: all` but is missing `opacity: 0; color: transparent` — incomplete suppression pattern |
| RENDER-024 | Hero `<p>` has `line-height: 24px` without `mso-line-height-rule: exactly` — Outlook may expand line spacing |
| GOTCHA-024 | `border-radius: 8px` inline on stat `<div>` containers — Outlook ignores border-radius on non-table elements; containers have no rounded corner fallback |

**Also expected (not scored):**
- `letter-spacing` — Outlook has unreliable support
- Stat `<div>` containers will not render in Outlook — floated divs with padding/border-radius are invisible

---

### level-5-gotchas.hbs — Expected violations

This template is intentionally well-structured. The violations are subtle:

**Main violations (11):**

| Rule | Violation | Why it's subtle |
|------|-----------|-----------------|
| RENDER-006 | `cellpadding="16"` on the main content `<table>` — should be `cellpadding="0"` with padding managed on `<td>` inline | The table looks right and renders fine in most clients; only Outlook's legacy engine adds unexpected internal spacing |
| ACCESS-011 | Data summary table `<th>` elements lack `scope` attribute — `<th align="left">Detail` and `<th align="right">Value` both missing `scope="col"` | The `<th>` elements are present, so the table looks accessible; the missing `scope` is invisible in the source |
| HBS-001 | `{{preheader}}`, `{{cta_url}}`, `{{cta_label}}`, `{{body_copy}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — none have `{{#if}}` guards or default values | These look like correct Handlebars output tags; the missing fallbacks are invisible in the source |
| GOTCHA-020 | Preheader `<div>` is missing `mso-hide: all` — has `display: none; visibility: hidden; opacity: 0` but the Outlook-specific property is absent | Three of four required hiding properties are present; the one missing is the Outlook-specific one |
| RENDER-023 | No `bgcolor` HTML attribute on main content `<table>` — only `style="background-color: #ffffff"` | The white background renders correctly in all modern clients; `bgcolor` is only needed for Outlook and very old clients |
| HTML-002 | `<h1>` has `margin-top: 0; margin-bottom: 16px` as directional properties with no `margin: 0` shorthand reset first — some Outlook versions apply default left/right heading margins | Directional margins appear correct; the issue is what is not explicitly set |
| HBS-006 / ACCESS-007 | `{{#each line_items}}` renders data rows with no `{{else}}` block — if `line_items` is empty the table renders column headers with no rows, which is semantically invalid | The template looks complete; the missing `{{else}}` only manifests with empty data |
| RENDER-017 | `mso-table-lspace: 0pt; mso-table-rspace: 0pt` is present on the outer wrapper tables but absent on the inner data summary table | The outer tables are correct — the inner data table is the one that is missed |
| HTML-001 | Main content `<table>` has two `class` attributes — `class="container"` is overridden by `class="email-body"` in HTML; the responsive `.container` media query will never match this element | The element visually functions; the duplicate attribute is easy to miss in dense markup |
| GOTCHA | `<body>` inline style is missing `-webkit-text-size-adjust: 100%` — the property is declared in the `<style>` block but not inline; iOS Safari may upscale font sizes when the style block is stripped | The `<style>` block version looks correct; the inline omission is only a problem when styles are stripped |
| RENDER-024 | Footer `<td>` has `line-height: 20px` without `mso-line-height-rule: exactly` — Outlook may override the line-height on footer text | The footer appears compact and correct in preview; the MSO rule is absent only on this cell |

**Also expected (not scored):**
- `letter-spacing: 1px` on `<th>` cells — Outlook support is inconsistent

---

### level-6-mjml.mjml — Expected violations

This template uses MJML syntax. The violations require knowledge of how MJML compiles
and which patterns introduce rendering bugs despite valid-looking MJML source:

**Main violations (10):**

| Rule | Violation | Why it's subtle |
|------|-----------|-----------------|
| UX-002 | No `<mj-preview>` element — compiled output will have no preheader text; inbox preview line will show first body text | In MJML, `<mj-preview>` is the correct preheader mechanism; omitting it is easy to miss since MJML handles so much automatically |
| RENDER-009 / GOTCHA-025 | `src="/images/hero-bg.jpg"` and `src="/images/logo-white.png"` — relative paths used in MJML attributes; compile output will contain relative URLs which break in all email clients | MJML passes through attribute values verbatim; relative URLs are not caught at compile time |
| ACCESS-001 | Logo `<mj-image alt="">` has an empty `alt` attribute — passes HTML validation but fails accessibility; decorative images should use `alt=""` intentionally but logos must have descriptive alt text | Empty `alt` is not a syntax error and MJML compiles it without warning |
| GOTCHA-024 | `color="rgba(255, 255, 255, 0.85)"` on `<mj-text>` subheading — MJML inlines this as `color: rgba(...)` which is unsupported in Outlook | MJML abstracts CSS; it is easy to forget that `rgba()` still compiles to unsupported CSS in Outlook |
| RENDER-012 | `background-color="#1a56db"` on `<mj-section>` with `background-url` — the compiled output uses a VML background conditional, but `background-size="cover"` is passed as inline style which Outlook ignores | The MJML looks complete; the problem is that `background-size` is stripped by Outlook regardless |
| HBS-002 | `{{{body_content}}}` — triple-stache in MJML `<mj-text>` body; compiled output renders raw HTML; XSS risk if `body_content` is not sanitised upstream | The MJML source looks like a content placeholder; the triple-stache semantics are easy to overlook |
| HBS-001 | `{{cta_url}}`, `{{first_name}}`, `{{unsubscribe_url}}`, `{{preferences_url}}`, `{{heading}}`, `{{subheading}}`, `{{feature_one_copy}}`, `{{feature_two_copy}}`, `{{cta_label}}` — no `{{#if}}` guards on any variable | MJML compiles all attributes to static HTML; empty variable outputs produce broken links and blank content silently |
| HTML-006 | Footer `<a>` links (`Unsubscribe`, `Email preferences`) are styled only via `css-class="footer-link"` CSS — compiled output puts styles in a `<style>` block which Gmail strips | The `css-class` approach is idiomatic MJML but produces non-inline styles that Gmail removes |
| HTML-014 | `<mj-font>` loads `Poppins` from Google Fonts and it is applied in `<mj-attributes>` as the default `font-family` — Outlook and Gmail ignore `@font-face` web fonts; no explicit system-font-only fallback is defined as a fallback path | The MJML defaults look professional; the Outlook/Gmail font fallback failure is hidden behind the abstraction |
| RENDER-014 | `<mj-button>` compiles to a `<table>` + `<a>` pattern — MJML does NOT generate a VML `<v:roundrect>` fallback; in Outlook the button renders as a plain underlined link with no background | MJML buttons look like they should be cross-client; the lack of VML output is non-obvious from the source |

**Also expected (not scored):**
- No MJML version comment (best practice for lockfile consistency)
- `<mj-style>` CSS is non-inline and will be stripped by Gmail
- `{{feature_one_copy}}` and `{{feature_two_copy}}` are unguarded like all other variables

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

### Minimum passing thresholds

| Template level | Min catch rate | Max false positives |
|---------------|---------------|---------------------|
| Level 1 | 100% | 3 |
| Level 2 | 90% | 3 |
| Level 3 | 85% | 4 |
| Level 4 | 80% | 4 |
| Level 5 | 80% | 4 |
| Level 6 | 70% | 5 |
