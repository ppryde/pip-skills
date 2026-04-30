# Gotchas & Edge Cases — Email Doctrine

## Purpose

Documents the non-obvious traps, client-specific regressions, and silent failure modes that survive rendering and deliverability tests but bite in production. These rules are drawn from verified issue reports in hteumeuleu/email-bugs, caniemail.com feature data, and live client testing. Many of these issues are invisible in screenshot testing — they manifest only in real send-and-receive environments.

## Rule Catalog

---

**[GOTCHA-001]** `transactional: mortal | marketing: mortal` — Do not use `url()` in inline `style` attributes.
> Gmail desktop webmail strips the **entire** `style` attribute from any element that contains a `url()` function — including all other properties on that element. `background-image: url(hero.jpg)` causes every inline style on that `<td>` (padding, colour, font-size) to vanish. Apply background images via `<style>` block classes only. Source: caniemail.com/features/css-background-image/ (verified 2026-03-17).
> `detect: regex` — pattern: `style="[^"]*url\(`

**[GOTCHA-002]** `transactional: mortal | marketing: mortal` — Total compiled HTML must stay under 80 KB as a safe margin against the 102 KB Gmail clip.
> Gmail clips the HTML body at exactly 102,400 bytes and replaces the remainder with a "View entire message" link. The clip occurs mid-document — transactional CTAs and order details placed after the clip boundary are effectively invisible. Inline CSS is the primary cause of size inflation. Source: Litmus "Gmail Clipping"; caniemail.com.
> `detect: contextual` — estimate compiled HTML byte count; flag at 80KB warning, error at 102KB

**[GOTCHA-003]** `transactional: mortal | marketing: mortal` — Gmail strips `<style>` block content above approximately 16 KB.
> This is distinct from the 102 KB HTML clip. Gmail silently strips the `<style>` tag content when it exceeds ~16 KB, causing catastrophic layout failure without any visible error. Keep `<style>` blocks lean; inline critical layout properties if the block grows large. Source: caniemail.com/features/html-style/; hteumeuleu/email-bugs.
> `detect: contextual` — estimate `<style>` block byte count; flag if approaching 16KB

**[GOTCHA-004]** `transactional: mortal | marketing: mortal` — Do not use CSS Color Level 4 whitespace-separated colour syntax.
> Gmail strips entire style rules containing `rgb(51 51 51)` or `rgba(0 0 0 / 0.5)` — the comma-free whitespace syntax introduced in CSS Color Level 4. Only the legacy comma-separated syntax (`rgb(51, 51, 51)`, `rgba(0, 0, 0, 0.5)`) is safe. Source: hteumeuleu/email-bugs #160 (2025).
> `detect: regex` — pattern: `(?:rgb|rgba)\([^)]*\s[^),]*(?:/[^)]*)?(?:[^,)])\)`

**[GOTCHA-005]** `transactional: venial | marketing: venial` — Always version image URLs — Gmail caches images permanently by URL.
> Gmail proxies images via `googleusercontent.com` and caches them indefinitely. The cache key is the original URL. Updating an image file at the same URL has no effect on already-delivered emails; Gmail continues serving the original version. Source: Litmus "Gmail Image Caching".
> `detect: contextual` — advisory; check if image URLs in templates include version markers (query string or versioned filename)

**[GOTCHA-006]** `transactional: mortal | marketing: mortal` — Do not use `id`-based references in email — Gmail and Outlook.com prefix `id` attributes.
> Gmail and Outlook.com prefix `id` attribute values to prevent collisions with the webmail DOM. This silently breaks `aria-labelledby`, `aria-describedby`, `<label for="...">`, and fragment anchors. `#section-name` links never work in email. Use `aria-label` instead of `aria-labelledby`. Source: caniemail.com/features/html-aria-labelledby/; caniemail.com/features/html-aria-describedby/.
> `detect: regex` — pattern: `(?:aria-(?:labelledby|describedby)|for)=["'][^"']+["']`

