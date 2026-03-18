# HTML Email Rendering & Client Compatibility

> Research compiled for engineers building transactional email systems.
> Focus: rendering engine differences, feature support, and workarounds that guarantee readability in all clients including legacy Outlook.
>
> Sources verified against live data from caniemail.com, litmus.com/blog, and campaignmonitor.com/css as of March 2026.

---

## Client Landscape

### Desktop Clients

#### Outlook for Windows (2007–2019) — Word Renderer
The most problematic email client for HTML/CSS rendering. Outlook 2007–2019 on Windows uses Microsoft Word's rendering engine (via a COM interface to winword.exe), not a web browser engine. This applies Word's CSS parser, which supports a very limited subset of CSS and HTML.

- **Outlook 2007** (MSO version 12): Word 2007 renderer. No `background-image` on `<div>`, no `border-radius`, no `rgba()`, very limited margin support.
- **Outlook 2010** (MSO version 14): Same Word renderer. Marginally improved list support.
- **Outlook 2013/2016** (MSO version 15): Same Word renderer. Some padding improvements but still severely limited.
- **Outlook 2019** (MSO version 16): Same Word renderer. All legacy issues persist.

**caniemail.com scoreboard** (out of 303 tested features): Outlook Windows scores 59/302 — the lowest of all tracked clients. Source: caniemail.com/scoreboard/.

**CSS quirks specific to these versions (verified via caniemail.com):**
- `padding` — partial: only supported on table cells (`<td>`), and vertical padding adopts the largest value in any row (all cells in a row get the same vertical padding).
- `margin` — partial: negative values not supported; `auto` value not supported; `margin` on `<span>` and `<body>` not supported; `background-color` bleeds into the margin area.
- `max-width` — partial: does not apply to `<table>` elements per the CSS 2.1 specification; use `width` HTML attribute on tables instead.
- `rgba()` — not supported. Use hex fallbacks.

Market share: Outlook desktop holds approximately 5–10% of email opens globally; in B2B enterprise environments it can represent 30–50%+ of opens. Source: Litmus Email Client Market Share data (litmus.com/email-client-market-share).

#### Outlook for Windows (New Outlook / 2021+) — Edge Renderer
Microsoft's "new Outlook" for Windows has migrated from the Word rendering engine to an Edge/Chromium-based renderer. This resolves many legacy Outlook rendering issues.

**What now works:** `border-radius`, `background-image` (via CSS, not VML), `max-width`, `display: flex`, CSS Grid, `rgba()`.

**What still applies:**
- MSO conditional comments (`<!--[if mso]>`) are still parsed, so existing conditionals do not break the new Outlook.
- VML is still processed but is no longer required for most use cases.
- The new Outlook applies forced dark mode colour inversion (does not honour `prefers-color-scheme`).
- `<style>` blocks in `<head>` are supported.

**Adoption caution:** As of early 2026, Microsoft has been rolling out new Outlook as the default on Windows 11 and as a replacement for Windows Mail. However, enterprises with volume licensing often remain on Outlook 2016/2019 via Microsoft 365 Apps perpetual licence. Do not assume new Outlook adoption is universal in B2B audiences. Source: Litmus Blog "New Outlook for Windows" coverage.

#### Outlook for Mac
Uses Apple WebKit rendering engine (same as Safari/Apple Mail). Supports most modern CSS. caniemail.com scores it 175/301. Far fewer rendering issues than Outlook for Windows. Source: caniemail.com/scoreboard/.

#### Apple Mail (macOS)
Uses WebKit. Excellent CSS support including `border-radius`, `background-image`, CSS Grid, `@media` queries, `:hover`, `@font-face`, `prefers-color-scheme`. Scores 283/303 on caniemail.com — the highest of all tracked clients. Source: caniemail.com/scoreboard/.

### Webmail Clients

#### Gmail (web — gmail.com)
Gmail's webmail uses a custom rendering engine. Key behaviours verified against caniemail.com data:

