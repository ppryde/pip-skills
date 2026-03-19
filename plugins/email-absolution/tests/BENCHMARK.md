# email-absolution Benchmark Templates

Seven test templates for benchmarking the `elder` and `visitation` skills.
Templates range from obvious beginner mistakes to subtle gotchas, MJML-specific
compilation traps, and deliberate content/tone violations. Use these to verify
skill output, regression-test after doctrine changes, and measure how many
planted violations the skill catches vs misses.

---

## Template Overview

| File | Stack | Difficulty | Planted violations | Focus |
|------|-------|------------|-------------------|-------|
| `level-1-obvious.liquid` | Klaviyo / Liquid | ★☆☆☆☆☆☆ | 12 | Structural basics |
| `level-2-moderate.liquid` | Klaviyo / Liquid | ★★☆☆☆☆☆ | 11 | Structural + Liquid |
| `level-3-handlebars.hbs` | SendGrid / Handlebars | ★★★☆☆☆☆ | 12 | Structural + Handlebars |
| `level-4-advanced.liquid` | Klaviyo / Liquid | ★★★★☆☆☆ | 12 | Advanced rendering + Klaviyo namespacing |
| `level-5-gotchas.hbs` | SendGrid / Handlebars | ★★★★★☆☆ | 11 | Subtle structural |
| `level-6-mjml.mjml` | SendGrid / MJML | ★★★★★★☆ | 9 | MJML compilation |
| `level-7-content.hbs` | SendGrid / Handlebars | ★★★★★★★ | 9 | Content, tone, UX copy |

---

## Type Tags

Each violation is tagged with one or more type labels:

| Tag | Meaning |
|-----|---------|
| `HTML` | General HTML email attribute or structural rule (DOCTYPE, `border="0"`, `role`, `bgcolor`, etc.) |
| `CSS` | CSS compatibility — property unsupported or behaves differently in Outlook/Gmail (`rgba()`, `float`, `background-size`, etc.) |
| `LQ` | Liquid templating — Klaviyo variable namespace, filters, loop fallbacks |
| `HBS` | Handlebars templating — `{{#if}}` guards, triple-stache XSS, `{{#each}}` fallbacks |
| `MJML` | MJML compilation behaviour — how MJML abstractions translate (or fail to translate) to compiled output |
| `ACCESS` | Accessibility — `alt`, `scope`, `role`, ARIA, screen reader concerns |
| `DELIV` | Deliverability — physical address, unsubscribe compliance, spam signals |
| `UX` | User experience — preheader, CTA hierarchy, inbox preview |
| `TONE` | Copy quality, tone of voice, personalisation, brand voice |

---

## Answer Key

### level-1-obvious.liquid — Expected violations

**Mortal sins (8):**

| Rule | Violation | Type |
|------|-----------|------|
| RENDER-001 | No `<!DOCTYPE>` declaration | `HTML` |
| ACCESS-004 | No `lang` attribute on `<html>` | `HTML` `ACCESS` |
| RENDER-009 / GOTCHA-025 | Relative `src="/images/logo.png"` — no base URL in email clients | `HTML` |
| RENDER-009 / GOTCHA-025 | Relative `href="/dashboard"` on CTA — same problem | `HTML` |
| ACCESS-001 | `<img>` has no `alt` attribute | `ACCESS` |
| GOTCHA-024 | `var(--bg-color)` and `var(--link-color)` — CSS custom properties unsupported in Outlook and Gmail | `CSS` |
| RENDER-014 | `<a>` styled as button with `display: block` and `padding` — no VML fallback | `HTML` |
| UX-016 | No unsubscribe link — conditional or otherwise | `DELIV` `UX` |

**Venial / counsel (4):**

| Rule | Violation | Type |
|------|-----------|------|
| LIQ-001 | `{{ customer.first_name }}` — no `\| default:` filter; renders blank if variable is undefined | `LQ` |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table element | `HTML` `ACCESS` |
| ACCESS / RENDER | No `charset` meta in `<head>` — missing `<meta http-equiv="Content-Type" content="text/html; charset=utf-8">` | `HTML` |
| HTML-016 | `<td style="padding: 30px">` — shorthand padding; Outlook may apply differently per-side; should use directional longhand | `CSS` |

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

