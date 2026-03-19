# HTML & CSS Practices — Email Doctrine

## Purpose

Guards against HTML structure and CSS usage patterns that produce broken, unstyled, or mis-spaced output in email clients. Where the rendering doctrine covers *what* breaks and *why*, this doctrine covers *how to write* HTML and CSS so it does not break. Rules here are about authoring patterns — structure, selectors, inheritance, and the specific properties that behave unexpectedly in the email environment.

## Rule Catalog

---

**[HTML-001]** `mortal` — Never use `<p>` tags for spacing or layout.
> Outlook 2007–2019 applies its own default margins to `<p>` elements that vary by Word version and cannot be fully reset via CSS. This causes inconsistent spacing between versions and breaks pixel-level layouts. Use table cell padding for spacing instead. If `<p>` is used for paragraph text, always include `style="margin: 0; padding: 0;"` explicitly.
> `detect: regex` — pattern: `<p(?![^>]*style="[^"]*margin:\s*0)[^>]*>`

**[HTML-002]** `mortal` — Headings (`<h1>`–`<h6>`) must have `margin: 0` set inline.
> Outlook and most clients apply browser-default margins to headings. Without an inline `margin: 0`, headings introduce unexpected vertical gaps above and below them that compound in multi-section layouts.
> `detect: regex` — pattern: `<h[1-6](?![^>]*style="[^"]*margin)[^>]*>`

**[HTML-003]** `mortal` — `display: none` on any element must be accompanied by `mso-hide: all`.
> Outlook 2007–2019 ignores `display: none` for some element types, rendering hidden content (preheaders, mobile-only blocks, dark mode swaps) visibly. `mso-hide: all` is the MSO-specific equivalent and must accompany every `display: none` declaration. Source: standard Outlook workaround pattern.
> `detect: regex` — pattern: `display:\s*none(?![^"]{0,120}mso-hide)`

**[HTML-004]** `mortal` — Do not nest `<table>` elements more than 3–4 levels deep.
> Deep table nesting causes rendering performance issues and layout glitches in older Outlook and Yahoo clients. Heavily nested tables also become unmaintainable. Flatten layout where possible; use padding and spacer rows for spacing rather than nested tables.
> `detect: contextual` — count table nesting depth; flag structures exceeding 4 levels