- **`<style>` blocks**: Gmail supports `<style>` tags in `<head>` since approximately 2016, but with significant limitations. As of testing recorded at caniemail.com: `<style>` is not supported inside `<body>`; the `<style>` tag is limited to **16 KB**; inline styles remain the safest approach for universal compatibility. Source: caniemail.com/features/html-style/.
- **102 KB clip**: Gmail clips email HTML at 102,400 bytes (exactly 102 KB) and shows a "[Message clipped] View entire message" link. Content below the clip is not rendered at the time of opening — recipients who do not click through miss all subsequent content. This limit applies to the raw HTML source, including inlined styles. Keep total HTML under 102 KB. Source: Litmus "Gmail Clipping" (litmus.com/blog/gmail-clipping — confirmed still accurate).
- **Background-image — critical quirk**: Gmail desktop webmail has a documented bug (noted at caniemail.com as of 2023-08): **it removes the entire `style` attribute or `<style>` tag when a `url()` function referencing a valid image URL is present**. This means using `background-image` in an inline style on any element can strip all inline styles from that element. Use separate `<td bgcolor="">` for background colours and VML for background images in layouts that must work in Gmail.
- **Scoped CSS**: Gmail wraps email content in a scoped div. Avoid `body { }` rules — use `table` or explicit class selectors instead.
- **No `<link>` support**: External stylesheets are blocked.
- **Relative URLs blocked**: All `src` and `href` attributes must use absolute URLs.
- **CSS animations**: Supported in Gmail desktop webmail since May 2021. Source: caniemail.com/features/css-at-keyframes/.
- **`rgba()`**: Supported since August 2021; whitespace syntax (`rgba(0 128 0 / 1)`) is not supported — use comma syntax (`rgba(0, 128, 0, 1)`). Source: caniemail.com/features/css-rgba/.

caniemail.com score: 152/303 for Gmail desktop webmail. Source: caniemail.com/scoreboard/.

Source: caniemail.com; Campaign Monitor CSS Support Guide (campaignmonitor.com/css/).

#### Gmail App (Android / iOS)
The Gmail mobile app scores lower than Gmail webmail: 110–111/302–303 on caniemail.com. `@media` queries are supported but with restrictions (no nested media queries). Inline styles remain the safest approach. Background images only work with Google accounts. Source: caniemail.com/scoreboard/; caniemail.com/features/css-at-media/.

#### Yahoo Mail / AOL Mail
Supports `<style>` blocks. Moderate CSS support. Scores 125–136/301–303 on caniemail.com depending on platform. Notable limitations:
- Does not support `@font-face`.
- `@media` queries supported but limited to `screen`, `width`, and `height` parameters only (no nested media queries).
- `background-size`: partial — does not support multiple values (comma separator removed).
- `rgba()`: supported since January 2021; whitespace syntax not supported.
- `prefers-color-scheme`: not supported — the query is transformed into `@media ( _filtered_a )` rendering it ineffective.
- CSS animations (`@keyframes`): supported since May 2021.

Source: caniemail.com; Campaign Monitor CSS Guide.

#### Outlook.com / Hotmail
Microsoft's webmail. Scores 172/303 on caniemail.com — considerably better than desktop Outlook. Supports `<style>` blocks, `border-radius`, `rgba()`, CSS animations.
- `prefers-color-scheme`: partial support (since July 2019) — adds custom `data-ogsc`/`data-ogac`/`data-ogsb`/`data-ogab` attributes in dark mode rather than honouring the standard media query directly.
- `:hover`: partial — only supported on type selectors.

Source: caniemail.com/scoreboard/.

### Mobile Clients

#### iOS Mail (iPhone/iPad)
Uses WebKit. Excellent CSS support. Scores 280/303 on caniemail.com. Supports `@media` queries, `@font-face`, `border-radius`, `background-image`, `prefers-color-scheme` (since iOS 12.2), `rgba()` (since iOS 12), CSS animations (since iOS 13).

Market share: iOS Mail is consistently the #1 or #2 email client globally. Source: Litmus market share data (litmus.com/email-client-market-share).

Source: caniemail.com/scoreboard/.

#### Samsung Email (Android)
Samsung Email uses a Chromium-based WebKit renderer. Scores 250/300 on caniemail.com — the third highest of all tracked clients. Good CSS support including `@media` queries, `border-radius`, `prefers-color-scheme` (from version 6.0+).
- **Background images**: requires at least one `<img>` element in the email for background images to download.
- `@media` queries: buggy with non-Samsung accounts.

Source: caniemail.com/scoreboard/.

#### Android Gmail App
See Gmail App above. CSS support is considerably more limited than Samsung Email (111/303 vs 250/300).

### Other Clients

#### Thunderbird (Desktop)
Uses Mozilla Gecko renderer. Good CSS support. Supports `<style>` blocks, `@media` queries, `border-radius`. Privacy-focused user base; niche but non-trivial in developer and enterprise audiences. Source: caniemail.com.

#### HEY, Superhuman, Fastmail
Modern email clients generally use WebKit or Electron/Chromium. Fastmail scores particularly well. Fastmail supports `display: flex`, `@font-face`, `@media` queries, `border-radius`. Niche combined market share but growing in developer and startup audiences.

---

## Feature Support Matrix

The following matrix rates feature support as:
- **SAFE**: Works reliably in all major clients including Outlook 2007–2019
- **PARTIAL**: Works in most modern clients; broken or unsupported in Outlook 2007–2019 and/or some webmail
- **RISKY**: Avoid for layout-critical properties; may work in some clients but not reliably enough for transactional email

