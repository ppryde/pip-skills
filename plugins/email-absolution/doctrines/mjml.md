# MJML — Email Doctrine

## Purpose

Rules and gotchas for engineers building HTML email templates with MJML. MJML v4.18.0 is the current stable release (March 2024). MJML v5.0.0-beta.1 was released March 2025 and is under active development — do not use in production without thorough visual regression testing. MJML compiles `.mjml` XML source to cross-client HTML with inlined CSS, nested tables, and MSO conditional comments for Outlook. It does not handle dynamic data — a separate templating layer is always required.

## Rule Catalog

---

**[MJML-001]** `transactional: mortal | marketing: mortal` — Use `<mj-preview>` for the preheader text — do not manually code the hidden preheader div.
> `<mj-preview>Your order has shipped.</mj-preview>` generates the correct multi-property hidden div: `display:none; max-height:0; overflow:hidden; mso-hide:all`. Hand-coded preheaders routinely omit `mso-hide:all` or use `display:none` alone, which is insufficient (see GOTCHA-028). Source: MJML Documentation.
> `detect: regex` — (1) absence check: flag if file contains `<mjml` but not `<mj-preview`; (2) contextual — flag if a hand-coded hidden div is present in source instead of `<mj-preview>`

**[MJML-002]** `transactional: mortal | marketing: mortal` — Set global defaults in `<mj-attributes>` — do not repeat attributes on every component. Be aware that `<mj-attributes>` defaults and per-component overrides stack, not replace.
> Repeating `font-family="Arial, sans-serif" color="#333333"` on every `<mj-text>` inflates source and causes drift when values change. Use `<mj-attributes>` in `<mj-head>` to set component-level defaults. Source: MJML Documentation — mj-attributes.
> **Double-padding trap:** when both a global default and a per-component override set `padding`, MJML applies both in the compiled output — they stack rather than one replacing the other. Example: `<mj-section padding="0" />` in `<mj-attributes>` plus `padding="20px"` on a specific `<mj-section>` produces `padding: 20px` (override wins for the `padding` shorthand), but if `<mj-column padding="16px" />` is set globally and a column also sets `padding-top="32px"`, the column receives `padding-top: 32px` from the override and `padding-right/bottom/left: 16px` from the global — the per-side values compound from both layers. This is not a bug; it is the MJML attribute merge model. Verify the compiled `<td>` padding values in the HTML output when mixing global and per-component padding, particularly on `<mj-section>` and `<mj-column>`.
> `detect: contextual` — flag if the same attribute value appears on more than 3 of the same component type without a corresponding `<mj-attributes>` default; also flag if both `<mj-attributes>` and individual components set padding properties, and note the stacking behaviour

**[MJML-003]** `transactional: mortal | marketing: mortal` — All `src` and `href` values must be absolute HTTPS URLs.
> MJML does not resolve relative URLs. `<mj-image src="/logo.png">` compiles to `<img src="/logo.png">` — which fails in every email client (see GOTCHA-025). Source: caniemail.com (no `<base>` support).
> `detect: regex` — pattern: `(?:src|href)=["'](?!https?://)[^"']+["']` in MJML source files

**[MJML-004]** `transactional: mortal | marketing: mortal` — Never hand-edit the compiled HTML output in `dist/`. All source changes must be made in `.mjml` files.
> MJML compilation overwrites the output file entirely. Manual edits to compiled HTML create invisible drift between source and deployed template — the next CI build reverts them silently.
> `detect: contextual` — advisory; check if dist/ files are tracked separately from source in git

**[MJML-005]** `transactional: mortal | marketing: mortal` — Pin the MJML version exactly in `package.json`.
> Use `"mjml": "4.18.0"` not `"^4.18.0"`. MJML patch releases have changed spacing, table attributes, and conditional comment syntax. Floating semver causes undetected visual regressions on `npm install`.
> `detect: regex` — in `package.json`: pattern `"mjml"\s*:\s*"[\^~]`

**[MJML-006]** `transactional: mortal | marketing: mortal` — Do not use MJML v5 in production. It is beta as of March 2025.
> MJML v5 breaking changes: file includes (`<mj-include>`) disabled by default as a security measure; minification backend replaced (htmlnano/cssnano); `mj-body` HTML structure changed; Node.js 16/18 dropped (requires 20, 22, or 24); migration helper tool removed. Source: MJML v5.0.0-beta.1 release notes.
> `detect: regex` — in `package.json`: pattern `"mjml"\s*:\s*"[^"]*(?:5\.\d|beta|alpha|rc\d|canary)`

