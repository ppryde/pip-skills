# Email Audit — Wayflyer Brand Refresh Template
**Date:** 2026-03-19
**Skill:** email-absolution:elder
**Stack:** SendGrid / Handlebars / Outlook 2019 + Gmail + Apple Mail
**Template:** Brand refresh base template (example layout — copy is illustrative)

> **Note:** Placeholder copy ("Welcome to the brand refresh template..."), hardcoded
> example data ($10,000,000, test-company-mca-1, 2021-11-21), and example headings
> (Example H1, Example H2, Example H3) are intentional scaffolding. They are not
> flagged as violations in this audit. All other findings apply to the template
> structure and code.

---

## Strengths — Found Righteous

The template demonstrates a high level of email engineering competence. The following
are confirmed correct:

| Area | What's right |
|------|-------------|
| Document structure | Correct XHTML DOCTYPE, `<html lang="en">` present, `charset=utf-8` meta tag |
| Outlook MSO setup | `<!--[if mso]>` XML with `<o:OfficeDocumentSettings>`, `PixelsPerInch`, and `AllowPNG` present |
| Table spacing | `mso-table-lspace: 0; mso-table-rspace: 0` applied to all tables via inline style |
| Image URLs | All `src` values use absolute HTTPS URLs — no relative paths, no HTTP |
| CSS safety | No CSS custom properties (`var()`), no `flexbox`, no `float` in layout |
| Layout constraints | No `min-height` in inline styles |
| Physical address | Wayflyer, Hatch Street Upper, Saint Kevin's, Dublin 2, Ireland — present in footer |
| Apple data detectors | `a[x-apple-data-detectors]` CSS reset present in `<style>` block |
| VML button | `<v:roundrect>` bulletproof button present with `fillcolor`, `strokecolor`, `w:anchorlock` |
| Logo image | `alt="Wayflyer"`, `display: block` in inline style |
| Colour scheme | `<meta name="color-scheme" content="light">` and `supported-color-schemes` present |
| MSO text colour | `<!--[if gte mso 16]-->` keep-white gradient pattern for white text preservation in Outlook |
| CTA copy | "Sign in to continue application" — verb-first, descriptive, not generic |
| Unsubscribe | `{{{unsubscribe}}}` link present, correctly gated behind `{{#if show_unsubscribe}}` |
| Responsive layout | `@media (max-width:620px)` breakpoint implemented with `.stack .column` collapse |
| Role attributes | Outer `nl-container`, `header`, `content`, `footer`, and most inner tables carry `role="presentation"` |
| Padding direction | Content column `<td>` uses directional padding (`padding-left: 24px`, etc.) — not shorthand |
| Gmail link fix | `#MessageViewBody a { color: inherit; text-decoration: none; }` present |
| Dark mode media query | `@media (prefers-color-scheme:dark)` present with button text override |
| ExternalClass reset | `.ExternalClass` rules present for Outlook.com line-height normalisation |
| `border-collapse` | `table { border-collapse: separate; }` in `<style>` block |

---

## Issues at a Glance

### Mortal Sins — Must Be Absolved Before Send (11)

| Rule | Location | Issue |
|------|----------|-------|
| HBS-002 | `<title>`, `{{#each snippets}}` | Triple-stache on `{{{subject}}}` and `{{{snippet}}}` — XSS risk |
| HBS-001 | CTA button, footer | Critical URL variables (`{{login_link}}`, `{{{unsubscribe}}}`) have no fallback protection |
| RENDER-003 | Header logo `<img>` | Missing `border="0"` HTML attribute — Outlook renders a blue border on linked images |
| HTML-013 | Header logo `<img>` | Missing `height` HTML attribute — layout reflows when image is blocked |
| RENDER-007 / ACCESS-003 | `html_block` tables, `footer_links`, `icons_block` | Inner layout tables missing `role="presentation"` |
| ACCESS-011 | `block-7` data tables | Data tables lack `<th scope>` headers — screen readers cannot associate labels with values |
| HTML-006 | All footer `<a>` elements | No inline `color` / `text-decoration` — Gmail strips `<style>` block link rules |
| HTML-001 | Greeting, closing, footer `<p>` elements | Missing `margin: 0` inline — Outlook applies its own paragraph margins |
| UX-002 / DELIV-006 | `<body>` | No preheader element — inbox preview will pull greeting and body copy |
| ACCESS-020 | `block-6` snippets `<ul>` | Missing Outlook list margin MSO conditional |
| HBS-008 | `block-7` data tables | Date values will need `formatDate` helper when hardcoded values become variables |

