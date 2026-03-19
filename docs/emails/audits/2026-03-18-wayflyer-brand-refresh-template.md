# Email Audit — Wayflyer Brand Refresh Template
**Date:** 2026-03-18
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

## Mortal Sins — Must Be Absolved Before Send (11)

> Placeholder copy findings excluded per note above. Structural and code violations only.

### [HBS-002] Triple-stache on untrusted variables — XSS risk

**Location:** `<title>{{{subject}}}</title>` and `{{{snippet}}}` in list items

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

**Fix:** Add `role="presentation"` to all layout tables. Reclassify the data tables per
the ACCESS-011 fix below.

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
    ...
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

**Fix:** Add to `<head>` `<style>` block or before the list:
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

## Venial Sins — Should Be Absolved (7)

| Rule | Finding | Fix |
|------|---------|-----|
| HTML-007 | `<br><br>` used as vertical spacer between blocks 5 and 6 | Replace with `<tr><td height="16" style="font-size:0;line-height:16px;">&nbsp;</td></tr>` |
| RENDER-014 | VML button structure non-canonical — `<a>` wraps both VML and non-Outlook div | Move `href` onto `<v:roundrect href="{{login_link}}">` and isolate `<a>` inside `<!--[if !mso]><!--> ... <!--<![endif]-->` |
| RENDER-024 | `line-height: 24px` on outer `<tbody>` lacks `mso-line-height-rule: exactly` | Add `mso-line-height-rule: exactly;` to every element with an explicit `line-height` value |
| RENDER-012 | `background-color: rgba(28, 23, 25)` on button div | Use `background-color: #1c1719` — hex is unambiguous; VML `fillcolor="#1c1719"` already covers Outlook correctly |
| RENDER-023 | `bgcolor` HTML attribute absent on background cells | Add `bgcolor="#ffffff"` as an HTML attribute alongside CSS `background-color` on primary cells |
| ACCESS-009 | "Example List" heading (`<h3>`) in `block-6` may be better as `<p><strong>` | If "Example List" is a label rather than a true section heading, use `<p><strong>` to avoid diluting heading navigation |
| ACCESS-012 | Footer text `font-size: 12px` below 14px minimum | Accepted industry exception for footer legal copy. Contrast #575355 on #fff = ~7:1 (compliant). No action required unless accessibility compliance is strict. |

---

## Counsel from the Elders (5)

| Rule | Advisory |
|------|---------|
| RENDER-021 | Add `<meta name="x-apple-disable-message-reformatting">` to `<head>` — prevents iOS Mail zooming and rescaling the layout |
| HTML-017 | Add `:root { color-scheme: light; }` to `<style>` block for broader WebKit dark mode coverage |
| RENDER-023 | Add `bgcolor="#ffffff"` on the outermost `<table class="nl-container">` as a backstop for ancient clients |
| GOTCHA-018 | When real copy is written: open with the key transactional fact as the first sentence — Apple Intelligence (iOS 18+) surfaces it in inbox notifications |
| TOOL-008 | Document the SendGrid vendor lock-in decision in `.email-absolution/config.yml` |

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
reset stack. The violations are concentrated in four areas: Handlebars safety (HBS-002
triple-stache, HBS-001 missing fallbacks), inline style completeness (border on img,
margin on p, color/text-decoration on footer links), preheader absence, and the
data table accessibility pattern.

None of the mortal sins require structural rework. All are targeted, isolated fixes.