**[MJML-007]** `transactional: venial | marketing: venial` — Declare `<mj-breakpoint>` explicitly in every template's `<mj-head>`.
> The default breakpoint is 480px. Not declaring it makes the responsive behaviour implicit and surprising when MJML versions change. Explicit declaration makes the intent clear in code review.
> `detect: regex` — absence check: flag if file contains `<mjml` but not `<mj-breakpoint`

**[MJML-008]** `transactional: venial | marketing: venial` — Use `<mj-font>` in `<mj-head>` to load web fonts.
> `<mj-font name="Lato" href="https://fonts.googleapis.com/css?family=Lato:400,700">` generates a `<link>` in the compiled `<head>` and makes the font name available in `font-family` attributes. Do not write `<link>` tags inside `<mj-raw>`. Web fonts fail silently in Gmail and Outlook — always include a complete fallback stack in the `font-family` attribute (see HTML-005).
> `detect: contextual` — check if web fonts use `<mj-font>` vs `<mj-raw><link>` approach

**[MJML-009]** `transactional: venial | marketing: venial` — Use `<mj-section>` and `<mj-column>` for all multi-column layouts — not `<mj-raw>` with hand-coded ghost tables.
> MJML generates the correct Outlook ghost table (`<!--[if mso]><table><tr><td>...<![endif]-->`) from section/column structure automatically. Ghost tables hand-coded in `<mj-raw>` defeat MJML's cross-client guarantees and require manual maintenance of the whitespace-gap pattern (see GOTCHA-011). Source: MJML Documentation.
> `detect: contextual` — check for `<mj-raw>` blocks containing MSO table structures that duplicate section/column layout

**[MJML-010]** `transactional: venial | marketing: venial` — `<mj-raw>` is an escape hatch for content MJML cannot express — MSO-specific meta tags, tracking pixels, `<!--[if IE]>` conditionals. Do not use it for layout or dynamic content injection.
> Every `<mj-raw>` block is emitted verbatim into the compiled output without table wrapping or sanitisation. Using it for layout bypasses MJML's cross-client rendering model and produces untested HTML. Additionally, `<mj-raw>` blocks that contain template variable placeholders (`{{variable}}`, `{{ variable }}`, `{%= var %}`) are an injection risk when those variables contain user-generated content — MJML does not sanitise `<mj-raw>` content at compile time. Dynamic content inside `<mj-raw>` is effectively equivalent to triple-stache in Handlebars (see HBS-002).
> `detect: contextual` — flag `<mj-raw>` blocks containing `<table>` or layout-critical HTML; also flag `<mj-raw>` blocks containing template variable placeholders that may carry user-controlled content

**[MJML-011]** `transactional: venial | marketing: venial` — Dynamic data placeholders survive MJML compilation verbatim.
> MJML does not parse content inside its components. `{{first_name}}` (Handlebars), `{{ first_name }}` (Liquid), or `{%= first_name %}` inside `<mj-text>` compile through unchanged. This enables the hybrid pattern: write layout in MJML, leave placeholders in place, compile, then inject data at runtime. Source: MJML Documentation.
> `detect: contextual` — advisory; verify placeholders survive compilation in CI smoke test

**[MJML-012]** `transactional: venial | marketing: venial` — Declare `<mj-title>` in `<mj-head>` for accessibility.
> `<mj-title>Order #12345 Confirmed — Acme</mj-title>` generates the HTML `<title>` element. Screen readers announce this on open. A missing or generic title fails ACCESS-008. Source: WCAG 2.1 SC 2.4.2.
> `detect: regex` — absence check: flag if file contains `<mjml` but not `<mj-title`

**[MJML-013]** `transactional: venial | marketing: venial` — Use `<mj-button>` for CTA buttons, but understand that it does NOT generate VML rounded corners for Outlook.
> `<mj-button>` compiles to a `<table>` + `<td>` structure with `mso-padding-alt` and `bgcolor` applied to the `<td>`, giving Outlook a solid rectangular button. It does NOT emit `<v:roundrect>` VML — Outlook 2007–2019 renders a flat rectangle regardless of the `border-radius` attribute (which is CSS-only and ignored by the Word rendering engine). For a true bulletproof VML button with rounded corners in Outlook, the `<v:roundrect>` pattern must be hand-coded in `<mj-raw>`. `<mj-button>` is still the correct default for rectangular CTA buttons; use `<mj-raw>` only when rounded corners in Outlook are a hard design requirement. Source: MJML Documentation; Stig Morten Myre "Bulletproof Buttons" (Campaign Monitor).
> `detect: contextual` — check if CTA buttons use `<mj-button>`; if `border-radius` is set and Outlook rounded corners are claimed, flag that the compiled output will be rectangular in Outlook 2007–2019