| Rule | Violation | Type |
|------|-----------|------|
| UX-002 | Preheader uses `display: none` via CSS class `.preheader` — Gmail strips `<style>` block rules, so the preheader shows as body text in Gmail | `CSS` `UX` |
| RENDER-008 / GOTCHA-009 | `min-height: 80px` on `<td>` — ignored by Outlook 2007–2019 | `CSS` |
| RENDER-014 | `<a>` styled as button with `display: inline-block` and `padding` — no VML `<v:roundrect>` fallback | `HTML` |
| LIQ-001 | `{{ order.customer_name }}`, `{{ order.id }}`, `{{ order.item_count }}`, `{{ order.total }}`, `{{ item.name }}`, `{{ item.price }}` — all unfiltered with no `\| default:` | `LQ` |
| LIQ-012 | Variables use generic namespace (`order.*`, `customer.*`) — Klaviyo exposes data under `event.extra.*` and `person.*` | `LQ` |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table | `HTML` `ACCESS` |
| DELIV-012 | No physical postal address in footer | `DELIV` |

**Venial / counsel (4):**

| Rule | Violation | Type |
|------|-----------|------|
| HTML-003 | Logo `<img>` has no `border="0"` HTML attribute — some clients add default borders | `HTML` |
| RENDER-011 | Logo `<img>` has no `height` HTML attribute — Outlook may collapse image height | `HTML` |
| LIQ-002 | `{% for item in order.items %}` loop has no `{% else %}` fallback — renders empty table if items is empty | `LQ` |
| LIQ-012 / LIQ-003 | `{{ customer.unsubscribe_url }}` — wrong Klaviyo namespace (should be `{{ unsubscribe_url }}`) and no `\| escape` filter | `LQ` |

**Also expected (not scored):**
- `border-collapse` not set explicitly on tables
- No `mso-table-lspace/rspace` on inner tables
- `<td style="padding: 0 40px 30px">` shorthand padding on body cell

---

### level-3-handlebars.hbs — Expected violations

**Mortal sins (8):**

