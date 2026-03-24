# Rendering — Email Doctrine

## Purpose

Guards against HTML and CSS patterns that cause broken or invisible content in major email clients. The primary adversary is Outlook 2007–2019 (Word renderer), which holds 5–10% global market share and 30–50%+ in B2B enterprise. Secondary adversaries are Gmail's inline-style stripping bug and New Outlook's forced dark mode inversion. Every rule here has a client victim and a production consequence.

## Rule Catalog

---

**[RENDER-001]** `transactional: mortal | marketing: mortal` — Never use `url()` in inline style attributes.
> Gmail desktop webmail removes the **entire** `style` attribute from any element containing a `url()` function. This strips ALL inline styles from that element — layout collapses, colours disappear, padding vanishes. Source: [caniemail.com/features/css-background-image](https://www.caniemail.com/features/css-background-image/).
> `detect: regex` — pattern: `style="[^"]*url\s*\(`

**[RENDER-002]** `transactional: mortal | marketing: mortal` — All `<img>` elements must have `display: block` in their inline style.
> Images rendered inline (the default) introduce a 3–4px gap below them in table cells across all major clients. `display: block` eliminates this gap. Required on every `<img>` without exception.
> `detect: regex` — pattern: `<img(?![^>]*display:\s*block)[^>]*>`

**[RENDER-003]** `transactional: mortal | marketing: mortal` — All `<img>` elements must have `border="0"` as an HTML attribute.
> Outlook 2007–2019 and older WebKit-based clients render a visible blue border on linked images unless `border="0"` is explicitly set as an HTML attribute (not just CSS `border: 0`). Source: standard cross-client pattern.
> `detect: regex` — pattern: `<img(?![^>]*\bborder=)[^>]*>`

**[RENDER-004]** `transactional: mortal | marketing: mortal` — Never use whitespace-syntax `rgb()` or `rgba()`.
> Gmail strips entire CSS rules that use the CSS Color Level 4 whitespace syntax (`rgb(0 128 0)` or `rgba(0 128 0 / 0.5)`). Use comma syntax only: `rgb(0, 128, 0)` and `rgba(0, 128, 0, 0.5)`. Source: [caniemail.com/features/css-rgba](https://www.caniemail.com/features/css-rgba/); hteumeuleu/email-bugs #160.
> `detect: regex` — pattern: `rgba?\(\s*\d+\s+\d+\s+\d+`

**[RENDER-005]** `transactional: mortal | marketing: mortal` — Use `<table>` for all structural layout. Never use `<div>`, `float`, or `display: flex` as primary layout primitives.
> Outlook 2007–2019 (Word renderer) does not support `<div>`-based layouts, `float`, or flexbox. Tables are the only layout primitive guaranteed to work across all clients. Source: [caniemail.com/features/css-display-flex](https://www.caniemail.com/features/css-display-flex/).
> `detect: contextual` — check if structural layout (columns, wrappers, sections) uses non-table elements

**[RENDER-006]** `transactional: mortal | marketing: mortal` — All layout `<table>` elements must have `border="0" cellpadding="0" cellspacing="0"`, and `border-collapse` must never be set to `collapse` on layout tables.
> Without these attributes, browsers and Outlook apply default table borders, cell spacing, and padding that create phantom gaps and misalignments. These must be HTML attributes, not CSS. Additionally, `border-collapse: collapse` in a `<style>` block or inline style causes Outlook 2007–2019 to render double borders and cell spacing artefacts; always use `border-collapse: separate` or omit the property entirely.
> `detect: regex` — two patterns: (1) `<table(?![^>]*\bcellpadding=)[^>]*>` — flags any `<table>` missing `cellpadding`; (2) `border-collapse\s*:\s*collapse` — flags `collapse` value anywhere in styles

**[RENDER-007]** `transactional: mortal | marketing: mortal` — All layout `<table>` elements must have `role="presentation"`.
> Screen readers announce table structure for data tables. Layout tables must declare `role="presentation"` to suppress this. This is both a rendering and accessibility requirement — its absence causes screen readers to announce "table, 3 columns, 5 rows" for visual layout scaffolding. Source: WCAG 2.1.
> `detect: regex` — pattern: `<table(?![^>]*\brole=)[^>]*>`

**[RENDER-008]** `transactional: mortal | marketing: mortal` — Do not use `min-height` in inline styles for elements that must be visible in Outlook.
> Outlook 2007–2019 ignores `min-height` entirely. Sections relying on `min-height` to push content down or create visual space will collapse to zero height. Use the `height` HTML attribute on `<td>` elements or empty spacer rows instead. Source: standard Outlook limitation.
> `detect: regex` — pattern: `style="[^"]*min-height\s*:`

**[RENDER-009]** `transactional: mortal | marketing: mortal` — All image `src` and `href` attributes must use absolute HTTPS URLs.
> Relative URLs are not resolved by email clients (there is no base URL context). HTTP URLs may be blocked by corporate security proxies and trigger security warnings in modern clients. Source: standard email rule; Gmail relative URL blocking.
> `detect: regex` — pattern: `(?:src|href)=["']/(?!/)`

**[RENDER-010]** `transactional: mortal | marketing: mortal` — Keep total HTML under 102,400 bytes (102 KB).
> Gmail clips email HTML at exactly 102 KB and replaces remaining content with a "[Message clipped] View entire message" link. Content after the clip point is invisible unless the user clicks through. Transactional content (order details, CTAs) after the clip is effectively lost. Source: [caniemail.com/features/html-style](https://www.caniemail.com/features/html-style/).
> `detect: contextual` — estimate HTML size from template; flag if approaching limit with inlined styles

**[RENDER-011]** `transactional: venial | marketing: counsel` — Do not use `z-index` in inline styles on elements targeting Outlook 2007–2019.
> Outlook 2007–2019 ignores `z-index`. Elements stacked with `z-index` for visual layering will not stack correctly in Outlook. Source: standard Outlook limitation.
> `detect: regex` — pattern: `style="[^"]*z-index\s*:`

**[RENDER-012]** `transactional: venial | marketing: counsel` — Do not use `rgba()` colours without a hex fallback for Outlook 2007–2019.
> Outlook 2007–2019 does not support `rgba()`. Semi-transparent backgrounds, overlays, and tints using `rgba()` render as fully transparent (or opaque, depending on context). Always precede `rgba()` with a hex or `rgb()` fallback in a `<style>` block rule. Source: [caniemail.com/features/css-rgba](https://www.caniemail.com/features/css-rgba/).
> `detect: regex` — pattern: `rgba\([^)]+\)` (check for hex fallback in same rule or preceding rule)

**[RENDER-013]** `transactional: mortal | marketing: venial` — Multi-column layouts must use the ghost table pattern with MSO conditional comments.
> Outlook 2007–2019 cannot render `display: inline-block` multi-column layouts. The ghost table pattern wraps columns in `<!--[if mso]><table><tr><td>...<![endif]-->` for Outlook while using `display: inline-block` for modern clients. Source: Nicole Merlin "Hybrid Coding Technique"; Litmus "Ghost Tables".
> `detect: contextual` — check if multi-column inline-block layouts have ghost table MSO wrappers

**[RENDER-014]** `transactional: mortal | marketing: venial` — CTA buttons must include a VML bulletproof button for Outlook.
> `<a>` link padding is not rendered in Outlook 2007–2019. A CSS button with `padding` on the `<a>` element appears as an unstyled link in Outlook. The VML bulletproof button technique (`<v:roundrect>` inside `<!--[if mso]>`) renders a real button. Source: Campaign Monitor "Bulletproof Email Buttons" (buttons.cm).
> `detect: contextual` — check if `<a>` styled as button has `<!--[if mso]>` VML fallback

**[RENDER-015]** `transactional: venial | marketing: counsel` — Do not use `background-image` in CSS without a VML fallback for Outlook.
> Outlook 2007–2019 does not support `background-image` on `<div>` elements. On `<td>` elements it is partial. VML `<v:rect>` with `<v:fill>` is required for background images to render in Outlook. Source: [caniemail.com/features/css-background-image](https://www.caniemail.com/features/css-background-image/).
> `detect: contextual` — check if background-image sections have VML fallback in MSO conditional

**[RENDER-016]** `transactional: mortal | marketing: venial` — Keep each `<style>` block under 16 KB.
> Gmail limits individual `<style>` blocks to 16,384 bytes. Content exceeding this limit is silently truncated. Rules at the end of a large `<style>` block may be missing without any visible error. Source: [caniemail.com/features/html-style](https://www.caniemail.com/features/html-style/).
> `detect: contextual` — estimate size of each `<style>` block

**[RENDER-017]** `transactional: venial | marketing: counsel` — Apply `mso-table-lspace: 0pt; mso-table-rspace: 0pt` to all tables.
> Outlook 2007–2019 adds 1–3px of phantom spacing on either side of table cells. This causes pixel-perfect layouts to drift and can cause two-column layouts to wrap. These MSO-specific properties eliminate the phantom spacing. Source: Litmus Email Boilerplate.
> `detect: regex` — pattern: `<table(?![^>]*mso-table)[^>]*>` (check style attribute or style block rule)

**[RENDER-018]** `transactional: venial | marketing: counsel` — Apply `max-width` via inline CSS on `<td>` or wrapper `<div>`, not on `<table>` for Outlook compatibility.
> Outlook 2007–2019 ignores `max-width` on `<table>` elements per the CSS 2.1 spec. Use the `width` HTML attribute on `<table>` to set the absolute width for Outlook, and `max-width` CSS on the containing `<td>` for fluid behaviour in modern clients. Source: [caniemail.com/features/css-max-width](https://www.caniemail.com/features/css-max-width/).
> `detect: contextual` — check if layout tables use both width attribute and max-width CSS

**[RENDER-019]** `transactional: venial | marketing: counsel` — Apply `color` and `text-decoration` to `<a>` elements via inline style, not `<style>` block rules only.
> Some clients (Outlook.com, older Yahoo) strip `<a>` colour rules from `<style>` blocks. Inline styles on `<a>` elements ensure link colours and underline removal render as intended.
> `detect: regex` — pattern: `<a\s[^>]*href=[^>]*>(?![^<]*style=)` (linked anchor without inline style)

**[RENDER-020]** `transactional: venial | marketing: counsel` — Do not use `padding` shorthand on `<td>` elements — use explicit directional properties.
> Outlook 2007–2019 has inconsistent shorthand parsing for `padding`. Explicit properties (`padding-top`, `padding-right`, `padding-bottom`, `padding-left`) are more reliably applied. Additionally, Outlook applies the largest vertical padding value to all cells in the same row — use padding on only one `<td>` per row. Source: [caniemail.com/features/css-padding](https://www.caniemail.com/features/css-padding/).
> `detect: regex` — pattern: `<td[^>]*style="[^"]*padding\s*:\s*\d`

**[RENDER-021]** `transactional: counsel | marketing: counsel` — Include `<meta name="x-apple-disable-message-reformatting">` in the `<head>`.
> Prevents iOS Mail from resizing and reformatting emails it detects as "too small". Without this meta tag, iOS Mail may zoom in and rescale the layout unexpectedly. Source: Email on Acid; Litmus boilerplate.
> `detect: regex` — pattern: `x-apple-disable-message-reformatting` (check for presence)

**[RENDER-022]** `transactional: counsel | marketing: counsel` — Include `<meta name="color-scheme" content="light dark">` and `<meta name="supported-color-schemes" content="light dark">`.
> These meta tags signal to Apple Mail, iOS Mail, and other WebKit clients that the email has dark mode styles, preventing unwanted forced inversion on clients that respect these declarations. Source: Litmus "Dark Mode for Email".
> `detect: regex` — pattern: `color-scheme` (check for presence in head)

**[RENDER-023]** `transactional: counsel | marketing: counsel` — Set `bgcolor` HTML attribute in addition to CSS `background-color` on `<td>` and `<table>` elements.
> Some older Outlook versions and webmail clients ignore CSS `background-color` but respect the deprecated `bgcolor` HTML attribute. Using both ensures background colours render everywhere.
> `detect: contextual` — check if primary background cells use both bgcolor and CSS background-color

**[RENDER-024]** `transactional: counsel | marketing: counsel` — Set `mso-line-height-rule: exactly` on all elements with an explicit `line-height` value.
> Outlook 2007–2019 interprets `line-height` differently from browsers. Without `mso-line-height-rule: exactly`, Outlook may apply extra leading above text, pushing content down and causing layout drift in fixed-height cells. Source: standard Outlook typography pattern.
> `detect: regex` — pattern: `line-height\s*:\s*\d[^;]*;(?![^"]*mso-line-height-rule)`

**[RENDER-025]** `transactional: counsel | marketing: counsel` — Animated GIFs must not convey critical transactional information.
> Outlook 2007–2019 shows only the first frame of an animated GIF. If the animation cycles through states (e.g. a progress animation), the first frame must be meaningful and the email must be fully comprehensible with only the first frame visible. Source: [caniemail.com](https://www.caniemail.com/).
> `detect: contextual` — check if animated GIFs are used and if first frame is a meaningful static state

**[RENDER-026]** `transactional: mortal | marketing: venial` — Use the XHTML 1.0 Transitional doctype (HTML 4.01 Transitional is acceptable), never omit the doctype.
> Outlook's Word renderer can fall into quirks mode without a compatible transitional doctype, which alters box model behavior and spacing. XHTML 1.0 Transitional is the most widely compatible email doctype; HTML 4.01 Transitional is an acceptable fallback when XHTML is not feasible. HTML5 doctypes and missing doctypes are not reliable in legacy Outlook builds. HTML5 may be tolerated for marketing-only emails, but is strongly discouraged and never acceptable for transactional content. Source: Litmus and Email on Acid boilerplates.
> `detect: contextual` — check that the first non-comment line is either `<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">` or `<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">`

---

---

## CSS Reset Reference

Include this in a `<style>` block in `<head>`. Keep the entire block under 16 KB (Gmail limit). Inline styles on individual elements remain the primary styling method; this block is a defensive layer.

```css
/* Prevent iOS/Android from auto-enlarging small fonts */
body, table, td, a {
  -webkit-text-size-adjust: 100%;
  -ms-text-size-adjust: 100%;
}
/* Remove phantom 1–3px table cell spacing in Outlook */
table, td {
  mso-table-lspace: 0pt;
  mso-table-rspace: 0pt;
}
/* Image normalisation */
img {
  -ms-interpolation-mode: bicubic;
  border: 0;
  height: auto;
  line-height: 100%;
  outline: none;
  text-decoration: none;
}
/* Remove body margin added by Outlook */
body {
  margin: 0 !important;
  padding: 0 !important;
  width: 100% !important;
}
/* Prevent Apple Mail from auto-linking phone numbers, addresses, dates */
a[x-apple-data-detectors] {
  color: inherit !important;
  text-decoration: none !important;
  font-size: inherit !important;
}
/* Gmail: target links inside Gmail's u+#body wrapper to override Gmail link styles */
u + #body a {
  color: inherit;
  text-decoration: none;
  font-size: inherit;
}
/* Outlook.com dark mode: prevent colour overrides */
[data-ogsc] .brand-colour { color: #0066cc !important; }
```

## Support Matrix

| Feature | Safe | Partial | Risky |
|---------|------|---------|-------|
| `<table>` layout | All clients | — | — |
| `<div>` layout | Modern only | — | Outlook 2007–19 |
| `display: flex` | Modern only | Yahoo (no inline-flex) | Outlook 2007–19 |
| `max-width` on `<table>` | — | Modern clients | Outlook 2007–19 ignores |
| `background-image` CSS | — | Most modern | Gmail (strips styles); Outlook (VML only) |
| `rgba()` | Modern (2021+) | — | Outlook 2007–19; whitespace syntax all clients |
| `border-radius` | Modern | Yahoo (no slash notation) | Outlook 2007–19 |
| `@media` queries | Modern | Gmail (no nested) | Outlook 2007–19 |
| `@font-face` | Apple Mail, iOS | — | Gmail, Yahoo, Outlook 2007–19 |
| CSS animations | ~34% of clients | Gmail/Yahoo (2021+) | Outlook 2007–19 |
| VML buttons | Outlook only | — | Non-Outlook (ignored, not broken) |

## Patterns & Code Examples

### DOCTYPE and HTML shell

```html
<!-- CORRECT: XHTML 1.0 Transitional, forces Outlook out of quirks mode -->
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <title>Email subject line here</title>
</head>
```

### Safe image declaration

```html
<!-- INCORRECT: missing display:block, border, explicit dimensions -->
<img src="/images/logo.png" alt="Logo">

<!-- CORRECT: absolute URL, display:block, border=0, explicit dimensions, alt text -->
<img src="https://cdn.example.com/logo.png"
     width="150" height="50"
     alt="Acme Corp"
     style="display: block; border: 0;" />
```

### Safe table reset

```html
<!-- CORRECT: all required table attributes present -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       width="100%"
       style="mso-table-lspace: 0pt; mso-table-rspace: 0pt; background-color: #f4f4f4;">
```

### Ghost table for two-column layout

```html
<!-- CORRECT: ghost table pattern for Outlook + inline-block for modern clients -->
<!--[if mso]>
<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr>
<td valign="top" style="width: 280px; padding-right: 20px;">
<![endif]-->
<div style="display: inline-block; vertical-align: top; width: 100%; max-width: 280px;">
  <!-- Left column -->
</div>
<!--[if mso]>
</td><td valign="top" style="width: 280px; padding-left: 20px;">
<![endif]-->
<div style="display: inline-block; vertical-align: top; width: 100%; max-width: 280px;">
  <!-- Right column -->
</div>
<!--[if mso]>
</td></tr></table>
<![endif]-->
```

### Spacer rows (Outlook-safe vertical spacing)

```html
<!-- INCORRECT: empty div for spacing — collapses in Outlook -->
<div style="height: 20px;"></div>

<!-- CORRECT: spacer row with height attribute (Outlook) + font-size:0 (modern clients) -->
<tr>
  <td height="20" style="font-size: 0; line-height: 20px;">&nbsp;</td>
</tr>
```

### Hiding elements from Outlook (e.g. preheader, mobile-only blocks)

```html
<!-- CORRECT: display:none with mso-hide:all ensures Outlook ignores the element -->
<div style="display: none; max-height: 0; overflow: hidden;
            mso-hide: all; font-size: 1px; opacity: 0;">
  Hidden content (preheader, spacer filler)
</div>
```

### Outlook-specific block (visible only to Outlook)

```html
<!-- Wrapper table visible only in Outlook — locks content to a fixed width -->
<!--[if mso]>
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600">
  <tr><td>
<![endif]-->
  <!-- Content here -->
<!--[if mso]>
  </td></tr>
</table>
<![endif]-->
```

## Known Afflictions

**Gmail url() style strip** — When any `url()` function appears in an inline `style` attribute, Gmail desktop webmail strips the entire `style` attribute from that element, destroying all inline styles.
Affects: Gmail desktop webmail. Source: [hteumeuleu/email-bugs #161](https://github.com/hteumeuleu/email-bugs/issues/161).
Fix: Remove all `url()` from inline styles. Use a `<style>` block class for background-image, or VML for Outlook.

**Gmail whitespace RGB strip** — CSS rules using whitespace-delimited RGB/RGBA syntax (`rgba(0 128 0 / 0.5)`) are entirely removed by Gmail.
Affects: Gmail desktop and mobile webmail. Source: [hteumeuleu/email-bugs #160](https://github.com/hteumeuleu/email-bugs/issues/160).
Fix: Always use comma syntax: `rgba(0, 128, 0, 0.5)`.

**Outlook vertical padding inheritance** — Outlook 2007–2019 applies the largest `padding-top` or `padding-bottom` value from any cell in a row to ALL cells in that row. A single cell with `padding-top: 40px` forces 40px top padding on every cell in the same row.
Affects: Outlook 2007–2019 (Word renderer). Source: [caniemail.com/features/css-padding](https://www.caniemail.com/features/css-padding/).
Fix: Apply vertical padding to only one `<td>` per row. Use spacer rows for spacing between content blocks.

**New Outlook forced dark mode inversion** — New Outlook for Windows (2021+) inverts light email colours to dark mode regardless of `prefers-color-scheme`. Using pure white (`#ffffff`) as the email background causes it to invert to pure black.
Affects: New Outlook for Windows. Source: Litmus "Ultimate Guide to Dark Mode for Email".
Fix: Use near-white (`#fffffe`) for background colours to avoid forced inversion in some contexts. For text elements, test in New Outlook explicitly.

**Outlook max-width on tables ignored** — Outlook 2007–2019 ignores `max-width` on `<table>` elements per the CSS 2.1 spec.
Affects: Outlook 2007–2019. Source: [caniemail.com/features/css-max-width](https://www.caniemail.com/features/css-max-width/).
Fix: Set fixed width via HTML `width` attribute on the `<table>` element. Use `max-width` CSS only on `<td>` or `<div>` wrappers for fluid behaviour in modern clients.

## Sources

1. **caniemail.com** — https://www.caniemail.com — Primary source for all client support data. Scoreboard, feature pages, and client-specific test results.
2. **hteumeuleu/email-bugs** — https://github.com/hteumeuleu/email-bugs — Live bug tracker for email client rendering issues. Referenced for Gmail url() strip (#161), whitespace RGB (#160).
3. **Litmus Blog** — https://www.litmus.com/blog — Dark mode guide, Gmail clipping, bulletproof buttons, market share data.
4. **Campaign Monitor CSS Guide** — https://www.campaignmonitor.com/css/ — MSO conditional comments, VML documentation.
5. **buttons.cm** — https://buttons.cm — Campaign Monitor's bulletproof button generator; VML button pattern reference.