### Venial Sins — Should Be Absolved (7)

| Rule | Location | Issue |
|------|----------|-------|
| HTML-007 | Between blocks 5 and 6 | `<br><br>` used as vertical spacer |
| RENDER-014 | CTA button | VML button structure non-canonical — `<a>` wraps both VML and non-Outlook div |
| RENDER-024 | Outer `<tbody>` | `line-height: 24px` lacks `mso-line-height-rule: exactly` |
| RENDER-012 | Button div | `background-color: rgba(28, 23, 25)` — use hex `#1c1719` |
| RENDER-023 | Background cells | `bgcolor` HTML attribute absent — some Outlook builds ignore CSS `background-color` |
| ACCESS-009 | `block-6` "Example List" heading | `<h3>` may be better as `<p><strong>` if this is a label, not a section heading |
| ACCESS-012 | Footer wrapper | `font-size: 12px` below 14px minimum (accepted industry exception for footer legal copy) |

### Counsel from the Elders (5)

| Rule | Advisory |
|------|---------|
| RENDER-021 | Add `<meta name="x-apple-disable-message-reformatting">` — prevents iOS Mail zooming the layout |
| HTML-017 | Add `:root { color-scheme: light; }` to `<style>` block for broader WebKit dark mode coverage |
| RENDER-023 | Add `bgcolor="#ffffff"` on outermost `<table class="nl-container">` as backstop for ancient clients |
| GOTCHA-018 | When real copy is written: open with the key transactional fact — Apple Intelligence surfaces it in notifications |
| TOOL-008 | Document the SendGrid vendor lock-in decision in `.email-absolution/config.yml` |

---

## Mortal Sins — Detail

### [HBS-002] Triple-stache on untrusted variables — XSS risk

**Location:** `<title>{{{subject}}}</title>` and `{{{snippet}}}` in `{{#each snippets}}`

`{{{subject}}}` renders HTML-unescaped. `subject` is almost certainly a plain-text
value — an email subject line — and must use double-stache `{{subject}}`. Triple-stache
is only appropriate for pre-rendered, trusted HTML from your own system.

`{{{snippet}}}` in the `{{#each snippets}}` loop is a higher-risk pattern. If snippet
content is user-generated or comes from any external source, this is an active XSS
vector. An explicit code-review decision and documentation confirming all values are
sanitised before injection is required before this can be considered compliant.

**Fix:** `{{subject}}` in `<title>`. For `{{{snippet}}}`: confirm source trust chain or
switch to `{{snippet}}` and sanitise at the data layer.

---

### [HBS-001] Critical URL variables have no fallback protection

**Location:** `{{login_link}}`, `{{{unsubscribe}}}`, `{{{unsubscribe_preferences}}}`

If `login_link` is undefined or empty, the CTA button renders a broken `href=""` link.
If `unsubscribe` is empty, the unsubscribe link in the footer is a dead anchor.

**Fix:**
```handlebars
{{#if login_link}}
  <a href="{{login_link}}" ...>...</a>
{{/if}}
```
Apply the same guard to unsubscribe and preferences URLs.

---

### [RENDER-003] `<img>` missing `border="0"` HTML attribute

**Location:** Header logo image

`border="0"` must be an explicit HTML attribute on every `<img>`. Outlook 2007–2019
renders a visible blue border on images inside `<a>` links without it. The inline
`style="border: 0;"` CSS is insufficient — Outlook ignores it.

**Fix:** `<img ... border="0" style="display: block; ...">`

---

### [HTML-013] `<img>` missing `height` HTML attribute

**Location:** Header logo image

`width="600"` is present. `height` is absent. When images are blocked (default in
corporate Outlook), the layout collapses or reflows without an explicit height. Both
`width` and `height` must be present as HTML attributes.