| Rule | Violation | Type |
|------|-----------|------|
| HBS-002 | `{{{body_content}}}` — triple-stache on a content variable; XSS risk if content is not pre-sanitised | `HBS` |
| HBS-001 | `{{cta_url}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — no `{{#if}}` guard; dead hrefs if variables are undefined | `HBS` |
| RENDER-006 | `table { border-collapse: collapse; }` — must be `separate`; `collapse` causes Outlook rendering artefacts | `CSS` |
| RENDER-007 / ACCESS-003 | No `role="presentation"` on any table element | `HTML` `ACCESS` |
| RENDER-012 | `background-color: rgba(26, 86, 219, 1)` on CTA — use hex `#1a56db`; `rgba()` unreliable in Outlook | `CSS` |
| RENDER-014 | No VML `<v:roundrect>` fallback on CTA button — `display: inline-block` with padding is invisible in Outlook 2007–2019 | `HTML` |
| HTML-006 | Footer `<a>` elements have no inline `color` or `text-decoration` — styled via `<style>` block `.footer a` only, which Gmail strips | `CSS` `HTML` |

**Venial / counsel (4):**

| Rule | Violation | Type |
|------|-----------|------|
| HTML-007 | `<br><br>` spacer between main card and footer table — should use `<table><tr><td height="X"></td></tr></table>` spacer | `HTML` |
| RENDER-017 | No `mso-table-lspace: 0pt; mso-table-rspace: 0pt` on outer wrapper tables | `HTML` |
| HBS-001 | `{{preheader}}` — no `{{#if}}` guard or default value; blank preheader element renders in some clients | `HBS` |
| GOTCHA-020 | Preheader `<div>` only has `display: none; max-height: 0; overflow: hidden; mso-hide: all` — missing `visibility: hidden; opacity: 0; color: transparent` for full client coverage | `HTML` `CSS` |

**Also expected (not scored):**
- No `bgcolor` attribute on background cells
- No `border="0"` on images

---

### level-4-advanced.liquid — Expected violations

**Mortal sins (7):**

| Rule | Violation | Type |
|------|-----------|------|
| HTML-015 | `float: left` on `.two-col-left` and `.two-col-right` — float is stripped/broken in many email clients including Gmail; two-column layout must use nested tables | `CSS` |
| HTML-023 | `@font-face` `font-family: 'Inter'` declared in `<style>` block — Gmail and Yahoo strip `<head>` style blocks, silently discarding the declaration; no guaranteed web-font rendering in the majority of clients | `CSS` |
| RENDER-001 | `background-image: url(...)` in inline `style` attribute on the hero `<td>` — Gmail strips the **entire** `style` attribute from any element containing `url()`, destroying all inline styles on that cell | `CSS` |
| RENDER-012 | `color: rgba(255, 255, 255, 0.85)` on subtitle text — `rgba()` with alpha channel unsupported in Outlook 2007–2019; no hex fallback provided; text renders in default colour | `CSS` |
| HTML-007 | Two-column layout uses `<div class="clearfix">` containing floated `<div>` elements — Outlook ignores the entire layout | `CSS` `HTML` |
| RENDER-024 | `line-height: 36px` on `<h1>` without `mso-line-height-rule: exactly` — Outlook applies its own line-height; combined with absent rule, heading spacing is broken | `CSS` |
| RENDER-015 | `background-image: url(...)` on hero `<td>` has no VML `<v:rect>/<v:fill>` fallback — background image is invisible in Outlook 2007–2019 | `CSS` |

**Venial / counsel (5):**

| Rule | Violation | Type |
|------|-----------|------|
| LIQ-019 | `{{ stats.revenue }}`, `{{ stats.orders }}`, `{{ period }}`, `{{ summary_subtitle }}`, `{{ body_copy }}`, `{{ cta_url }}` — bare variable names with no Klaviyo namespace prefix; all render as empty string in Klaviyo (require `event.extra.*` or `person.*`) | `LQ` |
| LIQ-012 / LIQ-003 | `{{ unsubscribe_url }}` — wrong Klaviyo variable name (Klaviyo uses `{{ unsubscribe_link }}`) and no `\| escape` filter | `LQ` |
| GOTCHA-020 | Preheader `<div>` has `display: none; visibility: hidden; mso-hide: all` but is missing `opacity: 0; color: transparent` — incomplete suppression pattern | `HTML` `CSS` |
| RENDER-024 | Hero `<p>` has `line-height: 24px` without `mso-line-height-rule: exactly` — Outlook may expand line spacing | `CSS` |
| GOTCHA-024 | `border-radius: 8px` inline on stat `<div>` containers — Outlook ignores border-radius on non-table elements; containers have no rounded corner fallback | `CSS` |

**Also expected (not scored):**
- `letter-spacing` — Outlook has unreliable support
- Stat `<div>` containers will not render in Outlook — floated divs with padding/border-radius are invisible

---

### level-5-gotchas.hbs — Expected violations

This template is intentionally well-structured. The violations are subtle:

**Main violations (11):**

| Rule | Violation | Type | Why it's subtle |
|------|-----------|------|-----------------|
| RENDER-006 | `cellpadding="16"` on the main content `<table>` — should be `cellpadding="0"` with padding managed on `<td>` inline | `HTML` | The table looks right and renders fine in most clients; only Outlook's legacy engine adds unexpected internal spacing |
| ACCESS-011 | Data summary table `<th>` elements lack `scope` attribute — `<th align="left">Detail` and `<th align="right">Value` both missing `scope="col"` | `ACCESS` | The `<th>` elements are present, so the table looks accessible; the missing `scope` is invisible in the source |
| HBS-001 | `{{preheader}}`, `{{cta_url}}`, `{{cta_label}}`, `{{body_copy}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — none have `{{#if}}` guards or default values | `HBS` | These look like correct Handlebars output tags; the missing fallbacks are invisible in the source |
| GOTCHA-020 | Preheader `<div>` is missing `mso-hide: all` — has `display: none; visibility: hidden; opacity: 0` but the Outlook-specific property is absent | `HTML` `CSS` | Three of four required hiding properties are present; the one missing is the Outlook-specific one |
| RENDER-023 | No `bgcolor` HTML attribute on main content `<table>` — only `style="background-color: #ffffff"` | `HTML` | The white background renders correctly in all modern clients; `bgcolor` is only needed for Outlook and very old clients |
| HTML-002 | `<h1>` has `margin-top: 0; margin-bottom: 16px` as directional properties with no `margin: 0` shorthand reset first — some Outlook versions apply default left/right heading margins | `CSS` | Directional margins appear correct; the issue is what is not explicitly set |
| HBS-006 / ACCESS-007 | `{{#each line_items}}` renders data rows with no `{{else}}` block — if `line_items` is empty the table renders column headers with no rows, which is semantically invalid | `HBS` `ACCESS` | The template looks complete; the missing `{{else}}` only manifests with empty data |
| RENDER-017 | `mso-table-lspace: 0pt; mso-table-rspace: 0pt` is present on the outer wrapper tables but absent on the inner data summary table | `HTML` | The outer tables are correct — the inner data table is the one that is missed |
| HTML-001 | Main content `<table>` has two `class` attributes — `class="container"` is overridden by `class="email-body"` in HTML; the responsive `.container` media query will never match this element | `HTML` | The element visually functions; the duplicate attribute is easy to miss in dense markup |
| GOTCHA | `<body>` inline style is missing `-webkit-text-size-adjust: 100%` — the property is declared in the `<style>` block but not inline; iOS Safari may upscale font sizes when the style block is stripped | `CSS` | The `<style>` block version looks correct; the inline omission is only a problem when styles are stripped |
| RENDER-024 | Footer `<td>` has `line-height: 20px` without `mso-line-height-rule: exactly` — Outlook may override the line-height on footer text | `CSS` | The footer appears compact and correct in preview; the MSO rule is absent only on this cell |

**Also expected (not scored):**
- `letter-spacing: 1px` on `<th>` cells — Outlook support is inconsistent

---

### level-6-mjml.mjml — Expected violations

This template uses MJML syntax. All violations are specific to how MJML compiles
or to the MJML attribute and layout model — they require knowledge beyond standard
HTML email rules:

**Main violations (9):**

| Rule | Violation | Type | Why it's MJML-specific |
|------|-----------|------|------------------------|
| MJML-001 / UX-002 | No `<mj-preview>` element — compiled output has no preheader; inbox preview shows first body text | `MJML` `UX` | `<mj-preview>` is the MJML-native preheader mechanism; a plain `<div display:none>` is not the right pattern in MJML |
| MJML-013 / RENDER-014 | `<mj-button>` compiles to `<table>` + `<a>` — MJML does **not** emit a VML `<v:roundrect>` fallback; Outlook renders a plain underlined link | `MJML` | This looks correct from MJML source; the missing VML only becomes visible in compiled output |
| MJML-019 | `<mj-all font-family="'Lato', Arial, sans-serif">` — web font set as global `mj-attributes` default; inflates compiled HTML (inlined on every `<td>`); Gmail strips `<mj-font>` link tag, silently losing the web font with no warning | `MJML` `CSS` | MJML's attribute system makes global defaults feel safe; the font inflation and link-strip failure are invisible until measured in compiled output |
| MJML-021 | `<mj-section background-url>` with `background-size="cover"` — MJML compiles a VML conditional for the background image but passes `background-size` as inline CSS which Outlook ignores entirely | `MJML` `CSS` | MJML appears to handle background images correctly; the `background-size` compile gap is non-obvious |
| MJML-015 | Two-column `<mj-section>` (feature cards, lines 89–102) missing `fluid-on-mobile="true"` — compiled output renders as fixed two-column layout on mobile; columns do not stack | `MJML` | `fluid-on-mobile` is a MJML-specific attribute on `<mj-section>`; without it multi-column sections never stack on narrow viewports |
| MJML-002 | `<mj-section padding="0">` default set via `<mj-attributes>` AND `<mj-column padding="24px 0">` on the hero column — MJML stacks section and column padding in the compiled output, creating double vertical spacing | `MJML` | The section and column padding declarations look intentional in MJML source; the stacking is a MJML layout model trap |
| MJML-010 | `<mj-raw>` block contains `{{promo_note}}` Handlebars variable — bypasses MJML's table structure and any sanitisation; user-controlled content in `<mj-raw>` is an injection risk; structural errors in the raw block are invisible at compile time | `MJML` `HBS` | `<mj-raw>` is idiomatic for one-off insertions but containing template variables makes it an injection risk covered by the updated MJML-010 |
| MJML-020 | Footer column uses `css-class="footer"` — MJML compiles `css-class` rules into a `<style>` block, not inline; Gmail strips the `<style>` block so any footer styles applied via `css-class` are lost | `MJML` `CSS` | `css-class` is the standard MJML mechanism for reusable styles; its non-inline compilation is a known MJML-Gmail gap |
| HBS-001 | `{{heading}}`, `{{subheading}}`, `{{first_name}}`, `{{body_copy}}`, `{{cta_url}}`, `{{cta_label}}`, `{{feature_one_copy}}`, `{{feature_two_copy}}`, `{{unsubscribe_url}}`, `{{preferences_url}}` — no `{{#if}}` guards or defaults on any variable | `HBS` | MJML compiles all attribute values verbatim; empty Handlebars variables produce broken links and blank rendered cells with no compile-time warning |

**Also expected (not scored):**
- No MJML version lock comment
- `<mj-section>` without explicit `background-color` on non-hero sections defaults to transparent

---

### level-7-content.hbs — Expected violations

This template is structurally sound. The violations are entirely in the copy,
content decisions, and UX writing — not in the HTML or CSS. Testing this template
verifies that the skill audits beyond rendering and flags content-quality sins.

**Run with tone profile:** `tests/configs/example-tone-profile.yaml` — the skill
should load this alongside the stack config when assessing level-7. Violations
are judged against the brand voice rules defined there, not generic best practice.

**Main violations (9):**

| Rule | Violation | Type |
|------|-----------|------|
| UX-002 | Preheader text is identical to the `<h1>` heading (`HUGE SUMMER SALE - DON'T MISS OUT!!!`) — both inbox slots used for the same message; the preheader adds no incremental information | `TONE` `UX` |
| UX-003 | `<h1>` is written entirely in ALL CAPS with multiple exclamation marks — aggressive tone, poor accessibility (screen readers may read as shouting), and inconsistent with most brand guidelines | `TONE` `ACCESS` |
| UX-015 | Primary CTA label is `Click Here` — no contextual information; screen readers announce "Click Here" with no destination context; weak conversion copy | `TONE` `ACCESS` |
| UX-014 | `Dear Valued Customer,` — no personalisation despite `{{first_name}}` being available and used elsewhere in the send; passive, depersonalised opening for a promotional email | `TONE` |
| UX-011 | Body copy uses passive voice throughout: `A sale has been prepared`, `discounts have been applied`, `items can be browsed` — indirect, brand-less tone that weakens urgency and trust | `TONE` |
| UX-013 | Urgency copy is vague and unanchored: `Limited time offer. Act now before it's too late!` — no expiry date, no end time, no specific scarcity signal; false urgency erodes trust | `TONE` `UX` |
| UX-017 | Three competing primary CTAs with no visual hierarchy: `Click Here` button (red), `Shop Women's` button (dark), and `shop the men's sale` text link — reader has no clear primary action | `UX` |
| UX-016 | Unsubscribe block is 3 sentences of legal boilerplate followed by `Click here to unsubscribe` — hostile, brand-less, and over-long; damages send reputation and reader trust | `TONE` `DELIV` |
| ACCESS-001 | Promotional image has `alt="promotional image"` — non-descriptive; fails accessibility and degrades experience when images are blocked | `ACCESS` `TONE` |

**Also expected (not scored):**
- No social proof, no value proposition in hero (content quality)
- Subject line (`<title>`) uses the same ALL CAPS pattern as the heading

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

All templates require a minimum 90% catch rate. Level 7 has a higher false-positive
tolerance because content judgements involve interpretation.

| Template level | Min catch rate | Max false positives |
|---------------|---------------|---------------------|
| Level 1 | 90% | 3 |
| Level 2 | 90% | 3 |
| Level 3 | 90% | 4 |
| Level 4 | 90% | 4 |
| Level 5 | 90% | 4 |
| Level 6 | 90% | 4 |
| Level 7 | 90% | 6 |