All data verified against caniemail.com unless otherwise noted. "Outlook 2007–19" in this matrix refers specifically to the Word-renderer versions.

### Layout & Structure

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `<table>` layout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `<div>` for layout | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | **RISKY** |
| `display: flex` | ❌ | ✅ | ✅ | ✅ | ✅ | Partial* | **RISKY** |
| `display: grid` | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | **RISKY** |
| `float` | ❌ | ✅ | Partial | ✅ | ✅ | Partial | **RISKY** |
| `position: absolute` | ❌ | ✅ | ❌ | Partial | Partial | ❌ | **RISKY** |
| `max-width` on `<table>` | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `max-width` on `<td>/<div>` | Partial | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `width` (HTML attr) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `cellpadding="0"` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `cellspacing="0"` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |

*`display: flex` is supported; `display: inline-flex` is not supported in Yahoo/AOL.

Source: caniemail.com/features/css-display-flex/; caniemail.com/scoreboard/.

### Typography

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `font-family` (web-safe) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `@font-face` | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | **PARTIAL** |
| `font-size` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `font-weight` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `line-height` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `letter-spacing` | Partial | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `text-transform` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `text-decoration` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |

Source: caniemail.com; Litmus "Web Fonts in Email".

### Colour & Background

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `background-color` (inline) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `background-image` on `<td>` | VML only | ✅ | Buggy† | ✅ | ✅ | Partial | **RISKY** |
| `background-image` on `<div>` | ❌ | ✅ | Buggy† | ✅ | ✅ | Partial | **RISKY** |
| VML background image | ✅ (Outlook only) | ✅ | ❌ | ❌ | ❌ | ❌ | Use with CSS fallback |
| `background-size` | VML only | ✅ | Partial‡ | ✅ | ✅ | Partial | **PARTIAL** |
| Hex colours | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `rgba()` colours | ❌ | ✅ | ✅ (2021+) | ✅ | ✅ | ✅ (2021+) | **PARTIAL** |

†**Gmail background-image bug**: Gmail web (desktop) removes the entire `style` attribute or `<style>` block when a `url()` function is detected in CSS. This strips ALL inline styles from affected elements. Avoid `background-image` in inline styles for Gmail-compatible layouts. Use `bgcolor` HTML attribute for background colours, and conditional VML for background image sections. Source: caniemail.com/features/css-background-image/.

‡Gmail: `background-size` only works with Google accounts; non-Google accounts using Gmail webmail do not get this support.

Source: caniemail.com/features/css-background-image/; caniemail.com/features/css-background-size/; caniemail.com/features/css-rgba/.

### Spacing & Borders

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `padding` on `<td>` (explicit sides) | Partial* | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `padding` shorthand | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | **RISKY** |
| `margin` on `<td>` | Partial† | ✅ | ❌ | ✅ | ✅ | ❌ | **RISKY** |
| `border` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `border-radius` | ❌ | ✅ | ✅ | ✅ | ✅ | Partial‡ | **PARTIAL** |
| `border-collapse` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |

*Outlook 2007–19 `padding` on `<td>`: buggy — vertical padding adopts the largest value in the row, meaning all cells in the same row share the same vertical padding regardless of individual declarations. Use padding on one cell per row only.

†Outlook 2007–19 `margin`: partial — no negative values, no `auto`, bleeds into `background-color` area, not supported on `<span>` or `<body>`.

‡Yahoo/AOL `border-radius`: elliptical borders using the slash `/` notation (e.g. `border-radius: 50px / 25px`) are not supported.

Source: caniemail.com/features/css-padding/; caniemail.com/features/css-border-radius/; caniemail.com/features/css-margin/.

### Images & Media

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `<img>` with `width`/`height` attrs | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `max-width: 100%` on `<img>` | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `display: block` on `<img>` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| Retina images (2× src) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| Animated GIF | ❌ (shows first frame) | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| `<video>` | ❌ (tags stripped) | Partial* | ❌† | Partial | ✅ | ❌† | **RISKY** |
| SVG images | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | **RISKY** |

*New Outlook macOS 16.80: allows right-click to play video only.

†Gmail and Yahoo: `<video>` tags are removed or replaced with `<u></u>` tags; fallback content is shown instead. Always include a fallback image inside `<video>` using `<img>` as the first child.

Source: caniemail.com/features/html-video/.

### Responsive & Media Queries

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Android Gmail | SAFE? |
|---|---|---|---|---|---|---|---|
| `@media` queries | ❌ | ✅ | Partial* | ✅ | ✅ | Partial* | **PARTIAL** |
| Hybrid/spongy layout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **SAFE** |
| `prefers-color-scheme` | ❌ | ❌ (forced inversion) | ✅ (2020+) | ✅ | ✅ (iOS 12.2+) | ❌ | **PARTIAL** |