**Fix:** `<img width="600" height="[actual px height]" ...>`

---

### [RENDER-007 / ACCESS-003] Inner layout tables missing `role="presentation"`

**Location:** `html_block` data tables (block-7), `footer_links` table, `icons_block`
alignment table

The outer structural tables are correctly marked. Several inner tables are not.
The `html_block` data tables are a special case: if they present data (revenue dates,
reference IDs), they should be `role="table"` with `<th scope>` headers — not
`role="presentation"`.

**Fix:** Add `role="presentation"` to all layout tables. Reclassify the data tables
per the ACCESS-011 fix below.

---

### [ACCESS-011] Data table lacks `<th scope>` headers

**Location:** Both data tables in `block-7` ("Example Table" and "Left-aligned Table")

The tables show row labels ("Revenue generated from:", "Revenue Amount:", etc.) and
values. They use `<th>` only for the caption row without a `scope` attribute, and bare
`<td>` for all data rows. Screen readers cannot associate labels with values.

**Fix:**
```html
<table role="table" ...>
  <thead>
    <tr><th scope="col">Field</th><th scope="col">Value</th></tr>
  </thead>
  <tbody>
    <tr>
      <th scope="row">Revenue generated from:</th>
      <td>{{revenue_from}}</td>
    </tr>
  </tbody>
</table>
```

---

### [HTML-006] Footer `<a>` elements have no inline `color` / `text-decoration`

**Location:** All footer links — Privacy policy, Security policy, Terms of use,
support mailto, unsubscribe, preferences

Link styling comes from the `<style>` block (`.footer_links a`, `.content a`). Gmail
strips `<style>` block `<a>` colour rules for non-Google-account users. Outlook.com
and older Yahoo do the same. The result: grey or blue unstyled links for a significant
portion of the audience.

**Fix:** Add inline style to every `<a>`:
```html
<a href="..." style="color: #1c1719; text-decoration: underline;">...</a>
```

---

### [HTML-001] Body `<p>` elements missing `margin: 0` inline

**Location:** Greeting paragraph, closing paragraph, footer paragraphs

The body content `<p>` tags use `style="box-sizing: border-box; line-height: inherit;"`.
Outlook 2007–2019 applies its own default paragraph margins (which vary by Word
version) and these override — or compound with — any `<style>` block reset.

**Fix:** Add `margin: 0; padding: 0;` to all `<p>` inline styles.

---

### [UX-002 / DELIV-006] No preheader element

The template has no hidden preheader div. Without it, email clients pull the first
visible body text as the inbox preview — which will be whatever the greeting resolves
to, followed by body copy.

**Fix:**
```html
<div style="display:none;visibility:hidden;opacity:0;color:transparent;
            height:0;width:0;font-size:0;max-height:0;max-width:0;
            overflow:hidden;mso-hide:all;line-height:0;"
     aria-hidden="true">
  {{preheader_text}}
  &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
</div>
```
Insert immediately after `<body>`, before the first `<table>`.

---

### [ACCESS-020] `<ul>` missing Outlook list margin MSO conditional

**Location:** `block-6` snippets loop

Outlook applies large default left margins to `<ul>` elements. The MSO conditional
fix is absent.

**Fix:** Add to `<head>` `<style>` block:
```html
<!--[if mso]><style>ul,ol{margin-left:20px!important;}</style><![endif]-->
```

---

### [HBS-008] Date variables will need `formatDate` helper

**Location:** `block-7` data tables (currently hardcoded; applies when variables are wired)

When the hardcoded dates (`2021-11-21`, `2021-11-25`) become Handlebars variables,
raw ISO strings must not be rendered directly. Register and use a `formatDate` helper.

**Fix:** `{{formatDate revenue_from "short"}}` — produces locale-appropriate output
(e.g. "21 Nov 2021" or "Nov 21, 2021" depending on recipient locale).

---

## Venial Sins — Detail

### [HTML-007] `<br><br>` spacer between sections

`<br><br>` appears between the heading blocks (block-5) and the list block (block-6).
Bare line-break elements are unreliable as spacers in Outlook.

**Fix:** Replace with a dedicated spacer row:
```html
<tr><td height="16" style="font-size:0;line-height:16px;">&nbsp;</td></tr>
```