**[MJML-014]** `transactional: venial | marketing: venial` — Set the correct display `width` on `<mj-image>` — not the file resolution width.
> `<mj-image width="600px">` compiles to `<img width="600">`. If the source image is 1200px wide (2× retina), the compiled `width` must be 600 (display size), not 1200 (file size). Setting `width="1200px"` causes the image to overflow its container in all clients (see GOTCHA-029). Source: Campaign Monitor "Retina Images in Email".
> `detect: contextual` — check that `<mj-image>` width attributes match the intended display dimensions

**[MJML-015]** `transactional: venial | marketing: venial` — Add `fluid-on-mobile="true"` to `<mj-section>` for multi-column sections that should stack to single-column on mobile.
> This generates the `@media` query that collapses multi-column sections on narrow viewports. Without it, two-column layouts stay two-column at mobile widths. Source: MJML Documentation — mj-section.
> `detect: contextual` — check if multi-column sections include `fluid-on-mobile="true"`

**[MJML-016]** `transactional: counsel | marketing: counsel` — `<mj-accordion>` and `<mj-carousel>` fall back to always-visible static content in unsupported clients (Outlook 2007–2019, Gmail, Yahoo Mail). Use them only where the open/visible fallback is acceptable.
> The fallback is not a broken component — it is the same content displayed statically. Acceptable for "show more details" patterns; not acceptable if the collapsed state is required for readability. Source: caniemail.com interactive email features.
> `detect: contextual` — advisory; verify fallback rendering is tested when interactive MJML components are used

**[MJML-017]** `transactional: counsel | marketing: counsel` — Test the compiled HTML in real email clients — not just the MJML online editor or the local MJML preview.
> The MJML online editor renders in a modern browser. The compiled HTML is processed by email clients with their own rendering engines. Issues in Outlook's Word engine and Gmail's CSS parser are invisible in the online editor.
> `detect: contextual` — advisory; verify QA process includes testing compiled HTML in target clients

**[MJML-018]** `transactional: counsel | marketing: counsel` — In MJML v5, explicitly enable file includes in `mjml.config.js` if the project uses `<mj-include>`.
> MJML v5 disables `<mj-include>` by default (security: prevents reading arbitrary files in server-side processing contexts). Build pipelines that use `<mj-include>` for shared headers/footers must enable includes explicitly. Source: MJML v5 security changelog.
> `detect: contextual` — if project uses `<mj-include>`, check that v5 config enables it

**[MJML-019]** `transactional: venial | marketing: venial` — Do not set a web font as the primary value in `<mj-all font-family>`.
> `<mj-all font-family="'BrandFont', Arial, sans-serif">` inlines the full font-family stack into every compiled element — `<table>`, `<td>`, `<a>`, and text nodes — potentially hundreds of inline repetitions per template. This inflates compiled HTML toward Gmail's 102 KB clip limit (see DELIV-005). Additionally, clients that strip `<link>` tags (Gmail) will never load the web font declared in `<mj-font>`, silently falling back without warning. Set `<mj-all font-family>` to the web-safe stack only: `font-family="Arial, 'Helvetica Neue', Helvetica, sans-serif"`. Apply the web font stack individually to `<mj-text>`, `<mj-button>`, and other specific components where it is needed.
> `detect: contextual` — flag if `<mj-all font-family>` value contains a non-system (web) font as its primary (first) entry

**[MJML-020]** `transactional: venial | marketing: venial` — `css-class` attribute styles compile to a `<style>` block in `<head>`, not to inline styles — Gmail strips them.
> MJML's `css-class="my-class"` attribute writes the corresponding CSS rules into a `<style>` block in the compiled HTML `<head>`. Gmail (and other clients that strip `<head>` `<style>` blocks) silently discard all styles applied via `css-class`. This means any visual treatment — font sizes, colours, spacing, display rules — that is applied only through `css-class` will be invisible in Gmail. Styles that must survive Gmail must be set as inline attributes directly on the MJML component (`font-size`, `color`, `padding`, etc.) or via `<mj-attributes>` defaults (which MJML inlines at compile time). Use `css-class` only for styles that are intentionally Gmail-optional (e.g. dark mode media query overrides, hover effects, print styles).
> `detect: contextual` — flag if `css-class` is used to apply styles that appear to be load-bearing (layout, typography, colour) rather than progressive-enhancement-only