*Gmail (desktop and mobile): `@media` queries supported but nested media queries are not supported. Yahoo Mail: `@media` supported but only `screen`, `width`, and `height` parameters — no `prefers-*` queries.

Source: caniemail.com/features/css-at-media/; caniemail.com/features/css-at-media-prefers-color-scheme/.

### Interactivity & Advanced

| Feature | Outlook 2007–19 | New Outlook (2021+) | Gmail web | Apple Mail | iOS Mail | Yahoo | SAFE? |
|---|---|---|---|---|---|---|---|
| `:hover` pseudo-class | ✅* | ✅ | Partial† | ✅ | ✅ | ✅ | **PARTIAL** |
| CSS animations (`@keyframes`) | ❌ | ✅ | ✅ (2021+) | ✅ | ✅ | ✅ (2021+) | **PARTIAL** |
| AMP for Email | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | **PARTIAL** |
| `<details>`/`<summary>` | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | **RISKY** |

*Outlook 2007–19 `:hover`: confirmed supported on type selectors per caniemail.com testing (last tested October 2019). Outlook.com: partial — only type selectors.

†Gmail web `:hover`: partial — not supported with non-Google accounts.

Important note on CSS animations: overall support across all tracked email clients is only ~34% (caniemail.com estimate). Do not rely on animations for critical content — always ensure the static state is the primary readable state.

Source: caniemail.com/features/css-pseudo-class-hover/; caniemail.com/features/css-at-keyframes/; caniemail.com/features/css-at-media-prefers-color-scheme/.

---

## Transactional Guarantees & Workarounds

For transactional emails (order confirmations, password resets, receipts, alerts), content MUST be readable in all clients. The following techniques guarantee this.

### 1. DOCTYPE and HTML Structure

Always use the XHTML 1.0 Strict doctype with explicit `xmlns`. This forces Outlook out of quirks mode and ensures consistent baseline rendering.

```html
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <title>Your Subject Line Here</title>
</head>
```

Source: Litmus "Email Coding 101"; Email on Acid "Email HTML Boilerplate".

### 2. CSS Reset for Email

Include these resets in a `<style>` block AND as inline styles on key elements. They address known Outlook, iOS, and Gmail rendering issues.

```css
/* In <style> block — keep this block under 16 KB (Gmail limit) */
body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
img { -ms-interpolation-mode: bicubic; border: 0; height: auto;
      line-height: 100%; outline: none; text-decoration: none; }
body { margin: 0 !important; padding: 0 !important; width: 100% !important; }
a[x-apple-data-detectors] { color: inherit !important; text-decoration: none !important;
                              font-size: inherit !important; }
/* u + #body prevents Gmail from applying its own link styles */
u + #body a { color: inherit; text-decoration: none; font-size: inherit; }
```

**Why each reset matters:**
- `mso-table-lspace/rspace: 0pt`: Removes phantom 1–3px spacing Outlook adds between table cells, causing pixel-level layout shifts.
- `-webkit-text-size-adjust: 100%`: Prevents iOS/Android from auto-enlarging small fonts when rendering narrow-viewport emails.
- `a[x-apple-data-detectors]`: Prevents Apple Mail from auto-detecting phone numbers, addresses, and dates and styling them as links with default blue underlines — critical for transactional data like order totals or addresses.
- `u + #body a`: The Gmail hack — Gmail wraps email content in a `<u>` tag; this selector targets links inside that wrapper to override Gmail's default link styling without using `body` selectors (which Gmail strips).

Source: Litmus Email Boilerplate (github.com/seanpowell/Email-Boilerplate); Campaign Monitor reset patterns.

### 3. Table-Based Layout (Universal Guarantee)

Tables are the only layout primitive that works in all email clients including Outlook 2007–2019. Every structural layout element must use `<table>`. Use `role="presentation"` on all layout tables to indicate they are not data tables — this is required for screen reader accessibility.

```html
<!-- Outer wrapper: fills viewport width -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       width="100%" style="background-color: #f4f4f4;">
  <tr>
    <td align="center">
      <!-- Inner: fixed 600px content width -->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0"
             width="600" style="max-width: 600px; width: 100%;">
        <tr>
          <td style="padding: 20px; background-color: #ffffff;">
            <!-- All content here -->
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
```

The outer 100%-width table fills any viewport. The inner 600px-wide table contains all content. `max-width: 600px` allows the inner table to shrink on narrow viewports in modern clients. Outlook 2007–19 ignores `max-width` on `<table>` elements (per CSS 2.1 spec), but the `width="600"` HTML attribute caps it at 600px there.

Source: Campaign Monitor "HTML Email Best Practices"; Litmus "Tables in Email Design".

### 4. Padding on Table Cells — Outlook Quirk

Outlook 2007–19 has a critical padding bug: **vertical padding is shared across all cells in the same row**. If one `<td>` in a row has `padding-top: 40px` and another has `padding-top: 0`, Outlook applies 40px to both.