---

### [RENDER-014] VML button structure non-canonical

The `<a>` element wraps both the VML conditional and the non-Outlook div together.
The canonical pattern places `href` directly on `<v:roundrect>` (making it
independently clickable in Outlook) and isolates the `<a>` div inside
`<!--[if !mso]><!--> ... <!--<![endif]-->`.

The current structure works in practice but is non-standard and may break in some
older Outlook builds.

---

### [RENDER-024] `line-height` without `mso-line-height-rule: exactly`

`line-height: 24px` on the outer `<tbody>` has no `mso-line-height-rule: exactly`
companion. Outlook adds extra leading to explicit line-height values without it.

**Fix:** Add `mso-line-height-rule: exactly;` alongside every explicit `line-height`
declaration.

---

### [RENDER-012] `rgba()` on button div — use hex

`background-color: rgba(28, 23, 25)` on the non-Outlook button div. Although the
VML `fillcolor="#1c1719"` covers Outlook correctly, using hex throughout is cleaner
and avoids any edge-case `rgba()` parsing differences.

**Fix:** `background-color: #1c1719`

---

### [RENDER-023] `bgcolor` attribute absent on background cells

All background colours are set via CSS `background-color` only. Some older Outlook
builds and webmail clients ignore CSS `background-color` but respect `bgcolor`.

**Fix:** Add `bgcolor="#ffffff"` as an HTML attribute alongside `style="background-color: #fff"`
on primary background cells and tables.

---

### [ACCESS-009] "Example List" `<h3>` may warrant `<p><strong>` instead

The "Example List" label in `block-6` uses an `<h3>` heading. If this is a label
for the list below rather than a true content section heading, using `<p><strong>`
is more semantically accurate and avoids diluting the heading navigation for
screen reader users who navigate by heading level.

---

### [ACCESS-012] Footer `font-size: 12px`

Footer text at 12px is below the 14px body text minimum. This is an accepted
industry exception for footer legal copy provided contrast is maintained.
Current contrast: #575355 on #fff ≈ 7:1 — compliant. No action required unless
strict WCAG 2.1 AA compliance is a hard requirement for footer content.

---

## Counsel — Detail

### [RENDER-021] Add `x-apple-disable-message-reformatting` meta

```html
<meta name="x-apple-disable-message-reformatting">
```
Prevents iOS Mail from detecting the email as "too narrow" and zooming or
reformatting the layout. Apple Mail is a declared rendering target.

---

### [HTML-017] Add `color-scheme` CSS declaration

```css
:root { color-scheme: light; }
```
Add to the `<style>` block alongside the existing `<meta name="color-scheme">`
tags for broader WebKit client coverage.

---

### [RENDER-023] `bgcolor` on outermost table

```html
<table class="nl-container" ... bgcolor="transparent">
```
A `bgcolor` backstop on the outermost wrapper ensures the background intent
survives in ancient clients that ignore all CSS.

---

### [GOTCHA-018] Open with the key transactional fact

Apple Intelligence (iOS 18+) surfaces the first body sentence in inbox
notifications in place of preheader text. When real copy is written, ensure the
first substantive sentence is the key action or fact — e.g.
"Your application for funding requires your attention." — not a greeting.

---

### [TOOL-008] Document the SendGrid vendor lock-in decision

SendGrid Dynamic Templates create meaningful vendor lock-in. Document the
trade-off and rationale in `.email-absolution/config.yml` or an architecture
decision record so future maintainers understand the constraint.

---

## Summary

| Category | Count |
|----------|-------|
| Mortal sins | 11 |
| Venial sins | 7 |
| Counsel | 5 |
| Found righteous | 21 |

The template has strong structural foundations — MSO setup, VML button, absolute
HTTPS URLs, role attributes on most tables, unsubscribe conditional, and a solid CSS
reset stack. The violations concentrate in four areas: Handlebars safety (triple-stache
and missing URL guards), inline style completeness (border on img, margin on p,
color/text-decoration on footer links), preheader absence, and the data table
accessibility pattern. None of the mortal sins require structural rework — all are
targeted, isolated fixes.
