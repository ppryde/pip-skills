# HTML/CSS Best Practices for Reliable Email Templates

> Research compiled for engineers building transactional email templates.
> Focus: maximum compatibility across email clients, with notes on modern alternatives.
> Last updated: March 2026. Live source verification performed against caniemail.com and campaignmonitor.com/css/.

---

## Core Principles

### The Fundamental Problem

Email clients are not browsers. Each email client has its own rendering engine — some based on Word (Outlook 2007–2019 on Windows uses Microsoft Word's rendering engine via Internet Explorer), some based on WebKit (Apple Mail, iOS Mail), and some based on Gecko or Blink (Thunderbird, some webmail). This fragmentation means CSS and HTML that renders perfectly in a browser may break catastrophically in an email client.

**Key rendering engines by client (as of 2025–2026):**

| Client | Rendering Engine |
|---|---|
| Outlook 2007–2019 (Windows) | Microsoft Word / IE |
| New Outlook (Windows, 2024+) | Edge/WebKit (see note below) |
| Outlook for Mac | WebKit |
| Apple Mail (macOS/iOS) | WebKit |
| Gmail (web) | Custom (strips `<head>`, inlines styles) |
| Gmail App (Android/iOS) | Custom (limited CSS support) |
| Yahoo Mail | Custom (moderate CSS support) |
| Samsung Email | Chromium-based WebKit |
| Thunderbird | Gecko |

**New Outlook for Windows note:** Microsoft has been rolling out the new Outlook for Windows (replacing Outlook 2019 and earlier) which uses the Edge/WebKit rendering engine rather than the Word renderer. As of 2025 it is widely deployed but not universal — enterprise environments may still run legacy Outlook. Continue using MSO conditional comments as a safety net until legacy Outlook share is negligible in your audience.

Sources: Litmus Email Client Market Share reports; Campaign Monitor "Guide to CSS Support in Email" (campaignmonitor.com/css).

---

### The Three Laws of Email HTML

**1. Tables for structure, not semantics.**
The `<table>` element is the most reliably supported layout primitive across email clients. Flexbox and CSS Grid have significantly improved support in modern clients (~83% and ~56% respectively per caniemail.com), but are still broken in Outlook 2007–2019 (Windows). Until legacy Outlook share in your audience is demonstrably negligible, tables remain required for any layout that must reach those clients.
Source: Litmus "Ultimate Guide to Email Design" (litmus.com); caniemail.com/features/css-display-flex/; caniemail.com/features/css-display-grid/

**2. Inline styles for guaranteed rendering.**
Many email clients — especially Gmail — strip `<head>` blocks or ignore `<style>` tags. Inlining critical styles directly on elements is the only way to guarantee they survive all pre-processing pipelines.
Source: Campaign Monitor "Inline CSS in Emails" guide; Email on Acid "CSS Support Guide" (emailonacid.com).

**3. Code defensively for Outlook's Word renderer.**
Outlook 2007–2019 (Windows) has the most severe CSS limitations. It does not support: `border-radius`, `background-image` on non-table elements (unreliably), CSS `max-width`, `min-height`, many shorthand properties, and more. Use MSO conditional comments (`<!--[if mso]>`) for Outlook-specific overrides. The new Outlook for Windows (Edge-based) is substantially more capable, but conditional comments are still required to support users on legacy builds.
Source: Campaign Monitor "Outlook Conditional Comments" documentation.

---

### Mobile-First vs Desktop-First

Transactional emails are commonly read on mobile (over 60% of opens as of 2023–2024, per Litmus Email Analytics). However, the safest default is to design at a fixed width (600px is the industry standard desktop width) and use `@media` queries to collapse to single-column on mobile — keeping in mind that Gmail on Android and some older clients do not support media queries.

The "hybrid" or "spongy" technique (using `max-width` with `width: 100%` on tables and `display: inline-block` on cells) provides a mobile-friendly layout without relying on media queries. This is the recommended approach for maximum compatibility.
Source: Campaign Monitor "Responsive Email Design" (campaignmonitor.com); Nicole Merlin "Hybrid Coding Technique" (webdesignerwall.com).

---

## Recommended Patterns

### Document Structure

Always use XHTML 1.0 Strict doctype and explicit `xmlns` on the `<html>` element. This prevents Outlook's quirks-mode rendering.

```html
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <!--[if !mso]><!-->
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <!--<![endif]-->
  <title>Email Title</title>
  <style type="text/css">
    /* Reset and base styles here */
    body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
    img { -ms-interpolation-mode: bicubic; border: 0; height: auto;
          line-height: 100%; outline: none; text-decoration: none; }
    body { margin: 0 !important; padding: 0 !important; width: 100% !important; }
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f4f4;">
```

**Key meta tags explained:**
- `x-apple-disable-message-reformatting`: Prevents iOS Mail from auto-resizing fonts and adjusting layout on small screens in ways that can break email designs.
- `color-scheme` / `supported-color-schemes`: Declares that the email is dark-mode aware. Prevents some clients (Apple Mail, iOS Mail) from forcibly inverting colours when the OS is in dark mode. Add both the `<meta>` tag and a matching `color-scheme` property on the `<html>` element for maximum coverage.
- `mso-table-lspace` / `mso-table-rspace`: Removes phantom spacing Outlook adds between table cells.
- `-webkit-text-size-adjust: 100%`: Prevents iOS from inflating font sizes when the email is viewed in landscape mode.

Source: Email on Acid "Email HTML Boilerplate" (emailonacid.com); Litmus "Email Coding 101"; Litmus "Dark Mode Email Design".

---

### Tables vs Divs

**Use `<table>` for:**
- The outer wrapper / container
- Multi-column layouts (two-column, three-column grids)
- Side-by-side content (image + text)
- Any layout that must render correctly in Outlook 2007–2019

**Use `<div>` for:**
- Pure cosmetic wrappers where layout doesn't matter (e.g., wrapping text inside a `<td>`)
- Modern-only emails (internal tools, known-WebKit audiences)
- Within MJML-generated code where the framework manages fallbacks

**Never use:**
- `<div>` for multi-column layout in cross-client emails (broken in Outlook 2007–2019)
- Nested tables deeper than 3–4 levels (performance and rendering bugs in some clients)
- `<p>` tags for spacing control — Outlook adds its own margins; use `<br>` or table cell padding instead

Source: Campaign Monitor "HTML Email Coding Best Practices"; Litmus "Tables in Email Design".

---

### The Outer Wrapper Pattern

Every email should have an outer 100%-width table (to fill the viewport) containing a centered inner table (max 600px wide). This is the foundational pattern.

```html
<!-- Outer wrapper: full viewport width -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       width="100%" style="background-color: #f4f4f4;">
  <tr>
    <td align="center" valign="top">

      <!-- Inner container: 600px max width -->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0"
             width="600" style="max-width: 600px; width: 100%;">
        <tr>
          <td align="left" valign="top"
              style="padding: 20px; background-color: #ffffff;">
            <!-- Content goes here -->
          </td>
        </tr>
      </table>

    </td>
  </tr>
</table>
```

**Critical attributes on every `<table>`:**
- `role="presentation"`: Tells screen readers this is a layout table, not data. Accessibility requirement.
- `border="0"`: Removes default table borders.
- `cellpadding="0"`: Removes default cell padding (use explicit `padding` styles instead).
- `cellspacing="0"`: Removes default cell spacing (critical — Outlook ignores CSS `border-spacing`).
- `width="600"` (integer, not `"600px"`): HTML attribute width is more reliable in Outlook than CSS `width`.

Source: Litmus "Coding HTML Email" documentation; Campaign Monitor "HTML Best Practices".

---

### CSS Inlining Strategy

**Always inline:**
- `background-color`
- `color`
- `font-family`, `font-size`, `font-weight`, `line-height`
- `padding` (on `<td>` elements — not shorthand in Outlook; use `padding-top`, `padding-right`, etc.)
- `text-align`, `vertical-align`
- `width`, `height` on `<td>` and `<img>`
- `border` (when used for decorative purposes)
- `margin: 0` resets on headings and paragraphs

**Safe to put in `<style>` block (not inline):**
- `@media` queries for responsive breakpoints
- `:hover` pseudo-class styles (for supported clients — Apple Mail, Outlook for Mac)
- Font-face declarations (`@font-face`)
- Reset rules (body margin/padding, image resets)
- Dark mode overrides (`@media (prefers-color-scheme: dark)`) — see Dark Mode section

**Never put in `<style>` block and expect universal support:**
- Layout-critical properties: `display`, `float`, `position`
- Any property used for multi-column or structural layout

**Shorthand padding warning for Outlook:**
```html
<!-- BAD: Outlook may ignore padding shorthand -->
<td style="padding: 20px 40px">

<!-- GOOD: Explicit sides always work -->
<td style="padding-top: 20px; padding-right: 40px; padding-bottom: 20px; padding-left: 40px;">
```

Source: Campaign Monitor "CSS Support in Email"; caniemail.com/features/css-padding/; Email on Acid "Outlook CSS Issues".

---

### Safe CSS Properties Reference

**Universally supported (inline on elements):**
```
background-color, color
font-family, font-size, font-style, font-weight
line-height, letter-spacing
text-align, text-decoration, text-transform
padding-top, padding-right, padding-bottom, padding-left
margin (on body; unreliable on most other elements)
width, height (HTML attributes preferred over CSS)
border (solid borders; shorthand works on td/table)
vertical-align
```

**Partially supported (use with fallbacks):**
```
border-radius          — not supported in Outlook 2007–2019; use VML for rounded buttons
background-image       — 90.69% support (caniemail 2023); Gmail has critical bug: strips the
                         entire style attribute when url() with a valid image is present;
                         Outlook Windows requires VML fallback
max-width              — not supported in Outlook 2007–2019 (use width attribute)
min-height             — not supported in Outlook 2007–2019
display: block         — works in most modern clients, not Outlook table cells
```

**Use with care — current support data (caniemail.com, verified 2023–2024):**
```
display: flex          — ~83% overall support; fully supported in Apple Mail, Gmail,
                         Outlook.com, Outlook for Mac/iOS/Android, Samsung Email,
                         Thunderbird, ProtonMail; NOT supported in Outlook Windows 2007–2019;
                         partial (no inline-flex) in Yahoo Mail, AOL
display: grid          — ~56% overall support; NOT supported in Outlook Windows 2007–2019;
                         supported in Apple Mail, Gmail, Outlook.com, Yahoo Mail, AOL,
                         Samsung Email, Thunderbird, ProtonMail
```

**Correction from earlier versions of this document:** Flex support was previously cited as "~50%" and grid as "~40%". Live caniemail.com data (tested 2019–2023) shows flex at ~83% and grid at ~56%. The document caveat remains: both are still broken in Outlook Windows 2007–2019, which is the blocking factor for cross-client emails targeting enterprise audiences.

**Avoid entirely for layout in cross-client emails:**
```
position: absolute/relative — unreliable across clients
float                       — unreliable, avoid
```

Source: caniemail.com (comprehensive client-by-client CSS support table); caniemail.com/features/css-display-flex/ (flex: ~83% support, verified 2021); caniemail.com/features/css-display-grid/ (grid: ~56% support, verified 2019); caniemail.com/features/css-background-image/ (background-image: ~91% support, verified 2023).

---

### Outlook Conditional Comments

Use MSO (Microsoft Office) conditional comments to target Outlook-specific fixes. These still apply to New Outlook for Windows when emails reach users on legacy builds.

```html
<!-- Target all Outlook versions -->
<!--[if mso]>
<table role="presentation" cellpadding="0" cellspacing="0" border="0">
  <tr><td width="600">
<![endif]-->
  <!-- Content here (seen by all clients) -->
<!--[if mso]>
  </td></tr>
</table>
<![endif]-->
```

```html
<!-- Ghost table trick: forces Outlook to respect width on a div-based layout -->
<!--[if mso]>
<table role="presentation" border="0" cellpadding="0" cellspacing="0">
<tr><td style="width:300px;">
<![endif]-->
<div style="display:inline-block; width:100%; max-width:300px;">
  <!-- Column content -->
</div>
<!--[if mso]>
</td><td style="width:300px;">
<![endif]-->
<div style="display:inline-block; width:100%; max-width:300px;">
  <!-- Column content -->
</div>
<!--[if mso]>
</td></tr></table>
<![endif]-->
```

The "ghost table" pattern is the standard approach for two-column hybrid layouts where you want `inline-block` to work in modern clients while Outlook sees a proper table.
Source: Campaign Monitor "Outlook Conditional Comments"; Litmus "Ghost Tables in Email".

---

### Font Handling

Web-safe fonts are the most reliable. For custom fonts, declare a `@font-face` in the `<style>` block with a full fallback stack.

**Web-safe font stack for email:**
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
             'Helvetica Neue', Arial, sans-serif;
```

**Custom font with fallback (supported in Apple Mail, iOS Mail, some Android):**
```html
<style>
  @font-face {
    font-family: 'CustomFont';
    src: url('https://example.com/font.woff2') format('woff2');
    font-weight: normal;
    font-style: normal;
  }
</style>
<!-- Inline with fallback: -->
<td style="font-family: 'CustomFont', Arial, sans-serif;">
```

Gmail, Outlook, and Yahoo Mail do not support `@font-face`. The fallback font renders in those clients. Always ensure the fallback is visually acceptable — do not rely on custom font sizing/spacing being preserved in the fallback.

Source: Campaign Monitor "Using Web Fonts in Email"; Litmus "Web Fonts in Email" (litmus.com/blog/the-ultimate-guide-to-web-fonts).

---

### Image Best Practices

```html
<!-- Always specify width/height, alt text, display:block, border:0 -->
<img src="https://example.com/image.png"
     width="600" height="300"
     alt="Descriptive alt text"
     style="display: block; border: 0; outline: none; text-decoration: none;
            -ms-interpolation-mode: bicubic; max-width: 100%;"
/>
```

**Critical rules:**
- Always use absolute URLs for `src` — email clients cannot resolve relative paths.
- Always specify `width` and `height` HTML attributes. Without them, images shift layout when blocked.
- Always include meaningful `alt` text. ~43% of email users have images blocked by default (Litmus research).
- `display: block` prevents a 1–4px gap below images in some clients (default inline-block behaviour).
- `max-width: 100%` allows images to shrink on mobile (CSS only — use `width` attribute for Outlook fixed-width).

**Retina / HiDPI images:**
Serve images at 2× the display size, set the `width` attribute to the display size:
```html
<!-- Image is 1200px wide, displayed at 600px -->
<img src="hero@2x.png" width="600" height="300" alt="Hero" style="..." />
```

Source: Litmus "Email Image Best Practices"; Campaign Monitor "Images in Email HTML".

---

### Dark Mode Support

Dark mode is no longer optional for production emails. Apple Mail, iOS Mail, Gmail (web and app), Outlook (Windows/Mac/iOS/Android/web), Samsung Email, Thunderbird, and ProtonMail all have dark mode — either respecting `prefers-color-scheme` or applying forced colour inversion.

**`@media (prefers-color-scheme: dark)` support (caniemail.com, verified 2024):**
- **~42% overall support** for the media query itself.
- **Full support**: Apple Mail (macOS/iOS), Gmail (web and app), Outlook (Windows/Mac/iOS/Android/web), Samsung Email, Thunderbird, ProtonMail.
- **Broken — query is filtered/transformed**: Yahoo Mail and AOL both transform `@media (prefers-color-scheme)` into a non-matching rule, silently discarding your dark mode overrides. Fastmail transforms it to `@media none`. HEY transforms it to `@media (false)`.
- Yahoo/AOL/Fastmail/HEY users will always see your light-mode design regardless of their OS preference.

**Three dark mode behaviours to defend against:**

1. **Respects `prefers-color-scheme`** (Apple Mail, Gmail, Outlook.com): Your CSS media query fires. You control the dark appearance.
2. **Forced inversion** (Gmail mobile, some Android): The client inverts or adjusts colours automatically, ignoring your media query. Use `color-scheme` meta tag to signal intent and reduce unwanted inversion.
3. **No dark mode processing** (Yahoo, AOL): Light mode design always displayed. Ensure light mode is acceptable.

**Dark mode CSS pattern:**

```html
<head>
  <!-- Signal dark mode awareness to reduce forced inversion -->
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <style type="text/css">
    :root {
      color-scheme: light dark;
      supported-color-schemes: light dark;
    }

    @media (prefers-color-scheme: dark) {
      /* Override background colours */
      .email-bg { background-color: #1a1a1a !important; }
      .email-body { background-color: #2d2d2d !important; }

      /* Override text colours */
      .email-text { color: #e0e0e0 !important; }
      .email-heading { color: #ffffff !important; }

      /* Override link colours */
      .email-link { color: #6ab0f5 !important; }

      /* Hide light-mode-only elements */
      .light-only { display: none !important; mso-hide: all !important; }
      /* Show dark-mode-only elements */
      .dark-only { display: block !important; }
    }
  </style>
</head>
```

**Important implementation notes:**
- Use `!important` on all dark mode overrides — they must beat inlined light mode styles.
- Add class names (e.g., `class="email-bg"`) to your structural `<td>` and `<table>` elements so the media query can target them.
- For images (logos), provide both a light-mode and dark-mode version and swap them with `display: none !important` / `display: block !important` within the media query.
- Outlook for Mac/Windows with dark mode enabled adds a `[data-ogsb]` attribute to the `<body>` — this can be used as a CSS selector for Outlook-specific dark mode overrides: `[data-ogsb] .email-bg { background-color: #1a1a1a !important; }`
- Always test in both modes. Tools: Litmus dark mode previews, Apple Mail on macOS (toggle in System Preferences).

Source: Litmus "Dark Mode Email Design Guide"; caniemail.com/features/css-at-media-prefers-color-scheme/ (~42% support, verified 2024); Campaign Monitor "Dark Mode Email Design".

---

### Ghost Table / Hybrid Fluid Layout Pattern

The hybrid (also called "spongy") layout technique achieves fluid, responsive columns without relying on `@media` queries. It is the recommended approach for maximum client compatibility.

**How it works:**
- Modern clients render `display: inline-block` divs that naturally reflow when the viewport is too narrow.
- Outlook Windows (which ignores `inline-block`) sees only the MSO ghost table markup, which forces fixed-width columns.
- The combination means: two columns on desktop (Outlook included), single column on narrow mobile (without needing media queries).

See the full implementation in the Two-Column Grid example below. The critical elements are:
1. The outer `<td>` has `align="center"` — this causes `inline-block` children to centre-align.
2. Each column `<div>` has `display: inline-block; vertical-align: top; width: 100%; max-width: Npx;`.
3. MSO conditional comments bracket each column with `<td width="Npx">` ghost table cells.
4. No whitespace between the closing `</div>` and the MSO comment — whitespace between `inline-block` elements causes a gap.

Source: Nicole Merlin "Hybrid Coding in Email" (webdesignerwall.com); Campaign Monitor "Responsive Email Design Patterns".

---

## Component Examples

### Button (CTA)

The bulletproof button technique uses a table-based approach so it works in all Outlook versions. `<a>` padding alone does not work in Outlook.

```html
<!-- Bulletproof button: works in all clients including Outlook -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       style="margin: 0 auto;">
  <tr>
    <td align="center" bgcolor="#0066cc"
        style="border-radius: 4px; background-color: #0066cc;">
      <!--[if mso]>
      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                   xmlns:w="urn:schemas-microsoft-com:office:word"
                   href="https://example.com"
                   style="height:44px; v-text-anchor:middle; width:200px;"
                   arcsize="10%"
                   stroke="f"
                   fillcolor="#0066cc">
        <w:anchorlock/>
        <center style="color:#ffffff; font-family:Arial,sans-serif;
                        font-size:16px; font-weight:bold;">
          Get Started
        </center>
      </v:roundrect>
      <![endif]-->
      <!--[if !mso]><!-->
      <a href="https://example.com"
         target="_blank"
         style="display: inline-block; color: #ffffff; font-family: Arial, sans-serif;
                font-size: 16px; font-weight: bold; line-height: 44px;
                text-decoration: none; text-align: center;
                padding: 0 24px; border-radius: 4px;
                background-color: #0066cc; mso-hide: all;">
        Get Started
      </a>
      <!--<![endif]-->
    </td>
  </tr>
</table>
```

The VML (`v:roundrect`) block renders in Outlook with a rounded rectangle background. The `<!--[if !mso]><!-->` block renders in all other clients. The `border-radius` on the `<td>` shows in most modern clients; the VML arcsize handles Outlook.

Source: Campaign Monitor "Bulletproof Email Buttons" (buttons.cm — the industry standard generator); Litmus "Designing Bulletproof Email Buttons".

---

### Header / Preheader

The preheader is hidden text that appears in inbox previews (after the subject line). It must be visually hidden but accessible to email clients.

```html
<!-- Preheader: hidden preview text -->
<div style="display: none; max-height: 0px; overflow: hidden; visibility: hidden;
            mso-hide: all; font-size: 1px; color: #ffffff; line-height: 1px;
            max-width: 0px; opacity: 0;">
  Your order has shipped — track it now.
  <!-- Filler: prevents content from leaking into preview -->
  &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
</div>

<!-- Header with logo -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <td align="center" valign="middle"
        style="padding: 24px 40px; background-color: #ffffff;">
      <a href="https://example.com" target="_blank" style="text-decoration: none;">
        <img src="https://example.com/logo.png"
             width="150" height="50"
             alt="Company Name"
             style="display: block; border: 0; outline: none;" />
      </a>
    </td>
  </tr>
</table>
```

**Preheader technique notes:**
- `mso-hide: all` hides in Outlook.
- Zero-width non-joiners (`&zwnj;`) prevent some clients from pulling in body text to fill the preview.
- Background colour matching the email background prevents flash of hidden text if CSS is stripped.

Source: Litmus "Email Preheader Best Practices" (litmus.com/blog/the-ultimate-guide-to-preview-text-support); Campaign Monitor "Preview Text".

---

### Two-Column Grid

The hybrid / ghost-table approach: modern clients use `inline-block`, Outlook uses the ghost table.

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <td align="center" valign="top" style="padding: 20px;">

      <!-- Ghost table for Outlook -->
      <!--[if mso]>
      <table role="presentation" border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td valign="top" style="width: 260px; padding-right: 20px;">
      <![endif]-->

      <!-- Column 1 -->
      <div class="two-col" style="display: inline-block; vertical-align: top;
                  width: 100%; max-width: 260px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%">
          <tr>
            <td align="left" valign="top"
                style="padding: 12px; background-color: #f9f9f9;">
              <h3 style="margin: 0 0 8px; font-family: Arial, sans-serif;
                          font-size: 18px; color: #333333;">Column One</h3>
              <p style="margin: 0; font-family: Arial, sans-serif;
                         font-size: 14px; line-height: 1.5; color: #666666;">
                Content for the first column goes here.
              </p>
            </td>
          </tr>
        </table>
      </div><!--[if mso]>
          </td>
          <td valign="top" style="width: 260px; padding-left: 20px;">
      <![endif]-->

      <!-- Column 2 -->
      <div class="two-col" style="display: inline-block; vertical-align: top;
                  width: 100%; max-width: 260px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%">
          <tr>
            <td align="left" valign="top"
                style="padding: 12px; background-color: #f9f9f9;">
              <h3 style="margin: 0 0 8px; font-family: Arial, sans-serif;
                          font-size: 18px; color: #333333;">Column Two</h3>
              <p style="margin: 0; font-family: Arial, sans-serif;
                         font-size: 14px; line-height: 1.5; color: #666666;">
                Content for the second column goes here.
              </p>
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
```

**Note on whitespace:** The closing `</div>` of column 1 is immediately followed by the MSO comment on the same line (no newline between them). This eliminates the whitespace gap that `inline-block` elements would otherwise render between columns in some clients.

On mobile (< 480px), add a media query to make each `div` `display: block; max-width: 100%` to stack columns.

```css
@media screen and (max-width: 480px) {
  .two-col { display: block !important; max-width: 100% !important; width: 100% !important; }
}
```

Media query styles will override inline styles in clients that support them (Apple Mail, iOS Mail, most Android clients).

Source: Nicole Merlin "Hybrid Coding in Email" (webdesignerwall.com); Campaign Monitor "Responsive Email Design Patterns".

---

### Hero Image with Text Overlay

Achieving text over a background image in email is notoriously difficult due to Outlook's lack of `background-image` support on non-table elements. The standard approach uses VML for Outlook and CSS for other clients.

**Background-image support summary (caniemail.com, verified July 2023):**
- Overall: ~91% support (72% full, 19% partial).
- Gmail critical bug: Gmail strips the **entire style attribute** from the element when the `background-image` value contains a `url()` with a valid image URL. This means other inline styles on that element are also lost. Workaround: apply background-image only via a `<style>` block class, not inline — or accept that Gmail users see only the fallback background-colour.
- Outlook Windows (2007–2019): No support. Must use VML.
- Thunderbird: No support.

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <!--[if mso]>
    <td valign="top" align="center">
    <v:rect xmlns:v="urn:schemas-microsoft-com:vml"
            fill="true" stroke="false"
            style="width:600px; height:300px;">
      <v:fill type="tile" src="https://example.com/hero.jpg" color="#0066cc"/>
      <v:textbox inset="0,0,0,0">
    <![endif]-->
    <!--[if !mso]><!-->
    <td valign="middle" align="center"
        style="background-color: #0066cc; padding: 60px 40px;">
    <!--<![endif]-->
    <!-- NOTE: background-image intentionally applied via <style> block class,
         not inline, to avoid Gmail stripping the entire style attribute.
         Add class="hero-td" and declare background-image in <style>. -->

      <table role="presentation" border="0" cellpadding="0" cellspacing="0"
             width="100%">
        <tr>
          <td align="center" valign="middle">
            <h1 style="margin: 0 0 16px; font-family: Arial, sans-serif;
                        font-size: 36px; font-weight: bold;
                        color: #ffffff; line-height: 1.2;">
              Welcome to Acme
            </h1>
            <p style="margin: 0; font-family: Arial, sans-serif;
                       font-size: 18px; color: #ffffff; line-height: 1.5;">
              The best product you will ever use.
            </p>
          </td>
        </tr>
      </table>

    <!--[if mso]>
      </v:textbox>
    </v:rect>
    </td>
    <![endif]-->
  </tr>
</table>
```

In the `<style>` block:
```css
.hero-td {
  background-image: url('https://example.com/hero.jpg');
  background-size: cover;
  background-position: center center;
}
```

`background-color` on the `<td>` serves as a fallback when the image is blocked or in clients without support. Always ensure text is readable against the fallback colour.

Source: Litmus "Background Images in HTML Email" (litmus.com/blog/background-images-html-email-vml-fallbacks); Campaign Monitor "VML Background Images"; caniemail.com/features/css-background-image/ (verified July 2023).

---

### Footer

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <td align="center" valign="top"
        style="padding: 24px 40px; background-color: #333333;">

      <!-- Social links -->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding: 0 8px;">
            <a href="https://twitter.com/acme" target="_blank"
               style="text-decoration: none;">
              <img src="https://example.com/icons/twitter.png"
                   width="24" height="24" alt="Twitter"
                   style="display: block; border: 0;" />
            </a>
          </td>
          <td style="padding: 0 8px;">
            <a href="https://linkedin.com/company/acme" target="_blank"
               style="text-decoration: none;">
              <img src="https://example.com/icons/linkedin.png"
                   width="24" height="24" alt="LinkedIn"
                   style="display: block; border: 0;" />
            </a>
          </td>
        </tr>
      </table>

      <!-- Address and legal -->
      <p style="margin: 16px 0 8px; font-family: Arial, sans-serif;
                 font-size: 12px; line-height: 1.5; color: #aaaaaa;
                 text-align: center;">
        Acme Inc., 123 Main St, San Francisco, CA 94105
      </p>

      <!-- Unsubscribe — required by CAN-SPAM / GDPR -->
      <p style="margin: 0; font-family: Arial, sans-serif;
                 font-size: 12px; color: #aaaaaa; text-align: center;">
        You received this because you signed up for updates.
        <a href="{{unsubscribe_url}}" target="_blank"
           style="color: #aaaaaa; text-decoration: underline;">
          Unsubscribe
        </a>
        &nbsp;|&nbsp;
        <a href="{{preferences_url}}" target="_blank"
           style="color: #aaaaaa; text-decoration: underline;">
          Manage Preferences
        </a>
      </p>

    </td>
  </tr>
</table>
```

**Legal requirements:**
- CAN-SPAM (US): Requires physical mailing address and a working unsubscribe mechanism that is honoured within 10 business days.
- CASL (Canada): Requires identification of sender and unsubscribe mechanism.
- GDPR (EU): Unsubscribe must be as easy as subscribing; consent records must be maintained.

Source: FTC CAN-SPAM Act compliance guide; CASL official guidance; ICO GDPR marketing guidance.

---

## Sources

### Primary References

1. **Litmus Blog and Documentation** — litmus.com
   - "Ultimate Guide to Email Design"
   - "Coding HTML Emails"
   - "Web Fonts in Email"
   - "Background Images in HTML Email"
   - "Email Preheader Best Practices"
   - "Dark Mode Email Design Guide"
   - "Email Client Market Share" (2024–2025 reports)
   Used throughout: rendering engine breakdown, image best practices, preheader technique, button design, font handling, dark mode patterns.

2. **Campaign Monitor CSS Guide** — campaignmonitor.com/css/
   - Comprehensive CSS property support matrix per email client (278 properties, 35 clients as of 2024)
   - "Bulletproof Email Buttons"
   - "Responsive Email Design"
   - "Outlook Conditional Comments"
   - "Dark Mode Email Design"
   Used throughout: CSS property support tables, conditional comment patterns, button and layout patterns.

3. **caniemail.com**
   - Machine-readable email client support data (analogous to caniuse.com for browsers)
   - Specific references verified live (2024–2026):
     - /features/css-display-flex/ — flex: ~83% support, last tested Nov 2021
     - /features/css-display-grid/ — grid: ~56% support, last tested Feb 2019
     - /features/css-background-image/ — background-image: ~91% support, last tested Jul 2023
     - /features/css-at-media-prefers-color-scheme/ — prefers-color-scheme: ~42% support, verified 2024
   Used for: Flexbox/Grid/background/dark-mode support data, CSS property compatibility claims.

4. **Email on Acid Blog** — emailonacid.com
   - "Email HTML Boilerplate"
   - "CSS Support in Email"
   - "Outlook CSS Issues"
   - "Email Accessibility Guide"
   Used for: meta tag recommendations, Outlook shorthand padding issues, reset styles.

5. **MJML Documentation** — mjml.io
   - Framework architecture, component reference, transpilation output
   Used in: Tradeoffs section, modern approach discussion.

6. **Nicole Merlin — "The Hybrid Coding Technique"** — webdesignerwall.com
   - Foundational resource for hybrid/spongy layout approach
   Used for: two-column grid pattern, ghost table technique.

7. **buttons.cm** — Campaign Monitor bulletproof button generator
   - VML button technique reference implementation
   Used for: button VML pattern.

8. **FTC CAN-SPAM Act Compliance Guide** — ftc.gov/tips-advice/business-center/guidance/can-spam-act-compliance-guide-business
   Used for: footer legal requirements.

9. **ICO (UK) GDPR Marketing Guidance** — ico.org.uk
   Used for: GDPR unsubscribe requirements.

---

## TODOs

- [x] **Dark mode support**: Completed — see dedicated Dark Mode Support section above. Covers `@media (prefers-color-scheme: dark)`, `color-scheme` meta tag, forced-colour inversion in Gmail, Yahoo/AOL/Fastmail/HEY breaking the media query, and the `[data-ogsb]` Outlook attribute selector.

- [ ] **Gmail CSS improvements**: Google has been progressively expanding CSS support in Gmail (e.g., improved `<style>` block support in 2016). The rate of change means caniemail.com data should be re-verified against the latest Gmail builds before any production deployment. Known current issue: Gmail strips the entire style attribute when `background-image: url()` is inlined — see Hero Image section.

- [ ] **New Outlook (Windows) rendering engine switch**: Microsoft has widely deployed the new Outlook for Windows (Edge/WebKit-based) replacing the Word renderer. As of 2025, enterprise environments still commonly run legacy builds. Monitor: Litmus "New Outlook for Windows" tracking article. The existing MSO conditional comment patterns remain the safe approach until legacy share is negligible in your audience.

- [ ] **MJML component extension patterns**: Research how to build custom MJML components for org-specific design systems (e.g., custom `mj-feature-flag` component).

- [ ] **Accessibility deep-dive**: This document covers `role="presentation"` and `alt` text basics. A dedicated research pass is needed covering: reading order in multi-column layouts, focus order for linked images, ARIA labels on icon buttons, and testing with VoiceOver/NVDA on common clients. Source starting point: Email on Acid "Email Accessibility Guide"; Litmus "Accessible Email Design".

- [ ] **AMP for Email**: Google's AMP for Email (supported in Gmail, Yahoo, Mail.ru) enables interactive email content (carousels, accordions, real-time data). Requires a separate `text/x-amp-html` MIME part alongside standard HTML. Research tradeoffs vs. standard interactivity approaches.

- [ ] **SPF / DKIM / DMARC**: While out of scope for HTML/CSS, deliverability directly impacts whether rendered HTML reaches the inbox. A companion research document on email authentication is recommended.

- [ ] **Testing tooling**: Litmus and Email on Acid both offer screenshot testing across 90+ clients. Research CI integration patterns for automated email regression testing.

COMPLETE