**Workaround:** Apply padding only to a single `<td>` per row, or use empty rows with a fixed height for spacing.

```html
<!-- Safe: vertical spacing via empty row -->
<tr>
  <td height="20" style="font-size: 0; line-height: 20px;">&nbsp;</td>
</tr>

<!-- Or: use padding on a single wrapping td -->
<tr>
  <td style="padding: 20px 0;">
    <!-- content -->
  </td>
</tr>
```

Source: caniemail.com/features/css-padding/.

### 5. MSO Conditional Comments

MSO (Microsoft Office) conditional comments are HTML comments that Outlook's Word renderer processes but other clients ignore. Use them to insert Outlook-specific HTML or override styles. These also apply to the new Outlook (2021+), which still parses MSO conditionals.

```html
<!-- Visible only to Outlook (all versions) -->
<!--[if mso]>
  <table role="presentation"><tr><td width="600">
<![endif]-->

<!-- Visible to all clients EXCEPT Outlook -->
<!--[if !mso]><!-->
  <div style="max-width: 600px;">
<!--<![endif]-->

<!-- Version-specific targeting -->
<!--[if mso 12]>  Outlook 2007 only  <![endif]-->
<!--[if mso 14]>  Outlook 2010 only  <![endif]-->
<!--[if mso 15]>  Outlook 2013/2016/2019  <![endif]-->
<!--[if (mso 12)|(mso 14)]>  Outlook 2007 or 2010  <![endif]-->
<!--[if gte mso 9]>  Outlook 2000 and later  <![endif]-->
```

Source: Campaign Monitor "Outlook Conditional Comments" (campaignmonitor.com); Microsoft Office conditional comment documentation.

### 6. Ghost Table for Hybrid Layouts

The "ghost table" technique enables two-column layouts that work in Outlook (via MSO conditional tables) while using `display: inline-block` in modern clients.

```html
<!-- Ghost table: Outlook sees a table; modern clients see inline-blocks -->
<!--[if mso]>
<table role="presentation" border="0" cellpadding="0" cellspacing="0">
<tr><td valign="top" style="width: 280px; padding-right: 20px;">
<![endif]-->
<div style="display: inline-block; vertical-align: top;
            width: 100%; max-width: 280px;">
  <!-- Left column content -->
</div>
<!--[if mso]>
</td><td valign="top" style="width: 280px; padding-left: 20px;">
<![endif]-->
<div style="display: inline-block; vertical-align: top;
            width: 100%; max-width: 280px;">
  <!-- Right column content -->
</div>
<!--[if mso]>
</td></tr></table>
<![endif]-->
```

Source: Nicole Merlin "Hybrid Coding Technique for Email" (webdesignerwall.com); Litmus "Ghost Tables".

### 7. VML Bulletproof Buttons

`<a>` padding is not rendered in Outlook 2007–19. Bulletproof buttons use VML (Vector Markup Language) for Outlook and standard CSS for other clients. The new Outlook (2021+) does not require VML but processes it harmlessly.

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       style="margin: 0 auto;">
  <tr>
    <td align="center" bgcolor="#0066cc"
        style="border-radius: 4px; background-color: #0066cc;">
      <!--[if mso]>
      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                   xmlns:w="urn:schemas-microsoft-com:office:word"
                   href="https://example.com/action"
                   style="height:44px; v-text-anchor:middle; width:200px;"
                   arcsize="10%" stroke="f" fillcolor="#0066cc">
        <w:anchorlock/>
        <center style="color:#ffffff; font-family:Arial,sans-serif;
                        font-size:16px; font-weight:bold;">
          Confirm Order
        </center>
      </v:roundrect>
      <![endif]-->
      <!--[if !mso]><!-->
      <a href="https://example.com/action" target="_blank"
         style="display: inline-block; color: #ffffff;
                font-family: Arial, sans-serif; font-size: 16px;
                font-weight: bold; line-height: 44px;
                text-decoration: none; padding: 0 24px;
                border-radius: 4px; background-color: #0066cc;
                mso-hide: all;">
        Confirm Order
      </a>
      <!--<![endif]-->
    </td>
  </tr>