**[HTML-005]** `mortal` — `font-family` declarations must include at least one web-safe fallback.
> Custom fonts (`@font-face`) are not supported in Gmail, Yahoo, or Outlook 2007–2019. If a custom font is declared without a web-safe fallback (e.g., `font-family: 'MyFont'`), these clients render the browser default (usually Times New Roman), which is almost never acceptable for production email. Source: [caniemail.com](https://www.caniemail.com/).
> `detect: regex` — pattern: `font-family\s*:\s*['"]?[A-Za-z][^;'"]*['"]?\s*[;"]` (check for single font — no comma following)

**[HTML-006]** `mortal` — `<a>` elements with custom colours must have `color` and `text-decoration` set via inline style.
> Outlook.com, older Yahoo, and Gmail may strip `<a>` colour rules from `<style>` blocks. Without inline styles on the `<a>` element itself, link colours revert to the client's default blue underlined style, which breaks branded button colours and link styling in footers and body text.
> `detect: regex` — pattern: `<a\s[^>]*href=[^>]*>` (check if each linked anchor has an inline style attribute)

**[HTML-007]** `venial` — Do not use `<br>` tags as spacing substitutes between content blocks.
> `<br>` spacing is inconsistent across clients — some add extra padding, some collapse multiple `<br>` tags. Use table rows with a fixed-height `<td>` (height attribute + font-size: 0) for reliable vertical spacing between content blocks.
> `detect: contextual` — check for `<br>` elements used outside paragraph or heading context (i.e. as spacers between table rows)

**[HTML-008]** `venial` — Use `padding-top`, `padding-right`, `padding-bottom`, `padding-left` instead of `padding` shorthand on `<td>` elements.
> Outlook 2007–2019 has inconsistent shorthand padding parsing. Explicit directional properties are more reliably applied. Also, Outlook's vertical padding row bug — all cells in a row inherit the largest vertical padding value — means vertical padding should be applied to at most one `<td>` per row. Source: [caniemail.com/features/css-padding](https://www.caniemail.com/features/css-padding/).
> `detect: regex` — pattern: `<td[^>]*style="[^"]*\bpadding\s*:\s*\d`

**[HTML-009]** `venial` — Inline all layout-critical CSS directly on elements.
> Gmail strips `<head>` `<style>` blocks in some rendering contexts. Styles critical to layout — `background-color`, `color`, `font-family`, `font-size`, `line-height`, `padding-*`, `width`, `border` — must be inlined. `<style>` block rules may be used as a progressive enhancement layer (dark mode, hover states, responsive breakpoints) but cannot be the sole source of layout-critical styles.
> `detect: contextual` — check if structural elements (outer wrapper, content cell, text) have inline styles for the properties listed above

**[HTML-010]** `venial` — Do not use `float` or `position: absolute/relative` for structural layout.
> Both are unreliable across email clients. `float` is partially supported but collapses unpredictably in Outlook and some webmail. `position: absolute/relative` is unsupported in most webmail clients. Use table-based layout for all structural positioning.
> `detect: regex` — pattern: `style="[^"]*(?:float\s*:|position\s*:\s*(?:absolute|relative|fixed))`

**[HTML-011]** `venial` — Do not use `border-radius` as the sole method for rounded buttons in cross-client emails.
> Outlook 2007–2019 does not support `border-radius`. Buttons with rounded corners will appear as square-cornered boxes in Outlook unless a VML `<v:roundrect>` fallback is present. The CSS `border-radius` may remain for modern clients but must not be the only implementation. Source: [caniemail.com](https://www.caniemail.com/).
> `detect: contextual` — check if elements with `border-radius` inside CTA sections have an accompanying VML fallback

**[HTML-012]** `venial` — `<img>` elements inside `<a>` elements must have `border="0"` and `style="text-decoration: none;"` on the wrapping `<a>`.
> Some clients render a blue underline or border around linked images. `border="0"` on the `<img>` and `text-decoration: none` on the `<a>` prevent both. The HTML attribute `border="0"` is required in addition to CSS `border: 0`.
> `detect: regex` — pattern: `<a[^>]*>\s*<img(?![^>]*\bborder=)[^>]*>`

**[HTML-013]** `venial` — All images must have explicit `width` and `height` HTML attributes.
> Without explicit dimensions, images that are blocked or slow to load cause the email layout to reflow or collapse. Explicit dimensions preserve layout structure even when images are not shown. `max-width: 100%` may be used in CSS to allow images to shrink on narrow viewports, but the HTML attribute dimensions remain required.
> `detect: regex` — pattern: `<img(?![^>]*\bwidth=)[^>]*>` or `<img(?![^>]*\bheight=)[^>]*>`

**[HTML-014]** `venial` — Do not use `margin: auto` for centering content.
> Outlook 2007–2019 does not support `margin: auto`. Centre-align content using `align="center"` on the `<td>` containing the content or `text-align: center` on the `<td>`. For the content table itself, wrap it in a 100%-wide outer table with `align="center"` on its cell.
> `detect: regex` — pattern: `style="[^"]*margin(?:-left|-right)?\s*:\s*auto`

**[HTML-015]** `venial` — Do not use `<span>` for layout or spacing purposes.
> `margin` on `<span>` is not supported in Outlook 2007–2019. `<span>` is appropriate for inline text styling (colour, font-weight) but must not be relied upon for layout spacing or structural positioning.
> `detect: contextual` — check for `<span>` elements with margin or padding used in structural contexts

**[HTML-016]** `counsel` — Use `@media` queries to stack columns on mobile, but never rely on them as the only path to mobile usability.
> Gmail Android and some webmail clients do not support `@media` queries. The hybrid layout pattern (table with `display: inline-block` columns) provides fluid mobile behaviour without media queries. Use `@media` queries as an enhancement layer on top of a hybrid base that already works without them.
> `detect: contextual` — check if any multi-column layout depends solely on @media stacking without a hybrid fallback

**[HTML-017]** `counsel` — Declare `color-scheme: light dark` on the `:root` element in the `<style>` block alongside the equivalent `<meta>` tags.
> Declaring `color-scheme` via CSS in addition to the `<meta>` tag provides broader coverage across WebKit-based clients that look for either signal. Without this, some clients apply forced colour inversion instead of using the email's own dark mode styles. Source: Litmus "Dark Mode Email Design Guide".
> `detect: regex` — pattern: `color-scheme` (check for both meta tag and CSS declaration)

**[HTML-018]** `counsel` — Dark mode overrides in `@media (prefers-color-scheme: dark)` must use `!important` on all declarations.
> Inline styles have higher specificity than `<style>` block rules. Dark mode overrides that target inline-styled elements (the default for email) must include `!important` to win the specificity battle. Without `!important`, dark mode overrides have no effect on inlined colour properties.
> `detect: regex` — pattern: `prefers-color-scheme:\s*dark` (check that rules inside use `!important`)

**[HTML-019]** `counsel` — Yahoo/AOL/Fastmail/HEY users always see the light mode design.
> Yahoo Mail and AOL transform `@media (prefers-color-scheme)` into a non-matching rule. Fastmail renders it as `@media none`. HEY renders it as `@media (false)`. These clients silently discard dark mode overrides — do not design light mode as an afterthought.
> `detect: contextual` — advisory note; no code pattern to check

**[HTML-020]** `counsel` — Use `bgcolor` HTML attribute alongside CSS `background-color` on `<td>` and `<table>` elements.
> Some Outlook builds and older clients ignore CSS `background-color` but respect the deprecated `bgcolor` attribute. Using both ensures background colours render everywhere. The `bgcolor` value must be a hex colour (no `rgba`, no named colours).
> `detect: contextual` — check primary background cells for both bgcolor attribute and CSS background-color

**[HTML-021]** `counsel` — Do not nest `<a>` elements.
> Nested anchor elements are invalid HTML and produce unpredictable rendering across email clients. Some clients select the inner `<a>` and ignore the outer; others produce completely broken output. This situation typically arises in frameworks that auto-wrap linked images inside a second link.
> `detect: regex` — pattern: `<a[^>]*>(?:[^<]|<(?!a[^>]*/?>))*<a` (nested anchor)

**[HTML-022]** `counsel` — Provide a dark-mode image variant for logos and icons using class-based swap.
> Logos designed for light backgrounds can become invisible or visually poor in forced-dark contexts. Provide a `light-only` version hidden in dark mode and a `dark-only` version hidden in light mode, swapped via `display: none !important` / `display: block !important` in the `@media (prefers-color-scheme: dark)` block.
> `detect: contextual` — check if logo `<img>` elements have a dark-mode alternative

**[HTML-023]** `venial` — Do not rely on `@font-face` in `<style>` blocks as the sole web font loading mechanism in email.
> Gmail and Yahoo strip `<head>` `<style>` blocks in some rendering contexts, silently discarding any `@font-face` declarations. Outlook 2007–2019 does not support `@font-face` at all. Apple Mail and iOS Mail do support it. This means the custom font loads in roughly 20–30% of clients and is silently lost in the rest. Accept this trade-off explicitly and always declare a complete web-safe fallback stack in every `font-family` declaration (see HTML-005). Using `@font-face` without a fallback produces the client default (usually Times New Roman) in Gmail, Yahoo, and Outlook.
> `detect: regex` — part 1 (presence flag): pattern `@font-face\s*\{` — if found, confirms custom font is in use and this rule applies; part 2 (fallback check): contextual — for each custom font name found in `@font-face`, verify every `font-family` declaration using that name also includes a named web-safe fallback (not just the generic `sans-serif`)

---

## Support Matrix

| Property | Safe | Partial | Risky |
|----------|------|---------|-------|
| `font-family` with fallback | All clients | — | — |
| `font-size`, `font-weight` | All clients | — | — |
| `color` inline | All clients | — | — |
| `background-color` inline | All clients | — | — |
| `padding-*` (explicit sides) | All clients | — | — |
| `padding` shorthand | Modern + Outlook.com | Outlook 2007–19 buggy | — |
| `margin: auto` | Modern clients | — | Outlook 2007–19 |
| `border-radius` | Modern clients | Yahoo (no slash notation) | Outlook 2007–19 |
| `display: none` | Modern clients | — | Outlook (requires mso-hide) |
| `@media` queries | Apple Mail, iOS | Gmail (no nested) | Outlook 2007–19, Yahoo (limited) |
| `@font-face` | Apple Mail, iOS | — | Gmail, Yahoo, Outlook 2007–19 |
| `prefers-color-scheme` | ~42% of clients | Gmail 2020+ | Yahoo, AOL, Fastmail, HEY |

## Patterns & Code Examples

### Safe paragraph and heading reset

```html
<!-- INCORRECT: default margins cause Outlook spacing drift -->
<h1>Order Confirmed</h1>
<p>Your order has shipped.</p>

<!-- CORRECT: explicit margin reset on every heading and paragraph -->
<h1 style="margin: 0 0 16px; font-family: Arial, sans-serif;
            font-size: 28px; font-weight: bold; color: #333333;
            line-height: 1.2; mso-line-height-rule: exactly;">
  Order Confirmed
</h1>
<p style="margin: 0; font-family: Arial, sans-serif;
           font-size: 16px; line-height: 1.5; color: #555555;
           mso-line-height-rule: exactly;">
  Your order has shipped.
</p>
```

### Spacer row (safe vertical spacing)

```html
<!-- INCORRECT: <br> spacing — inconsistent across clients -->
<tr><td>Content block 1</td></tr>
<tr><td><br><br></td></tr>
<tr><td>Content block 2</td></tr>

<!-- CORRECT: spacer row with height attribute for Outlook + font-size:0 for modern -->
<tr><td>Content block 1</td></tr>
<tr>
  <td height="24" style="font-size: 0; line-height: 24px;">&nbsp;</td>
</tr>
<tr><td>Content block 2</td></tr>
```

### Safe anchor styling

```html
<!-- INCORRECT: link colour set only in <style> block — stripped by Gmail/Outlook.com -->
<a href="https://example.com">Click here</a>

<!-- CORRECT: colour and decoration inlined directly on the <a> element -->
<a href="https://example.com" target="_blank"
   style="color: #0066cc; text-decoration: underline; font-family: Arial, sans-serif;">
  Click here
</a>
```

### Hidden element (preheader / mobile swap)

```html
<!-- CORRECT: display:none with mso-hide:all to hide from all clients including Outlook -->
<div style="display: none; max-height: 0; overflow: hidden;
            mso-hide: all; font-size: 1px; opacity: 0;">
  Preheader or hidden content here
</div>
```

### Dark mode override pattern

```html
<!-- In <head> -->
<meta name="color-scheme" content="light dark" />
<meta name="supported-color-schemes" content="light dark" />
<style type="text/css">
  :root { color-scheme: light dark; }

  @media (prefers-color-scheme: dark) {
    /* All rules must use !important to override inlined light-mode styles */
    .email-body  { background-color: #1e1e1e !important; }
    .email-card  { background-color: #2d2d2d !important; }
    .email-text  { color: #e0e0e0 !important; }
    .email-link  { color: #6ab0f5 !important; }

    /* Logo swap: hide light version, show dark version */
    .logo-light  { display: none !important; mso-hide: all !important; }
    .logo-dark   { display: block !important; }
  }
</style>

<!-- Body content uses class names for dark mode targeting -->
<table role="presentation" width="100%"
       class="email-body"
       style="background-color: #f4f4f4;">
  <tr>
    <td class="email-card"
        style="background-color: #ffffff; padding: 24px;">
      <p class="email-text"
         style="margin: 0; font-family: Arial, sans-serif; color: #333333;">
        Your order is confirmed.
      </p>
    </td>
  </tr>
</table>
```

### Two-column hybrid layout

```html
<!-- Ghost table: Outlook sees table columns; modern clients use inline-block -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <td align="center" valign="top" style="padding: 20px;">

      <!--[if mso]>
      <table role="presentation" border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td valign="top" style="width: 260px; padding-right: 20px;">
      <![endif]-->
      <div style="display: inline-block; vertical-align: top;
                  width: 100%; max-width: 260px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td style="padding: 12px; background-color: #f9f9f9;">
              <p style="margin: 0; font-family: Arial, sans-serif;
                         font-size: 14px; color: #333333;">Column one content.</p>
            </td>
          </tr>
        </table>
      </div><!--[if mso]>
          </td>
          <td valign="top" style="width: 260px; padding-left: 20px;">
      <![endif]-->
      <div style="display: inline-block; vertical-align: top;
                  width: 100%; max-width: 260px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td style="padding: 12px; background-color: #f9f9f9;">
              <p style="margin: 0; font-family: Arial, sans-serif;
                         font-size: 14px; color: #333333;">Column two content.</p>
            </td>
          </tr>
        </table>
      </div>
      <!--[if mso]>
          </td>
        </tr>
      </table>
      <![endif]-->

    </td>
  </tr>
</table>

<!-- Media query to stack columns on mobile -->
<style>
  @media screen and (max-width: 480px) {
    .col { display: block !important; max-width: 100% !important; width: 100% !important; }
  }
</style>
```

> Note: No whitespace between the closing `</div>` of column 1 and the MSO comment — whitespace between `inline-block` elements creates a visible gap in some clients.

### Web font with fallback

```html
<!-- CORRECT: custom font declared in <style> block with web-safe fallback -->
<style>
  @font-face {
    font-family: 'BrandFont';
    src: url('https://cdn.example.com/BrandFont-Regular.woff2') format('woff2'),
         url('https://cdn.example.com/BrandFont-Regular.woff') format('woff');
    font-weight: normal;
    font-style: normal;
  }
</style>
<!-- Inline with fallback on the element: custom font shows where supported -->
<h1 style="font-family: 'BrandFont', 'Helvetica Neue', Arial, sans-serif;
            font-size: 28px; color: #1a1a1a; margin: 0;">
  Order Confirmed
</h1>
<!-- Gmail, Yahoo, Outlook 2007–19 users see Helvetica Neue or Arial -->
```

## Known Afflictions

**Outlook `<p>` margin inheritance** — Outlook 2007–2019 applies paragraph margins that vary by Word version and cannot be reliably overridden in all cases. Use `<td>` padding instead of `<p>` for spacing.
Affects: Outlook 2007–2019. Source: standard Outlook pattern.
Fix: Replace `<p>` spacing with `<td>` padding or spacer rows.

**Gmail `<a>` style stripping** — Gmail can strip link colours set in `<style>` blocks for non-Google-account users. The `u + #body a` selector hack provides some protection but does not cover all Gmail rendering contexts.
Affects: Gmail (non-Google accounts). Source: Campaign Monitor CSS Guide.
Fix: Inline `color` and `text-decoration` directly on every `<a>` element.

**Yahoo/AOL silent `prefers-color-scheme` discard** — Yahoo Mail transforms `@media (prefers-color-scheme: dark)` into a non-matching rule without warning. Dark mode overrides are silently ignored.
Affects: Yahoo Mail, AOL Mail, Fastmail, HEY. Source: [caniemail.com/features/css-at-media-prefers-color-scheme](https://www.caniemail.com/features/css-at-media-prefers-color-scheme/).
Fix: Design light mode as primary. Dark mode is a progressive enhancement.

## Sources

1. **caniemail.com** — https://www.caniemail.com — CSS property support per client, prefers-color-scheme support data.
2. **Campaign Monitor CSS Guide** — https://www.campaignmonitor.com/css/ — Inline vs block CSS guidance, `<a>` style stripping data.
3. **Litmus Blog** — https://www.litmus.com/blog — Dark mode design guide, font handling, image best practices.
4. **Email on Acid** — https://www.emailonacid.com — Outlook CSS issues, shorthand padding behaviour.