**[GOTCHA-007]** `transactional: mortal | marketing: mortal` — Do not use `display: flex` for structural layout in Gmail-targeted emails.
> Gmail desktop webmail supports `display: flex` only for Google account users. Users accessing Gmail webmail with a non-Google account (a company account hosted elsewhere but using Gmail's interface) do not get flex support. Use table-based layout for all structural elements. Source: caniemail.com/features/css-display-flex/ (verified 2026-03-18).
> `detect: regex` — pattern: `display\s*:\s*flex`

**[GOTCHA-008]** `transactional: venial | marketing: venial` — Set explicit `width` attributes on images — Gmail mobile webmail ignores `max-width: 100%`.
> Gmail's mobile webmail (responsive web view) does not honour `max-width: 100%` on `<img>` elements. Images wider than their container overflow. Use `max-width: 100%` only as progressive enhancement layered on top of an explicit `width` attribute. Source: hteumeuleu/email-bugs #152.
> `detect: contextual` — check that images have explicit `width` attribute in addition to `max-width` CSS

**[GOTCHA-009]** `transactional: mortal | marketing: mortal` — Outlook 2007–2019 ignores `min-height`.
> Outlook Windows renders HTML using the Word engine, which has no concept of `min-height`. Containers collapse to their content height. Use transparent spacer images or VML to enforce minimum heights in Outlook. Source: Campaign Monitor CSS guide; Litmus Outlook notes.
> `detect: regex` — pattern: `min-height\s*:`

**[GOTCHA-010]** `transactional: venial | marketing: venial` — Set `mso-line-height-rule: exactly` when precise line heights are required in Outlook 2007–2019.
> Outlook Windows uses "at least" semantics for `line-height` by default — it adds extra spacing above the specified value. Without `mso-line-height-rule: exactly`, Outlook inflates line heights inconsistently. `line-height` set on `<td>` is not inherited by child text elements in Outlook. Source: Litmus "Outlook Line Height Bug".
> `detect: contextual` — check if `line-height` declarations include `mso-line-height-rule: exactly` on text-containing elements

**[GOTCHA-011]** `transactional: mortal | marketing: mortal` — Ghost table column dividers must have no whitespace between the closing `</div>` and the MSO conditional comment.
> Inline-block elements have a 4px whitespace gap between them in all modern clients when there is any whitespace (newline, space, indent) between the elements. In ghost table multi-column layouts, the whitespace between column divs creates this gap in Gmail and Apple Mail. Source: Campaign Monitor "Responsive Email"; Litmus Boilerplate.
> `detect: contextual` — check multi-column layouts for whitespace between inline-block div columns and MSO conditional comments

**[GOTCHA-012]** `transactional: mortal | marketing: mortal` — Do not use `float` in Outlook 2007–2019 content — it crops text.
> In Outlook Windows, placing a table with `float` inside a `<td>` with a background colour causes text content following the floated table to be cropped and not displayed. Use MSO conditional table columns for all multi-column layouts. Source: hteumeuleu/email-bugs #158.
> `detect: regex` — pattern: `float\s*:\s*(?:left|right)`

**[GOTCHA-013]** `transactional: venial | marketing: venial` — Account for auto-linking of phone numbers, dates, and addresses in Outlook and Apple Mail.
> Outlook Windows and Apple Mail both automatically detect phone numbers, postal addresses, and dates and convert them to interactive links, overriding your colour and text-decoration styles. Use CSS resets (`a[x-apple-data-detectors]` for Apple, inline span overrides for Outlook) to control the visual treatment. Source: Email on Acid "Outlook Auto-Link Bug"; Litmus "Apple Data Detectors".
> `detect: contextual` — check if templates containing phone numbers/addresses/dates include data-detector style resets

**[GOTCHA-014]** `transactional: venial | marketing: venial` — New Outlook for Windows (Edge renderer) applies forced dark mode colour inversion.
> The new Outlook for Windows uses Edge/Chromium rendering. In dark mode, it inverts colours without honouring `prefers-color-scheme` CSS media queries. You cannot control dark mode appearance in the new Outlook via CSS. Using off-white (`#fffffe`) reduces some unwanted inversion but is not reliable. Source: hteumeuleu/email-bugs #146; Litmus "New Outlook for Windows".
> `detect: contextual` — note in audit report; no reliable workaround; document in project

**[GOTCHA-015]** `transactional: venial | marketing: venial` — New Outlook for Windows background images may not render on initial load until zoom change.
> Background images in the new Outlook for Windows sometimes fail to render until the user manually changes the zoom level — a known regression. Source: hteumeuleu/email-bugs #146.
> `detect: contextual` — advisory; document as known limitation when background images are used

**[GOTCHA-016]** `transactional: counsel | marketing: counsel` — Apple Mail Privacy Protection makes open-rate tracking unreliable — shift to click rates.
> iOS 15+ Apple Mail pre-fetches all email content through Apple's proxy when email is downloaded, firing tracking pixels regardless of whether the user reads the email. Apple Mail represents 40–60% of email opens for consumer lists. Open rates are inflated and unreliable. There is no workaround. Source: Apple MPP (2021); Litmus "State of Email Privacy 2022".
> `detect: contextual` — advisory; verify in email.config.yml that tracking relies on click rates, not open rates

**[GOTCHA-017]** `transactional: venial | marketing: venial` — Include `a[x-apple-data-detectors]` CSS reset to prevent Apple Mail from styling auto-detected data.
> Apple Mail auto-wraps dates, phone numbers, and addresses in styled `<a>` tags that override your link colours and text-decoration. The `a[x-apple-data-detectors]` selector resets these back to your intended styles. Source: Litmus "Apple Data Detectors".
> `detect: contextual` — check if `<style>` block includes `a[x-apple-data-detectors]` reset when template contains contact information

**[GOTCHA-018]** `transactional: venial | marketing: venial` — Apple Intelligence (iOS 18+) generates AI email summaries that may override preheader text.
> Apple Intelligence generates AI-powered summaries from email body content and may display these in place of preheader text in the inbox notification. There is no metadata or header that suppresses this. Write the first full body sentence as the most important fact (e.g. "Your order #12345 has shipped") — this is what Apple Intelligence surfaces. Source: Apple iOS 18 release notes; Litmus coverage of Apple Intelligence (2024).
> `detect: contextual` — verify that email body opens with the most critical fact as the first sentence after the preheader

**[GOTCHA-019]** `transactional: venial | marketing: venial` — Yahoo Mail rewrites `@media (prefers-color-scheme: dark)` — dark mode CSS is dead in Yahoo.
> Yahoo Mail rewrites `@media (prefers-color-scheme: dark)` as `@media (_filtered_a)`, which never matches. Dark mode CSS targeted via this media query does nothing in Yahoo Mail. Use `[data-ogsb]` attribute selectors for partial Yahoo dark mode coverage. Source: hteumeuleu.com/2021/understanding-email-dark-mode; Email on Acid.
> `detect: regex` — pattern: `@media[^{]*prefers-color-scheme`

**[GOTCHA-020]** `transactional: mortal | marketing: mortal` — Do not use CSS comments in `<style>` blocks — Yahoo Mail desktop silently drops the rule after a comment.
> In Yahoo Mail desktop webmail, a CSS rule immediately following a CSS comment in a `<style>` block is silently dropped. Commenting out one rule inadvertently removes the next rule too. Source: caniemail.com/features/html-style/ (partial support caveats, last tested July 2023).
> `detect: regex` — pattern: `/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*\n\s*[a-zA-Z#.\[{]` (CSS comment followed by rule)

**[GOTCHA-021]** `transactional: venial | marketing: venial` — Do not apply CSS classes directly to `<img>` elements — Yahoo/AOL strips them.
> Yahoo Mail and AOL strip `class` attributes from `<img>` tags. CSS rules targeting `img.my-class` silently fail. Apply classes to a wrapper `<td>` or `<div>` instead. Source: hteumeuleu/email-bugs #157.
> `detect: regex` — pattern: `<img[^>]+\bclass=`

**[GOTCHA-022]** `transactional: venial | marketing: venial` — Yahoo Mail on Android removes the first `<head>` element — include a second `<head>` with styles.
> Yahoo Mail on Android strips the first `<head>` element from email HTML, including any `<style>` blocks within it. The established workaround is a second `<head>` element containing the `<style>` block — non-standard HTML that Yahoo Android honours. Source: caniemail.com/features/html-style/.
> `detect: contextual` — check if template includes a duplicate `<head>` for Yahoo Android compatibility

**[GOTCHA-023]** `transactional: mortal | marketing: mortal` — Never use SVG in email — Gmail and Outlook 2007–2019 do not support it.
> SVG images (`<img src="image.svg">` and inline `<svg>`) fail silently in Gmail (all platforms) and Outlook 2007–2019 — which together represent the majority of email volume for most senders. Use PNG or GIF exports. Serve 2× PNG for retina displays. Source: caniemail.com (SVG feature data).
> `detect: regex` — pattern: `(?:src|href)=["'][^"']*\.svg["']|<svg[\s>]`

**[GOTCHA-024]** `transactional: mortal | marketing: mortal` — Do not use CSS Custom Properties (`var()`) in email — Gmail and Outlook do not support them.
> CSS Custom Properties (`--colour: #333; color: var(--colour);`) are unsupported in Outlook 2007–2019, all Gmail platforms, and Yahoo Mail. Styles using `var()` silently fall through to no value. Pre-process variables at build time using a CSS preprocessor or build step — email templates must always receive computed flat values. Source: caniemail.com (CSS custom properties feature data).
> `detect: regex` — pattern: `var\(--[^)]+\)`

**[GOTCHA-025]** `transactional: mortal | marketing: mortal` — All `src` and `href` values must be absolute HTTPS URLs — relative URLs and `<base>` tags do not work.
> Email clients strip or ignore `<base href="...">` tags. `<img src="/images/logo.png">` fails to load. `<a href="/login">` points nowhere or to the client's own domain. Protocol-relative URLs (`//example.com/image.jpg`) behave unpredictably. Every asset reference must be an absolute `https://` URL. Source: caniemail.com (no `<base>` support); Litmus "Email Image Best Practices".
> `detect: regex` — pattern: `(?:src|href)=["'](?!https?://|mailto:|tel:|#)[^"']+["']`

**[GOTCHA-026]** `transactional: venial | marketing: venial` — Web fonts must have a complete, well-ordered fallback stack — `@font-face` fails silently in Gmail and Outlook.
> `@font-face` is unsupported in Gmail (all platforms), Outlook 2007–2019, and Yahoo Mail. When the custom font fails, the browser uses the next entry in `font-family`. A minimal fallback (`sans-serif`) resolves inconsistently across platforms — `sans-serif` maps to Times New Roman on some Windows configurations. Always provide explicit named fallbacks: `'Your Font', -apple-system, 'Segoe UI', Arial, Helvetica, sans-serif`. Source: caniemail.com/features/css-at-font-face/; Litmus "Web Fonts in Email".
> `detect: contextual` — check `font-family` declarations that include a custom font for complete fallback stacks

**[GOTCHA-027]** `transactional: venial | marketing: venial` — Style blocks are stripped when email is forwarded — inline critical styles.
> When a recipient forwards an email via Gmail or Outlook.com webmail, the `<head>` section including `<style>` blocks is stripped. Only inline styles survive. Transactional emails that are commonly forwarded (receipts, tickets, order confirmations) must have critical layout styles inlined. Source: Litmus "Email Forwarding"; Campaign Monitor.
> `detect: contextual` — check if layout-critical styles are inlined for transactional email types likely to be forwarded

**[GOTCHA-028]** `transactional: venial | marketing: venial` — Use the correct multi-property preheader hiding technique — `display: none` alone is unreliable.
> `display: none` does not reliably hide preheader text in all Outlook configurations (some preview panes show it) and some accessibility tools announce it. The correct technique combines `display: none`, `visibility: hidden`, `opacity: 0`, `max-height: 0`, `overflow: hidden`, and `mso-hide: all`. Source: Litmus "Preheader Text"; Email on Acid.
> `detect: regex` — pattern: `display\s*:\s*none(?![^}]*mso-hide)` (display:none without mso-hide companion)

**[GOTCHA-029]** `transactional: venial | marketing: venial` — Serve images at 2× resolution with `width`/`height` attributes set to display dimensions.
> High-density (Retina/HiDPI) displays render images blurry if served at 1× resolution. Serve at 2× file resolution but set HTML `width`/`height` attributes to the intended display size. If `width` is set to the file width (1200) instead of the display width (600), the image overflows its container in all clients. Outlook 2007–2019 ignores `max-width: 100%` — the `width` attribute is the only size control in Outlook. Source: Campaign Monitor "Retina Images in Email"; email_rendering_compatibility.md.
> `detect: contextual` — check if high-resolution image assets have correct `width`/`height` attributes matching display dimensions

**[GOTCHA-030]** `transactional: counsel | marketing: counsel` — Test both Gmail webmail and Gmail app — they are distinct rendering environments.
> Gmail desktop webmail (browser) and Gmail iOS/Android apps have different CSS support profiles. The app uses a native WebView renderer with differences in `@media` query handling, `@supports`, and dark mode behaviour. Screenshot testing in Litmus/Email on Acid captures webmail rendering, not app rendering. Source: Litmus "Gmail App vs Webmail"; Email on Acid testing guides.
> `detect: contextual` — advisory; verify QA matrix includes both Gmail webmail and Gmail iOS/Android app as separate test targets

---

## Patterns & Code Examples

### Gmail: background image via class, not inline style

```html
<!-- INCORRECT: Gmail strips ALL inline styles on this element -->
<td style="background-image: url(https://cdn.example.com/hero.jpg);
           padding: 40px 24px; color: #ffffff; font-family: Arial, sans-serif;">
  Hero content
</td>

<!-- CORRECT: background-image in <style> class; other styles remain inline -->
<style>
  .hero-cell { background-image: url(https://cdn.example.com/hero.jpg) !important; }
</style>
<td class="hero-cell"
    style="padding: 40px 24px; color: #ffffff; font-family: Arial, sans-serif;">
  Hero content
</td>
```

### Preheader: correct multi-property hiding

```html
<!-- CORRECT: combined hiding technique that survives Outlook preview pane -->
<!-- aria-hidden prevents screen readers announcing the hidden text -->
<div style="display: none; visibility: hidden; opacity: 0; color: transparent;
            height: 0; width: 0; font-size: 0; max-height: 0; max-width: 0;
            overflow: hidden; mso-hide: all; line-height: 0;"
     aria-hidden="true">
  Your order #12345 has shipped — arriving Friday.
  <!-- Padding characters prevent body text bleeding into preheader slot -->
  &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
</div>
```

### Apple Mail: data detector CSS reset

```html
<!-- Include in <style> block for templates containing phone/address/date content -->
<style>
  /* Prevent Apple Mail from auto-linking phone numbers, addresses, dates */
  a[x-apple-data-detectors] {
    color: inherit !important;
    text-decoration: none !important;
    font-size: inherit !important;
    font-family: inherit !important;
    font-weight: inherit !important;
    line-height: inherit !important;
  }
</style>
```

### Yahoo Android: duplicate head pattern

```html
<!-- Yahoo Mail on Android removes the first <head>; second <head> survives -->
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<head>
  <!-- Styles here survive Yahoo Android (non-standard but established workaround) -->
  <style>
    @media (max-width: 600px) {
      .mobile-full { width: 100% !important; }
    }
    /* Do NOT use CSS comments in Yahoo-targeted style blocks */
    a[x-apple-data-detectors] { color: inherit !important; }
  </style>
</head>
```

### MSO conditional comment version reference

```html
<!--[if mso]>          All Outlook versions (Word engine + new Outlook) -->
<!--[if gte mso 9]>    Outlook 2000+ (effectively all modern Outlook Windows) -->
<!--[if mso 15]>       Outlook 2013/2016/2019 (same version number) -->
<!--[if !mso]><!-->    Non-Outlook clients only (note: extra <!-- is intentional)
<!--<![endif]-->       Closes [if !mso] block (note: comment opens before the tag)

<!--
  Version reference:
  mso 12 = Outlook 2007
  mso 14 = Outlook 2010
  mso 15 = Outlook 2013, 2016, 2019 (identical version number)
  mso 16 = Outlook 2016 (some builds only — unreliable, use mso 15 instead)

  New Outlook for Windows also parses [if mso] conditionals.
  VML inside conditionals is inert in new Outlook (no-op, not harmful).
-->
```

### Retina image pattern

```html
<!-- Serve at 2× file resolution; display at 1× via width attribute -->
<!-- width attribute = display width (600), NOT file width (1200) -->
<img src="https://cdn.example.com/hero@2x.png"
     width="600" height="300"
     alt="Spring collection banner"
     style="display: block; border: 0; max-width: 100%;" />
<!--
  Outlook 2007–2019: uses width="600" attribute (ignores max-width: 100%)
  Gmail/Apple Mail/modern clients: max-width: 100% allows fluid resize on mobile
-->
```

## Support Matrix

| Feature | Gmail webmail | Gmail app | Outlook 2007–19 | Outlook new | Apple Mail | Yahoo Mail |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| `display: flex` | Google accounts only | No | No | Yes | Yes | No |
| `display: grid` | No | No | No | Yes | Yes | No |
| `min-height` | Yes | Yes | No | Yes | Yes | Yes |
| `border-radius` | Yes | Yes | No | Yes | Yes | Yes |
| `background-image` | Class only | Yes | VML only | Yes | Yes | Yes |
| CSS Custom Properties | No | No | No | Yes | Yes | No |
| `@font-face` | No | No | No | Yes | Yes | No |
| `prefers-color-scheme` | Partial | Partial | No | No* | Yes | No† |
| `<style>` block | 16KB limit | Yes | Yes | Yes | Yes | ‡ |
| SVG images | No | No | No | Yes | Yes | No |
| `<details>`/`<summary>` | No | No | No | Yes | Yes | No |

\* New Outlook inverts colours without honouring `prefers-color-scheme`.
† Yahoo rewrites the media query to a non-matching value.
‡ Yahoo desktop: CSS rule after comment is dropped. Yahoo Android: first `<head>` removed.

## Known Afflictions

**Outlook.com dark mode white background on image hover** — In Outlook.com dark mode, hovering over images causes a white background to appear behind them, exposing the cell background's absence. Transparent PNGs on dark-coloured cells are most affected.
Affects: Outlook.com (webmail) dark mode. Source: hteumeuleu/email-bugs #162.
Fix: Use images with an opaque background matching the cell background colour, not transparent PNGs, when placing on dark-coloured cells.

**Laposte/SFR comment out `<style>` tags entirely** — French email clients Laposte and SFR wrap `<style>` tags in HTML comments, stripping all CSS. Any email relying on `<style>` blocks rather than inline styles renders completely unstyled.
Affects: Laposte.net, SFR webmail. Source: hteumeuleu/email-bugs #161.
Fix: Always inline critical styles. Treat `<style>` blocks as progressive enhancement only.

**Samsung Email requires `<img>` for background images** — Samsung Email will not download or display CSS background images unless the email contains at least one `<img>` tag. Background-image-only designs with no foreground images fail silently.
Affects: Samsung Email (Android). Source: Email on Acid client testing notes.
Fix: Ensure every email template contains at least one `<img>` element.

**Outlook 365 Windows 2025 build regression** — 2025 builds of Outlook 365 on Windows have been reported to break CSS in hybrid (inline-block) layouts independently of classic Word-engine behaviour. Teams that tested against Outlook 2016/2019 may miss this regression.
Affects: Outlook 365 Windows (2025 builds). Source: hteumeuleu/email-bugs #148.
Fix: Include Outlook 365 Windows as a specific test target in QA matrix, not only legacy Outlook versions.

**`font-size: 0` zero-base inherits to `em` children** — Setting `font-size: 0` on a wrapper element (to eliminate inline-block whitespace gaps) causes any child element using `em` units for font size to render invisibly — `1em` of `0px` = `0px`.
Affects: All clients. Source: Stack Overflow `html-email`; Email on Acid.
Fix: Only use `px` units inside `font-size: 0` wrappers, and explicitly reset `font-size` on all direct children.

**AMP for Email CORS silent failure** — AMP email components that fetch data (`<amp-list>`) require CORS headers (`Access-Control-Allow-Origin: https://mail.google.com` for Gmail). Missing CORS causes the component to silently render nothing, with no error shown to the user.
Affects: Gmail AMP for Email, Yahoo AMP for Email. Source: Google AMP for Email documentation.
Fix: Verify CORS headers on all endpoints used by AMP components. Include a fallback `text/html` MIME part that is accurate for non-AMP clients.

**ESP click-tracking wraps break deep links and pre-signed URLs** — Most ESPs wrap links in redirect tracking URLs (`https://click.esp.com/track/...?u=<encoded-original>`). This breaks custom protocol deep links (`myapp://`), very long URLs that exceed proxy length limits, pre-signed S3/CDN URLs (expiry timestamp changes under the wrapper), and `mailto:` links with body/subject parameters.
Affects: All ESP click-tracking implementations. Source: SendGrid, Postmark, Mailgun click tracking documentation.
Fix: Disable click tracking for affected link types. Test custom protocol links end-to-end through your ESP. Use short clean URLs for tracked links.

## Sources

1. **hteumeuleu/email-bugs** — https://github.com/hteumeuleu/email-bugs — Issues #146 (new Outlook background), #148 (Outlook 365 regression), #152 (Gmail mobile max-width), #156 (Yahoo near-white), #157 (Yahoo img class), #158 (Outlook float), #160 (Gmail CSS Color 4), #161 (Laposte style tags), #162 (Outlook.com dark hover).
2. **caniemail.com** — https://www.caniemail.com — Feature support data for flex, custom properties, SVG, @font-face, style limits, ARIA.
3. **Litmus** — https://www.litmus.com — Gmail clipping, image caching, forwarding, preheader, dark mode, Gmail vs app, MPP.
4. **Campaign Monitor** — https://www.campaignmonitor.com/css/ — CSS support guide, retina images, responsive email patterns.
5. **Apple iOS 18 release notes** — https://developer.apple.com/news/releases/ — Apple Intelligence email summaries.
6. **hteumeuleu.com** — https://www.hteumeuleu.com — Yahoo dark mode processing, email-bugs issue commentary.