</table>
```

Source: Campaign Monitor "Bulletproof Email Buttons" (buttons.cm); Litmus "Bulletproof Buttons".

### 8. VML Background Images for Outlook

`background-image` on `<div>` elements is not supported in Outlook 2007–2019. Use VML for background images targeting Outlook. Note: because Gmail also strips styles when `background-image` URLs are present (see Gmail quirk above), this VML-plus-CSS approach is the safest pattern across all clients.

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
  <tr>
    <!--[if mso]>
    <td align="center" valign="middle">
    <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false"
            style="width:600px; height:250px;">
      <v:fill type="tile" src="https://example.com/bg.jpg" color="#1a1a2e"/>
      <v:textbox inset="0,0,0,0">
    <![endif]-->
    <!--[if !mso]><!-->
    <td align="center" valign="middle"
        style="background-color: #1a1a2e; padding: 40px;">
      <!-- Note: background-image omitted here to avoid Gmail stripping inline styles.
           Use a separate <style> block rule for background-image if needed,
           accepting that Gmail desktop webmail will not show the image. -->
    <!--<![endif]-->
      <!-- Content over background -->
    <!--[if mso]>
      </v:textbox>
    </v:rect>
    </td>
    <![endif]-->
  </tr>
</table>
```

The `color="#1a1a2e"` in the VML fill serves as a fallback if the image fails to load in Outlook. The inline `background-color` on the `<td>` serves as the fallback in all other clients.

Source: Litmus "Background Images in HTML Email: VML Fallbacks"; caniemail.com/features/css-background-image/.

### 9. Image Blocking Resilience

Major email clients (Outlook, some Gmail contexts, corporate security appliances) block images by default. Transactional emails MUST be comprehensible without images.

```html
<!-- Always: explicit width/height, meaningful alt, background-color fallback -->
<img src="https://cdn.example.com/order-confirmed.png"
     width="80" height="80"
     alt="Order confirmed"
     style="display: block; border: 0; background-color: #0066cc;" />

<!-- Logo with company name as alt text -->
<img src="https://cdn.example.com/logo.png"
     width="150" height="50"
     alt="Acme"
     style="display: block; border: 0;" />
```

**Rules:**
- `alt` text must convey the image's meaning, not just describe it ("Order confirmed" not "checkmark icon").
- Set `background-color` on `<img>` to match brand colour — shows when image is blocked.
- Never put critical transactional data (order number, amount) only in an image.
- Samsung Email requires at least one `<img>` element in the email for background images to download. Source: caniemail.com/features/css-background-image/.

Source: Litmus "Email Image Blocking" statistics; Campaign Monitor "Alt Text in Email".

### 10. Gmail 102 KB HTML Clip Prevention

Gmail clips email HTML at exactly 102,400 bytes (102 KB) and replaces the rest with a "[Message clipped] View entire message" link. Recipients who do not click that link miss all content below the clip. This is measured against the raw HTML source, including all inlined CSS declarations.

**Note on Gmail `<style>` size limit**: Gmail also limits individual `<style>` blocks to 16 KB. This is separate from the 102 KB total HTML clip. Both limits apply independently. Source: caniemail.com/features/html-style/.

**Prevention:**
- Keep total HTML under 102 KB.
- Inline CSS efficiently — avoid redundant declarations, use explicit padding sides (`padding-top`, `padding-right`, etc.) only where needed.
- Move tracking pixels to the top of the email (above the fold, within the first kilobytes).
- Put the most critical transactional content (order summary, CTA button) near the top.
- If HTML is unavoidably large: include a visible "View in browser" link at the very top.

Detection: Google provides no notification when an email is clipped. Test by sending to a Gmail account and checking if the "[Message clipped]" text appears in the rendered email.

Source: Litmus "Gmail Clipping" (litmus.com/blog/gmail-clipping); Email on Acid "Gmail 102KB Limit"; caniemail.com/features/html-style/.

### 11. Fluid / Hybrid Mobile Layout

The hybrid ("spongy") technique creates mobile-responsive layouts without relying on `@media` queries — critical because some Gmail contexts and webmail clients have restricted media query support.

Principle: outer tables at 100% width, inner content tables at `max-width` with `width: 100%`. Content fills available width on narrow screens without media queries.

```html
<!-- Fluid outer: fills any viewport -->
<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center">
      <!-- Inner: shrinks below 600px automatically in modern clients -->
      <table role="presentation" width="600" border="0" cellpadding="0" cellspacing="0"
             style="max-width: 600px; width: 100%;">
        <tr>
          <td style="padding: 20px;">
            <!-- Content -->
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
```

For two-column layouts that should stack on mobile without media queries, use `display: inline-block` with `max-width` values that collapse gracefully (see Ghost Table section above).

Source: Nicole Merlin "Hybrid Coding Technique"; Campaign Monitor "Responsive Email Design".

### 12. Preheader Text

The preheader is the short preview text displayed in inbox listings after the subject line. If not explicitly set, email clients pull the first visible text from the email body — which may be "View in browser" links, navigation items, or "unsubscribe" text.

Always include a hidden preheader immediately after `<body>`:

```html
<div style="display: none; max-height: 0; overflow: hidden; visibility: hidden;
            mso-hide: all; font-size: 1px; color: #f4f4f4; line-height: 1px;
            max-width: 0px; opacity: 0;">
  Your order #12345 has shipped. Expected delivery: Friday, March 20.
  &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
</div>
```