**[MJML-021]** `transactional: venial | marketing: venial` — `background-size` on `<mj-section background-url>` is ignored in Outlook 2007–2019.
> `<mj-section background-url="..." background-size="cover">` compiles to two parallel rendering paths: (1) a `<!--[if mso]>` VML block using `<v:rect>` + `<v:fill type="frame">` for Outlook, and (2) a CSS `background-image` + `background-size` inline style for all other clients. The VML `<v:fill>` element does not accept a `size` attribute equivalent to CSS `background-size: cover` — the VML path always stretches to fill the container without respecting the CSS sizing instruction. In Outlook 2007–2019 the background image is displayed but `background-size: cover` or `contain` has no effect. Design backgrounds with this constraint in mind: use images cropped to the correct aspect ratio, or accept that Outlook will not clip/fit the image to cover.
> `detect: regex` — pattern: `<mj-section[^>]*background-url[^>]*background-size|<mj-section[^>]*background-size[^>]*background-url` (both attributes on same element = flag)

---

## Patterns & Code Examples

### mj-attributes global defaults

```xml
<mj-head>
  <mj-attributes>
    <!-- Global text defaults — apply to every <mj-text> unless overridden -->
    <mj-text font-family="Arial, 'Helvetica Neue', Helvetica, sans-serif"
             font-size="14px"
             line-height="1.5"
             color="#333333" />
    <!-- Global section defaults -->
    <mj-section background-color="#ffffff" padding="0" />
    <!-- Global column defaults -->
    <mj-column padding="0" />
    <!-- All components inherit font-family -->
    <mj-all font-family="Arial, 'Helvetica Neue', Helvetica, sans-serif" />
  </mj-attributes>

  <mj-breakpoint width="480px" />
  <mj-title>Your order has been confirmed — Acme</mj-title>
  <mj-preview>Order #12345 confirmed. Arriving Friday.</mj-preview>

  <mj-font name="Lato"
            href="https://fonts.googleapis.com/css?family=Lato:400,700&display=swap" />
</mj-head>
```

### Two-column section with fluid-on-mobile

```xml
<mj-section fluid-on-mobile="true" padding="20px 0">
  <mj-column width="50%" padding="0 12px 0 0">
    <mj-image src="https://cdn.example.com/product@2x.jpg"
              width="270px" alt="Blue Widget" />
  </mj-column>
  <mj-column width="50%" padding="0 0 0 12px">
    <mj-text font-size="18px" font-weight="bold">Blue Widget</mj-text>
    <mj-text>£24.99</mj-text>
    <mj-button href="https://example.com/products/blue-widget"
               background-color="#0066cc" border-radius="4px">
      View Product
    </mj-button>
  </mj-column>
</mj-section>
```

On mobile (below 480px breakpoint), the two columns stack to single-column because `fluid-on-mobile="true"` generates the required `@media` query.

### Hybrid: MJML + Handlebars placeholders

```xml
<!-- MJML source: placeholders survive compilation verbatim -->
<mj-section>
  <mj-column>
    <mj-text>Hi {{firstName}},</mj-text>
    <mj-text>Your order <strong>{{orderId}}</strong> is confirmed.</mj-text>
    {{#each orderItems}}
    <mj-text>{{this.name}} × {{this.quantity}} — £{{this.price}}</mj-text>
    {{/each}}
    <mj-button href="{{trackingUrl}}">Track Your Order</mj-button>
  </mj-column>
</mj-section>
```

After `mjml compile`, `{{firstName}}`, `{{#each}}`, and `{{trackingUrl}}` are in the compiled HTML unchanged. The Handlebars runtime then fills them at send time.

### Complete minimal template boilerplate