The zero-width non-joiner characters (`&zwnj;`) pad the preview text to prevent the email client from pulling additional body content into the preview after the intentional preheader ends.

Keep preheader under 100 characters — most clients truncate beyond that. Treat it as a second subject line.

Source: Litmus "Preview Text / Preheader" (litmus.com/blog/the-ultimate-guide-to-preview-text-support); Campaign Monitor "Email Preheader".

### 13. Dark Mode Considerations

Dark mode rendering in email is inconsistent and splits into two behaviours:

**Clients that honour `prefers-color-scheme` (developer can target):**
- Apple Mail (macOS and iOS 12.2+)
- Outlook.com (partial — uses `data-ogsc`/`data-ogac` attributes)
- Outlook for Mac (macOS 2019+)
- Gmail web (2020+)
- Samsung Email (6.0+)

**Clients that force colour inversion WITHOUT honouring `prefers-color-scheme`:**
- New Outlook for Windows (2021+)
- Windows Mail
- Gmail App (iOS) — full inversion
- Gmail App (Android) — partial inversion
- Outlook App (Android) — partial inversion

**Workarounds for forced inversion clients:**
- Use off-white (`#fffffe`) instead of pure white (`#ffffff`) — some inversion engines skip near-white values.
- Use off-dark (`#1a1a1a`) instead of pure black for dark backgrounds.
- For the new Outlook Windows forced inversion: MSO-specific gradient CSS properties and VML techniques can override inversion in some cases.
- For Gmail iOS: CSS blend modes combined with the Gmail `u + #body` selector hack can retain original colours.

Source: Litmus "The Ultimate Guide to Dark Mode for Email"; caniemail.com/features/css-at-media-prefers-color-scheme/.

### 14. Min-Height Workaround for Outlook

`min-height` is not supported in Outlook 2007–2019. Use a VML or height attribute technique to enforce minimum section heights.

```html
<!-- Spacer row: enforces minimum height in Outlook via height attribute -->
<tr>
  <td height="120" style="min-height: 120px; font-size: 0; line-height: 0;">&nbsp;</td>
</tr>
```

For sections where content height is variable but a minimum is required, use an empty `<td>` with a `height` HTML attribute (which Outlook respects) combined with `min-height` CSS (which modern clients use).

Source: Standard email development workaround pattern.

### 15. Transactional Email Minimum Checklist

These are the absolute minimum requirements for a transactional email to be readable in all major clients:

- [ ] HTML under 102 KB total
- [ ] `<style>` blocks under 16 KB each (Gmail limit)
- [ ] All critical content in text (not just images)
- [ ] All styles inlined on elements; `<style>` block as progressive enhancement only
- [ ] No `background-image` in inline styles (strips all styles in Gmail web)
- [ ] `<table>` used for all structural layout
- [ ] `role="presentation"` on all layout tables
- [ ] `border="0" cellpadding="0" cellspacing="0"` on all tables
- [ ] Padding applied to one `<td>` per row only (Outlook vertical padding bug)
- [ ] All `<img>` tags have `width`, `height`, `alt`, `display: block`
- [ ] `bgcolor` HTML attribute used in addition to CSS `background-color` for safety
- [ ] All `src` and `href` use absolute URLs (https://)
- [ ] Preheader text set explicitly and padded with `&zwnj;` characters
- [ ] Plain-text version included in MIME multipart
- [ ] Unsubscribe link present (even for transactional — best practice and increasingly a deliverability requirement)
- [ ] Physical mailing address in footer (CAN-SPAM requirement)
- [ ] VML button provided for Outlook (not just CSS button)
- [ ] Tested in Outlook 2016 (Windows) as minimum Outlook test target
- [ ] Tested in Gmail web (desktop) and Gmail iOS app

Source: Litmus "Email Testing Checklist"; Email on Acid "Pre-Send Email Checklist"; caniemail.com feature data.

---

## Sources

1. **caniemail.com** — Primary source for all feature support matrix data.
   - /scoreboard/ — Client scores out of 303 features (Apple Mail 283, Samsung Email 250, Outlook Mac 175, Outlook.com 172, Gmail desktop 152, Yahoo 125–136, Outlook Windows 59).
   - /features/css-display-flex/ — flex support (~83% estimated across tracked clients; Outlook Windows not supported, Yahoo partial for `inline-flex`).
   - /features/css-at-media/ — @media support (~80% estimated; Gmail no nested queries; Yahoo limited parameters).
   - /features/css-border-radius/ — ~83% support; Yahoo/AOL partial (no slash notation).
   - /features/css-padding/ — Outlook 2007–19 partial (table cells only; vertical padding row bug).
   - /features/css-margin/ — Outlook 2007–19 partial (no negative/auto; bleeds into background).
   - /features/css-max-width/ — Outlook 2007–19 partial (not on `<table>` elements).
   - /features/css-rgba/ — Outlook 2007–19 not supported; Gmail/Yahoo from 2021; no whitespace syntax.
   - /features/css-background-image/ — Gmail web buggy (strips style attributes containing url()); Outlook VML only.
   - /features/css-background-size/ — Outlook VML only; Gmail partial (Google accounts only).
   - /features/css-at-keyframes/ — ~34% overall support; Gmail from 2021-05; Yahoo from 2021-05; Outlook not supported.
   - /features/css-pseudo-class-hover/ — ~68% overall support; Outlook 2007–19 supported; Gmail partial (Google accounts only).
   - /features/css-at-media-prefers-color-scheme/ — ~42% support; not supported in Outlook 2007–19, Yahoo; Outlook.com partial.
   - /features/html-style/ — Gmail limits `<style>` to 16 KB; not supported inside `<body>`.
   - /features/html-video/ — ~24% overall support; Gmail/Yahoo strip tags.

2. **Litmus** — litmus.com/blog and litmus.com/email-client-market-share
   - Market share data: iOS Mail globally #1 or #2; Outlook desktop 5–10% globally, 30–50%+ in B2B enterprise.
   - "The Ultimate Guide to Dark Mode for Email Marketers" — dark mode client breakdown and workarounds.
   - "Gmail Clipping" — 102 KB clip limit confirmed current.
   - "Preview Text Support" — preheader patterns.
   - "New Outlook for Windows" — Edge renderer adoption and CSS capability changes.
   - "Bulletproof Email Buttons" — VML button technique.
   - "Email Coding 101" — DOCTYPE and baseline structure.

3. **Campaign Monitor CSS Support Guide** — campaignmonitor.com/css/
   - Tests 278 CSS properties across 35 email clients.
   - Used for: conditional comments documentation, VML documentation, reset patterns.

4. **Email on Acid Blog** — emailonacid.com
   - "Gmail Rendering Guide" — Gmail scoped CSS and link styling quirks.
   - "Email HTML Boilerplate" — reset patterns.
   - "Pre-Send Email Checklist" — checklist items.

5. **Nicole Merlin — "Hybrid Coding Technique"** — webdesignerwall.com
   - Used for: fluid/hybrid layout technique, ghost table methodology.

6. **FTC CAN-SPAM Act Compliance Guide** — ftc.gov
   - Physical address requirement in transactional email footer.

7. **Litmus Email Boilerplate** — github.com/seanpowell/Email-Boilerplate
   - CSS reset patterns and `u + #body` Gmail hack.

8. **Google AMP for Email documentation** — developers.google.com/gmail/ampemail
   - AMP component support in Gmail and Yahoo Mail.

---

## Open Research Items

- **New Outlook (2021+) enterprise rollout pace**: As Microsoft continues rolling out new Outlook as the Windows 11 default, track when B2B audience shares shift enough that VML-only workarounds (vs CSS-first with VML fallback) can be deprioritised. Check Litmus market share data quarterly.

- **AMP for Email production patterns**: AMP is supported in Gmail, Yahoo Mail, and Mail.ru. Document production use cases (carousels, forms, real-time order status) and the required non-AMP MIME fallback structure for clients that do not support it.

- **Dark mode — comprehensive workaround matrix**: The current research covers the high-level split between `prefers-color-scheme` clients and forced-inversion clients. A dedicated dark mode research pass should document specific CSS selectors and VML overrides for each major client, including the Gmail blend-mode technique.

- **Apple Mail Privacy Protection (MPP) — tracking implications**: iOS 15+ Apple Mail pre-fetches email content (including tracking pixels) regardless of whether the user opens the email. This inflates open rate metrics. Research implications for transactional open tracking, IP warming calculations that depend on open rates, and any engineering compensations in the email sending pipeline.

- **Samsung One UI version matrix**: Samsung Email behaviour has changed across One UI versions, and the `@media` query bug with non-Samsung accounts is documented but not fully characterised across versions. Validate CSS support levels against current Samsung Galaxy test devices.

- **CSS `min-height` VML spacer technique**: Document the standard VML spacer as an alternative to height attributes for minimum-height sections, including how it interacts with the new Outlook's Edge renderer.

- **Accessibility intersection**: The rendering compatibility patterns documented here should be cross-referenced with WCAG requirements. Focus indicators on buttons, semantic heading structure via `<h1>`–`<h6>` in table-based layouts, and `role` attributes for non-presentation tables all need client-specific validation.

- **Email security headers (SPF/DKIM/DMARC)**: Out of scope for rendering research but directly impacts deliverability. A companion technical hygiene document should cover authentication requirements, BIMI support, and the impact of DMARC `p=reject` policies on forwarded transactional emails.

COMPLETE