```xml
<mjml>
  <mj-head>
    <mj-attributes>
      <mj-all font-family="Arial, 'Helvetica Neue', Helvetica, sans-serif" />
      <mj-text font-size="14px" line-height="1.5" color="#333333" padding="0" />
      <mj-section background-color="#ffffff" padding="0" />
      <mj-column padding="0" />
    </mj-attributes>

    <mj-breakpoint width="480px" />
    <mj-title>Your order #{{orderId}} confirmed — Acme</mj-title>
    <mj-preview>Order {{orderId}} confirmed. Arriving {{deliveryDate}}.</mj-preview>

    <mj-style>
      /* Apple data detectors reset */
      a[x-apple-data-detectors] { color: inherit !important; text-decoration: none !important; }
      /* Reset for Gmail dark mode */
      u + #body .gmail-fix { display: block !important; }
    </mj-style>
  </mj-head>

  <mj-body background-color="#f4f4f4">
    <!-- Header -->
    <mj-section background-color="#0066cc" padding="20px 24px">
      <mj-column>
        <mj-image src="https://cdn.example.com/logo-white@2x.png"
                  width="120px" alt="Acme" align="left" />
      </mj-column>
    </mj-section>

    <!-- Body -->
    <mj-section background-color="#ffffff" padding="32px 24px 0">
      <mj-column>
        <mj-text font-size="22px" font-weight="bold" padding-bottom="16px">
          Order confirmed
        </mj-text>
        <mj-text padding-bottom="16px">
          Hi {{firstName}}, your order <strong>{{orderId}}</strong> is confirmed.
        </mj-text>
        <mj-button href="{{trackingUrl}}"
                   background-color="#0066cc"
                   border-radius="4px"
                   font-size="16px"
                   font-weight="bold"
                   inner-padding="12px 24px">
          Track Your Order
        </mj-button>
      </mj-column>
    </mj-section>

    <!-- Footer -->
    <mj-section background-color="#f4f4f4" padding="24px">
      <mj-column>
        <mj-text font-size="12px" color="#666666" align="center">
          Acme Ltd — 123 High Street, London EC1A 1BB<br />
          <a href="{{unsubscribeUrl}}" style="color: #666666;">Unsubscribe</a>
        </mj-text>
      </mj-column>
    </mj-section>
  </mj-body>
</mjml>
```

### MSO conditional in `<mj-raw>`

Use `<mj-raw>` for HTML that MJML cannot generate — MSO-specific meta tags, hidden tracking elements, or Outlook-version-specific overrides:

```xml
<mj-head>
  <mj-raw>
    <!--[if mso]>
    <style>
      /* Outlook-specific font fallback */
      .outlook-font { font-family: Arial, sans-serif !important; }
    </style>
    <![endif]-->
  </mj-raw>
</mj-head>
```

Do not use `<mj-raw>` for multi-column layout — use `<mj-section>` and `<mj-column>` instead.

## Support Matrix

| MJML Feature | Gmail | Outlook 2007–19 | Outlook new | Apple Mail | Yahoo Mail |
|-------------|:---:|:---:|:---:|:---:|:---:|
| Table layout (mj-section/column) | ✅ | ✅ | ✅ | ✅ | ✅ |
| VML button (mj-button) | N/A | ✅ | N/A | N/A | N/A |
| CSS button (mj-button fallback) | ✅ | N/A | ✅ | ✅ | ✅ |
| Web font (mj-font) | ❌ | ❌ | ✅ | ✅ | ❌ |
| @media responsive | ✅ | ❌ | ✅ | ✅ | Partial |
| Accordion (mj-accordion) | ❌ | ❌ | ✅ | ✅ | ❌ |
| Carousel (mj-carousel) | ❌ | ❌ | ✅ | ✅ | ❌ |

## Known Afflictions

**MJML v5 `<mj-include>` disabled by default** — Migrating from MJML v4 to v5 with shared component includes (`<mj-include path="./shared/header.mjml">`) will silently fail unless includes are explicitly enabled in `mjml.config.js`. The compiled output omits the included section without an error.
Affects: MJML v5+. Source: MJML v5 security changelog.

**MJML online editor uses latest version** — The MJML online editor (mjml.io/try-it-live) always uses the latest available MJML version. If your project is pinned to v4.18.0 and the online editor has upgraded to v5, the compiled output from the editor may differ from your local/CI build. Always build locally with the pinned version.
Affects: Teams using the MJML online editor for testing. Source: MJML editor documentation.

**Phantom whitespace in `<mj-raw>` multi-column** — If ghost table multi-column layouts are hand-coded inside `<mj-raw>` blocks, the inline-block whitespace gap pattern applies (see GOTCHA-011). MJML's section/column system handles whitespace elimination automatically — `<mj-raw>` does not.
Affects: Templates using `<mj-raw>` for multi-column layout. Source: Campaign Monitor "Responsive Email".

## Sources

1. **MJML Documentation** — https://documentation.mjml.io/ — Component reference, Node.js API, mj-attributes, mj-breakpoint.
2. **MJML GitHub** — https://github.com/mjmlio/mjml — v5 changelog, breaking changes, security discussion.
3. **caniemail.com** — https://www.caniemail.com — Interactive email component support data.
4. **Campaign Monitor CSS Support Guide** — https://www.campaignmonitor.com/css/ — Responsive email, ghost table pattern.
