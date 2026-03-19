# Email Gotchas, Edge Cases & Sneaky Behaviours

Production war stories. The non-obvious traps. The things that bite you in staging but only manifest in a specific client at 2am.

Last compiled: 2026-03-18. Live source verification performed against caniemail.com, github.com/hteumeuleu/email-bugs, rfc-editor.org, and support.google.com/mail on this date.

---

## Client-Specific Bugs & Traps

### Gmail

**The 102KB HTML clip**
Gmail clips the entire email body when the HTML payload exceeds 102,400 bytes, replacing the remainder with a "View entire message" link. The clip point is mid-document — not end-of-document — so the email appears to end abruptly wherever the 102KB boundary falls. Inline CSS is the primary offender (every style repeated per-element inflates size rapidly).

Fix: Keep HTML under 80KB as a safe margin. Audit with `wc -c` on the rendered output. Strip comments, minify whitespace, and use `<style>` blocks where clients support them.

Source: Litmus "Gmail Clipping"; caniemail.com.

---

**The `<style>` block 16KB limit**
Separate from the 102KB HTML clip: Gmail limits `<style>` tags to approximately 16KB. Content exceeding this is silently stripped. The rest of the email renders without those styles, often catastrophically.

Fix: Keep your `<style>` block lean. Audit it. If you're near the limit, inline critical layout properties.

Source: caniemail.com/features/html-style/ (confirmed 16KB cap, last tested July 2023); hteumeuleu email-bugs.

---

**`url()` strips ALL inline styles on that element**
If a Gmail webmail desktop `style` attribute (inline style) contains a `background-image: url(...)` or any other `url()` function, Gmail strips the **entire `style` attribute** from that element — not just the `url()` property. Every other inline style on the same element disappears.

```html
<!-- This loses ALL inline styles in Gmail desktop webmail -->
<td style="background-image: url(hero.jpg); padding: 24px; color: #333;">

<!-- Fix: move background-image to a <style> block class -->
<style>.hero-cell { background-image: url(hero.jpg); }</style>
<td class="hero-cell" style="padding: 24px; color: #333;">
```

Fix: Never use `url()` in inline styles. Apply background images via `<style>` block classes only.

Source: caniemail.com/features/css-background-image/ (verified 2026-03-17).

---

**Gmail removes styles using whitespace colour syntax (added from live research)**
Gmail strips entire style rules that use the modern whitespace-separated colour syntax introduced in CSS Color Level 4. The affected syntax: `rgba(0 128 0 / 0.5)` and `rgb(0 128 0)` (no commas). Gmail only accepts the legacy comma-separated syntax.

```css
/* BREAKS in Gmail — whitespace syntax */
color: rgb(51 51 51);
background-color: rgba(0 0 0 / 0.5);

/* SAFE — comma syntax */
color: rgb(51, 51, 51);
background-color: rgba(0, 0, 0, 0.5);
```

This was documented as a regression in gmail rendering (hteumeuleu/email-bugs issue #160, 2025).

Fix: Always use comma-separated RGB/RGBA syntax in email styles.

Source: hteumeuleu/email-bugs #160 (github.com/hteumeuleu/email-bugs/issues/160).

---

**Gmail image caching is permanent by URL**
Gmail proxies and caches images via `googleusercontent.com` after the first send. The cache key is the original URL. If you update the image at the same URL, **Gmail continues serving the old version indefinitely** — there is no TTL, no cache-busting header that helps.

Fix: Always version image URLs. Append a query string or change the filename for every new version: `logo.png?v=2` or `logo-v2.png`.

Source: Litmus "Gmail Image Caching"; Stack Overflow discussion (repeated community reports).

---

**Gmail CSS class name prefixing**
Gmail rewrites CSS class names in `<style>` blocks by prefixing them (e.g. `.button` becomes `.m_-1234567890button`). This breaks any JavaScript-based class manipulation (which shouldn't be in email anyway) and can interfere with complex cascade rules if you rely on class specificity matching.

Fix: Be aware, but it rarely requires a fix. Don't rely on class names in non-Gmail-aware tooling for email.

Source: hteumeuleu.com; Stack Overflow `html-email` tag.

---

**Gmail `id` attribute prefixing**
Gmail prefixes `id` attributes with a hash to prevent collisions with the surrounding webmail DOM. This breaks `aria-labelledby`, `aria-describedby`, `<label for="...">`, and any fragment anchors (`#section-name`).

Fix: Do not use `id`-based references for anything functional in email. Use `aria-label` instead of `aria-labelledby`. Never use fragment anchors for in-email navigation.

Source: caniemail.com/features/html-aria-labelledby/; caniemail.com/features/html-aria-describedby/.

---

**Gmail mobile webmail does not support `max-width: 100%` on images (added from live research)**
Gmail's mobile webmail (the responsive web view, not the native app) does not honour `max-width: 100%` on `<img>` elements. Images wider than their container overflow rather than shrink. This is a separate rendering context from both Gmail desktop webmail and the Gmail native app.

Fix: Set explicit pixel `width` attributes on images for Gmail mobile webmail. Use `max-width: 100%` only as a progressive enhancement layered on top.

Source: hteumeuleu/email-bugs #152 (github.com/hteumeuleu/email-bugs/issues/152).

---

**Gmail does not support `display: flex` with non-Google accounts (added from live research)**
On Gmail desktop webmail, `display: flex` is supported — but **only when the recipient uses a Google account** (gmail.com, Google Workspace). Users accessing Gmail webmail with a non-Google account (e.g. a company account hosted elsewhere but using Gmail's interface) do not get flex support. The same restriction applies to `:hover` pseudo-class support in Gmail.

Fix: Do not use flexbox for structural layout in Gmail-targeted emails. Use table-based layout with flex as an enhancement only.

Source: caniemail.com/features/css-display-flex/ (verified 2026-03-18); caniemail.com/features/css-pseudo-class-hover/.

---

### Outlook Windows 2007–2019 (Word Rendering Engine)

**The Word engine — the root of most pain**
Outlook 2007–2019 on Windows renders HTML using Microsoft Word's layout engine, not a browser. This means CSS is interpreted by a word processor, not a rendering engine. Most modern CSS simply does not exist in this context.

caniemail.com score for Outlook Windows: 59/302 — the lowest of all actively used clients.

---

**`min-height` does nothing**
Outlook Windows ignores `min-height`. A container you expect to grow to at least 200px will collapse to fit its content.

Fix: Use a transparent spacer image or VML to enforce minimum heights:
```html
<!--[if mso]>
<v:rect style="width:600px; height:200px;" stroke="f" fillcolor="#ffffff">
  <v:textbox inset="0,0,0,0"><![endif]-->
  <!-- content here -->
<!--[if mso]></v:textbox></v:rect><![endif]-->
```

Source: Campaign Monitor CSS support guide; Litmus Outlook rendering notes.

---

**`line-height` is not inherited from `<td>`**
Setting `line-height` on a `<td>` does not propagate to text inside it in Outlook Windows. You must set it directly on the element containing the text, or use `mso-line-height-rule: exactly` to prevent Outlook inflating it.

```html
<!-- Outlook will inflate line-height unless mso-line-height-rule: exactly is set -->
<p style="line-height: 24px; mso-line-height-rule: exactly;">
  Text here
</p>
```

Without `mso-line-height-rule: exactly`, Outlook uses "at least" semantics and adds extra spacing.

Source: Litmus "Outlook Line Height Bug"; Email on Acid.

---

**Padding on `<p>` and `<div>` is unreliable**
Outlook Windows applies padding inconsistently on block elements. Use `<td>` padding instead. Never rely on `<p>` margin or padding for spacing in Outlook — use empty `<tr>` rows with height, or spacer cells.

```html
<!-- Reliable spacing in Outlook -->
<tr><td height="16" style="font-size:0; line-height:0;">&nbsp;</td></tr>
```

Source: Campaign Monitor; Stack Overflow `html-email` discussions.

---

**`border-radius` not supported**
Outlook 2007–2019 ignores `border-radius`. Rounded buttons look square. Use VML roundrect for the Outlook version.

Source: caniemail.com/features/css-border-radius/.

---

**Auto-linking phone numbers, addresses, and dates**
Outlook (and Apple Mail — see below) automatically detects phone numbers, postal addresses, and dates and turns them into hyperlinks. This changes colour, adds underline, and overrides your link styles.

Fix for Outlook:
```html
<!-- Wrap in a span with no-link styling — partial fix -->
<span style="color: #333333; text-decoration: none;">+44 20 7946 0000</span>
```
More reliable: use MSO-specific `w:` markup or accept it as a known limitation.

Source: Stack Overflow; Email on Acid "Outlook Auto-Link Bug".

---

**`z-index` does not work**
Outlook Windows does not support `z-index`. Overlapping elements (e.g. positioned badges, ribbons) will not stack correctly.

Fix: Redesign overlapping elements as non-overlapping, or accept that the design degrades in Outlook.

Source: caniemail.com/features/css-z-index/.

---

**Gaps below images**
Outlook (and some other clients) render a gap below `<img>` elements because images are treated as inline elements with a text baseline. This creates 4–5px gaps in table-based layouts.

Fix:
```html
<img src="..." style="display: block; border: 0;" />
```
Always set `display: block` and `border: 0` on images inside table cells.

Source: Campaign Monitor "Image Gap Bug"; Litmus.

---

**List margins inflated**
Outlook adds extra left margin to `<ul>` and `<ol>` beyond what you specify.

Fix:
```html
<!--[if mso]>
<style>ul, ol { margin-left: 20px !important; }</style>
<![endif]-->
```

Source: Email on Acid; Stack Overflow.

---

**Text crops after floating tables in coloured table backgrounds (added from live research)**
In Outlook Windows, when a table with `float` styling is placed inside a `<td>` with a background colour, text content following the floated table is cropped and not displayed. This is a known Word-engine rendering defect.

Fix: Do not use `float` in Outlook-targeted content. Use MSO conditional tables for all multi-column layouts.

Source: hteumeuleu/email-bugs #158 (github.com/hteumeuleu/email-bugs/issues/158).

---

**Outlook 365 (Windows, 2025 builds) ignoring CSS in hybrid layouts (added from live research)**
Outlook 365 on Windows in 2025 builds has been reported to ignore CSS and break hybrid (inline-block) email layouts even when MSO conditional comments are properly applied. This appears to be a regression in specific Windows 365 App builds. The issue is distinct from the legacy Word-engine behaviour.

This is particularly treacherous because teams that have tested against Outlook 2016/2019 may not notice the regression in 365 builds.

Fix: Include Outlook 365 on Windows as a specific test target, not just legacy Outlook. Monitor hteumeuleu/email-bugs for updates.

Source: hteumeuleu/email-bugs #148 (github.com/hteumeuleu/email-bugs/issues/148).

---

**MSO conditional comment targeting**

Understanding the variants:
```html
<!--[if mso]>           targets ALL Outlook versions (Word engine) -->
<!--[if gte mso 9]>     targets Outlook 2000+ (effectively all modern Outlook) -->
<!--[if mso 16]>        targets Outlook 2016 only -->
<!--[if !mso]><!-->     targets everything EXCEPT Outlook (note the unusual syntax) -->
<!--<![endif]-->        closes the !mso block (note: the comment opens BEFORE the tag) -->
```

The `<!--[if !mso]><!-->` pattern is the most mistyped. The extra `<!--` after `>` is intentional — it starts a regular HTML comment that Outlook (which processed the conditional) closes, while non-Outlook clients see it as an opening comment that the `-->` on the last line closes.

**Version number reference:**
```
mso 12 = Outlook 2007
mso 14 = Outlook 2010
mso 15 = Outlook 2013, 2016, 2019
mso 16 = Outlook 2016 (some builds) — use with caution, not universally reliable
```

Note: MSO conditional comments are also parsed by the new Outlook for Windows (Edge renderer). Existing conditionals do not break the new Outlook, but VML inside conditionals is no longer required for most layout needs in the new Outlook.

Source: Campaign Monitor; Litmus Boilerplate (github.com/leemunroe/responsive-html-email-template).

---

### New Outlook for Windows (Edge/Chromium Renderer, 2021+)

**The new Outlook is NOT the Word-engine Outlook — but it has its own gotchas (added from live research)**
Microsoft's new Outlook for Windows uses an Edge/Chromium-based renderer. This resolves most Word-engine limitations (`border-radius`, `background-image`, `max-width`, `display: flex`, CSS Grid all work). However, the new Outlook introduces its own rendering issues:

- **Forced dark mode colour inversion**: The new Outlook inverts colours in dark mode without honouring `prefers-color-scheme`. You cannot use CSS media queries to control dark mode appearance in the new Outlook. Use off-white (`#fffffe`) instead of pure white to reduce unwanted inversion on some elements.
- **Background image collapse until zoom change**: Background images sometimes do not render on initial load and only appear after the user changes the zoom level. This is a known regression (hteumeuleu/email-bugs #146).
- **MSO conditional comments still parsed**: `<!--[if mso]>` blocks are still processed. This means legacy VML inside conditionals is still inert (not harmful), but VML-only approaches no longer serve the new Outlook's rendering context.

**Adoption caution**: As of 2026, enterprises with volume Microsoft 365 licensing often remain on Outlook 2016/2019 via perpetual licence. Do not assume new Outlook adoption is universal in B2B audiences — continue supporting the Word engine.

Source: hteumeuleu/email-bugs #146, #148; Litmus "New Outlook for Windows" coverage; caniemail.com rendering data.

---

### Apple Mail

**Mail Privacy Protection (MPP) — tracking pixels are dead**
Apple MPP (iOS 15+, macOS Monterey+) pre-fetches all email content — including images — through Apple's proxy servers when the email is downloaded, not when the user opens it. This means:
- **Open tracking pixels fire immediately on download**, not on open
- All email opens from Apple Mail appear as opens, regardless of whether the user actually read the email
- Open rates from Apple Mail are inflated and unreliable as an engagement metric
- The user's real IP address and device are never sent to your image server

Fix: Do not rely on open rates from Apple Mail for engagement decisions. Use click rates as the primary engagement signal. There is no technical workaround.

Source: Apple MPP announcement (2021); Litmus "Mail Privacy Protection Impact"; Campaign Monitor.

---

**Auto data detectors (dates, addresses, phone numbers become links)**
Apple Mail auto-detects dates ("Thursday 20 March"), times, addresses, and phone numbers and wraps them in interactive `<a>` tags. These override your link styles and add unwanted interactivity.

Fix:
```html
<!-- CSS reset for Apple data detectors -->
<style>
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

Or suppress on specific elements:
```html
<a href="#" x-apple-data-detectors="false" style="color: #333; text-decoration: none;">
  +44 20 7946 0000
</a>
```

Source: Litmus "Apple Data Detectors"; Campaign Monitor.

---

**Apple Mail dark mode forced colour inversion**
Apple Mail in dark mode uses two strategies:
1. **Honour `prefers-color-scheme: dark`** — if you have explicit dark mode CSS, it uses it.
2. **Force colour inversion** on elements without dark mode CSS — white backgrounds become dark, dark text becomes light.

The trap: partial dark mode support. If you provide dark mode CSS for some elements but not others, Apple Mail inverts the unspecified elements while honouring your explicit overrides on others. This creates mismatched colour combinations.

Fix: Either provide complete dark mode CSS for all elements, or use `color-scheme: light` meta tag to opt out entirely:
```html
<meta name="color-scheme" content="light" />
<meta name="supported-color-schemes" content="light" />
```

Source: Litmus "Dark Mode Email Design"; hteumeuleu.com.

---

**Apple Intelligence email summaries (added from live research)**
iOS 18 and macOS Sequoia introduced Apple Intelligence, which generates AI-powered summaries of email content. These summaries appear in the inbox notification and in the email list view — replacing or supplementing the preheader text. The summary is generated from the email body, not the preheader, and Apple Intelligence cannot be suppressed by the sender.

Implications:
- Your carefully crafted preheader text may be overridden by an AI-generated summary in the notification
- Summaries may omit or misrepresent nuanced transactional content (e.g. summarising "Your password was reset" might omit the urgency context)
- There is no metadata or header that suppresses Apple Intelligence summarisation

Fix: Write email body copy that reads coherently and accurately when summarised. Lead with the most important fact (order confirmed, password reset, payment failed) as the first full sentence after the preheader — this is what Apple Intelligence is most likely to surface.

Source: Apple iOS 18 release notes; Litmus coverage of Apple Intelligence (2024); hteumeuleu/email-bugs TODO list.

---

### Outlook.com (Hotmail)

**Aggressive CSS property stripping**
Outlook.com strips many CSS properties it considers unsafe or unsupported. Properties that work in desktop Outlook 365 may be stripped in Outlook.com webmail. Always test both.

Notable strips: `position`, `z-index`, `float`, `overflow`, certain `background` shorthand properties.

Source: caniemail.com; hteumeuleu email-bugs repo.

---

**`id` prefixing (same as Gmail)**
Outlook.com also prefixes `id` attributes, breaking ARIA cross-references and fragment anchors.

Source: caniemail.com/features/html-aria-describedby/.

---

**Outlook.com dark mode adds white background behind images on hover (added from live research)**
In Outlook.com's dark mode, hovering over images causes a white background to appear behind them. This is particularly damaging for transparent PNG images (logos, icons) that are placed on dark-coloured table cell backgrounds — on hover, the cell background vanishes and a white box appears behind the image.

Fix: For images placed on dark backgrounds in Outlook.com, avoid transparent PNGs. Use images with an opaque background colour matching the cell background.

Source: hteumeuleu/email-bugs #162 (github.com/hteumeuleu/email-bugs/issues/162).

---

### Yahoo Mail / AOL

**`@media` query rewriting**
Yahoo Mail rewrites `@media` queries — specifically, it rewrites `@media (prefers-color-scheme: dark)` as `@media (_filtered_a)`, which never matches. Dark mode CSS in Yahoo Mail is effectively dead.

Fix: Do not rely on `prefers-color-scheme` for Yahoo Mail. Design for light mode as the baseline. Use `[data-ogsb]` attribute selectors as a partial Yahoo dark mode workaround (targets Yahoo's dark mode class on `<body>`):
```css
[data-ogsb] .my-element { background-color: #1a1a1a !important; }
```

Source: hteumeuleu.com/2021/understanding-email-dark-mode; Email on Acid.

---

**Yahoo dark mode strongly alters near-white colours (added from live research)**
Yahoo Mail's dark mode processing strongly alters colours in the near-white range, including `#fffffe` (the off-white value commonly recommended as a "dark mode inversion escape hatch"). Do not rely on `#fffffe` as a Yahoo dark mode bypass — it is altered just as aggressively as `#ffffff` in Yahoo.

Source: hteumeuleu/email-bugs #156 (github.com/hteumeuleu/email-bugs/issues/156).

---

**Yahoo/AOL do not support `class` on `<img>` elements (added from live research)**
Yahoo Mail and AOL strip `class` attributes from `<img>` tags. CSS rules targeting `img.my-class` will not apply. Any responsive or dark-mode image swapping that relies on class selectors on `<img>` elements silently fails in these clients.

Fix: Apply image classes to a wrapper `<td>` or `<div>` instead of directly on the `<img>` tag when Yahoo/AOL support is required.

Source: hteumeuleu/email-bugs #157 (github.com/hteumeuleu/email-bugs/issues/157).

---

**Yahoo Mail Desktop Webmail: CSS rule after a comment is ignored (added from live research)**
In Yahoo Mail desktop webmail, a CSS rule that immediately follows a CSS comment in a `<style>` block is silently dropped. This means commenting out a rule in your `<style>` block inadvertently kills the next rule too.

```css
/* This comment causes the next rule to be silently dropped in Yahoo Mail desktop */
/* .some-class { color: red; } */
.the-next-rule { color: blue; } /* This rule is lost in Yahoo Mail desktop webmail */
```

Fix: Do not use CSS comments in `<style>` blocks, or ensure there is always a non-commented rule before any rule you care about after a comment block.

Source: caniemail.com/features/html-style/ (noted in partial support caveats, last tested July 2023).

---

**Yahoo Mail Android removes the first `<head>` element (added from live research)**
Yahoo Mail on Android removes the first `<head>` element in the HTML, including any `<style>` blocks it contains. The workaround is to include a duplicate `<head>` element — Yahoo removes the first but leaves the second.

```html
<!-- Yahoo Mail Android: include styles in a second <head> -->
<head><style>/* first head — Yahoo Android removes this */</style></head>
<head><style>/* second head — survives in Yahoo Android */</style></head>
```

This is non-standard HTML but is the established workaround.

Fix: Put your `<style>` block in a second `<head>` element, or inline all critical styles.

Source: caniemail.com/features/html-style/ (noted in partial support caveats, last tested July 2023).

---

### Laposte / SFR (French Email Clients)

**Style tags commented out entirely (added from live research)**
The French email clients Laposte and SFR comment out `<style>` tags in the document `<head>`, effectively stripping all CSS. Any email that relies on `<style>` blocks rather than inline styles renders completely unstyled in these clients.

Fix: Always inline critical styles. Treat `<style>` blocks as progressive enhancement. This is also the correct defensive posture for all webmail clients.

Source: hteumeuleu/email-bugs #161 (github.com/hteumeuleu/email-bugs/issues/161).

---

### Samsung Email

**Older WebKit rendering**
Samsung Email on Android uses a WebKit-based renderer that lags behind current WebKit/Blink. Some flex and grid properties that work in Gmail app (which uses Chrome WebView) do not work in Samsung Email.

Fix: Test on Samsung Email specifically if you have significant Android non-Gmail traffic. It frequently surprises engineers who tested only Gmail on Android.

**Background images require at least one `<img>` element**
Samsung Email requires that the email contains at least one `<img>` element before it will download and display background images. An email with only CSS background images and no `<img>` tags will show no background images.

Source: caniemail.com; Email on Acid client testing notes.

---

## The Non-Obvious Traps

### Email Forwarding Breaks Style Blocks

When a recipient forwards an email via a webmail client (Gmail, Outlook.com), the `<head>` section — including `<style>` blocks — is typically stripped. Only inline styles survive. The forwarded version of your beautifully styled email may be completely unstyled.

This is especially problematic for:
- Layouts that rely on media queries (the `<style>` block with `@media` is gone — the mobile layout disappears)
- Dark mode CSS
- Reset styles that compensate for client defaults

Fix: Always inline critical layout styles. Use `<style>` blocks as enhancement only, not as the primary layout mechanism for transactional emails that are likely to be forwarded (receipts, tickets, etc.).

Source: Litmus "Email Forwarding"; Campaign Monitor.

---

### The 600px Convention — Why It Exists

The email industry standard of max 600px width exists because of Outlook's 3-pane preview panel, not mobile. The right-side preview pane in classic Outlook leaves approximately 600px of width. Emails wider than 600px require horizontal scrolling in the preview pane.

Mobile consideration is a separate reason to stay at 600px (or use fluid layouts that go narrower), but the original reason is Outlook desktop.

Source: Campaign Monitor "Email Design Guide"; Litmus "Email Width".

---

### `display: none` Is Not Reliable

Using `display: none` to hide content (e.g. preheader text) does not reliably hide it everywhere:
- Some Outlook configurations show `display: none` content in the preview pane
- Some accessibility tools read it
- Some older mobile clients ignore it

The correct preheader hiding technique combines multiple approaches:
```html
<span style="display:none; visibility:hidden; opacity:0; color:transparent;
             height:0; width:0; font-size:0; max-height:0; max-width:0;
             overflow:hidden; mso-hide:all; line-height:0;">
  Preheader text here &#847; &zwnj; &nbsp; &#847; &zwnj; &nbsp;
  (padding characters to prevent next content showing as preheader)
</span>
```

The `&#847;` (word joiner) and `&zwnj;` padding prevents the email body content from appearing in the preheader slot after the preheader text ends.

Source: Litmus "Preheader Text"; Email on Acid.

---

### The Ghost Table Whitespace Trap

Ghost tables (MSO conditional table wrappers for multi-column layouts) require that the closing `</div>` of column 1 and the MSO conditional comment for column 2 have **no whitespace between them**. Any whitespace character between inline-block elements creates a 4px gap.

```html
<!-- WRONG: gap between columns because of newline/indent -->
<div style="display:inline-block; width:280px;">
  Column 1 content
</div>
<!--[if mso]></td><td width="280"><![endif]-->
<div style="display:inline-block; width:280px;">

<!-- CORRECT: no whitespace between closing div and conditional comment -->
<div style="display:inline-block; width:280px;">
  Column 1 content
</div><!--[if mso]></td><td width="280"><![endif]--><div style="display:inline-block; width:280px;">
```

This is one of the most common multi-column layout bugs in email. The gap appears in Gmail/Apple Mail (inline-block gap), not Outlook (which uses the MSO table cells).

Source: Campaign Monitor "Responsive Email"; Litmus Boilerplate.

---

### Reply-To vs From and DMARC Alignment

DMARC alignment checks the **From** header domain against your SPF/DKIM domain. The **Reply-To** header is irrelevant to DMARC.

The trap: if you send via an ESP (Mailgun, SendGrid, etc.) and your `From` domain is `yourcompany.com` but the ESP sends from `em.sendgrid.net`, you need either:
- **DKIM alignment**: ESP signs with a key for `yourcompany.com` (requires DNS record delegation to the ESP)
- **SPF alignment**: `yourcompany.com` SPF record includes the ESP's sending IPs

If neither is configured, DMARC fails even though the email delivers — because DMARC policy may be `none` (monitoring only) and many engineers don't notice until they tighten to `quarantine` or `reject`.

Fix: Always configure DKIM signing for your `From` domain through your ESP. Do not rely on SPF alignment alone.

Source: RFC 7489 (DMARC); Google Sender Guidelines 2024.

---

### Subdomain DMARC Alignment Trap

DMARC has a `aspf` and `adkim` alignment mode: `relaxed` (default) or `strict`.

In **relaxed** mode: `mail.yourcompany.com` passes DMARC for `yourcompany.com` (subdomain matches organisational domain).

In **strict** mode: `mail.yourcompany.com` **fails** DMARC for `yourcompany.com` (exact domain match required).

Many engineers set `p=reject` and `adkim=s` (strict) without realising their ESP sends from a subdomain. All mail silently fails DMARC.

Fix: Use `adkim=r` (relaxed) unless you have a specific reason for strict. Audit your sending domains before tightening DMARC policy.

Source: RFC 7489; dmarc.org/overview/.

---

### ESP Link Wrapping Breaks Custom Protocols and Long URLs

Most ESPs wrap links in click-tracking redirects (e.g. `https://click.mailchimp.com/track/click/...?u=<encoded-original-url>`). This causes problems with:

- **Deep links and custom protocol URLs** (`myapp://open?token=abc`) — many ESPs cannot wrap these, or the redirect chain breaks the protocol
- **Very long URLs** — some ESP wrappers + encoded original URL exceed HTTP URL length limits (2,048 chars in some proxies)
- **Pre-signed S3/CDN URLs** — the expiry timestamp in the URL means the wrapped link expires
- **`mailto:` links with body/subject parameters** — wrappers break the mailto construction

Fix: Disable click tracking for affected links, or use short/clean URLs. Test custom protocol links end-to-end through your ESP.

Source: ESP documentation (SendGrid, Postmark, Mailgun click tracking docs); community reports.

---

### Relative URLs and `<base>` Tags Do Not Work in Email (added from live research)

Email clients strip or ignore `<base href="...">` tags and do not resolve relative URLs. Every `src` and `href` attribute in an email must be an absolute URL with full scheme and hostname.

Specific failure modes:
- `<base href="https://example.com/">` — stripped by Gmail, Outlook.com, and most webmail clients
- `<img src="/images/logo.png">` — the image simply fails to load; no fallback mechanism
- `<a href="/login">` — the link becomes non-functional or points to the client's own domain in some clients
- Protocol-relative URLs (`//example.com/image.jpg`) — unreliable; some clients do not inherit the correct protocol

Fix: Always use `https://` absolute URLs for every `src` and `href`. Run a linting step in your build pipeline that flags any relative URL in email templates.

Source: Email community research; caniemail.com (no `<base>` support documented across clients); Litmus "Email Image Best Practices".

---

### The "Works in Gmail Webmail, Breaks in Gmail App" Distinction

Gmail webmail (browser) and Gmail app (iOS/Android) are different rendering environments:
- Webmail: runs in Chrome/Firefox/Safari — good CSS support, `<style>` blocks supported
- Gmail iOS/Android app: uses a native WebView renderer — some CSS behaves differently, especially with `@media` queries

Specific known differences:
- Gmail app on iOS ignores some `@supports` queries
- Gmail app on Android has historically had issues with `width: 100%` on outer containers
- Dark mode behaviour differs between webmail and app

Fix: Always test both webmail and app environments in your QA matrix.

Source: Litmus "Gmail App vs Webmail"; Email on Acid testing guides.

---

### Screenshot Testing Misses Runtime Failures

Tools like Litmus and Email on Acid capture screenshots of rendered emails. Screenshots do not capture:
- Dark mode rendering (most tools show light mode only, or require explicit dark mode captures)
- Interactive states (`:hover`, `:focus`)
- Dynamic content rendering failures (Handlebars/Liquid rendering errors that produce empty sections)
- Load failures for externally hosted images (a broken image URL shows the alt text, not the image)
- The 102KB Gmail clip — the screenshot tool may render the full email even if Gmail would clip it

Fix: Treat screenshot testing as a visual layout check only. Test dynamic content with real send-and-receive tests. Check HTML size before testing.

Source: Email on Acid "Limitations of Screenshot Testing"; Litmus documentation.

---

### Apple MPP Makes Open Rates Useless as Engagement Signal

As of iOS 15 (September 2021), Apple Mail pre-fetches all email content including tracking pixels via Apple's proxy. This means:
- Every Apple Mail open registers as an open, whether the user read it or not
- Apple Mail accounts for 40–60% of email opens depending on your list
- "Open rate" as a deliverability health signal is now partially corrupted
- Spam filter warmup sequences that use open rates to prove engagement are affected

This is not a rendering bug — it is a deliberate privacy feature. There is no workaround.

Fix: Shift engagement measurement to **clicks** as the primary metric. Use click rate for list hygiene. Do not rely on open rates for suppression decisions on Apple Mail users.

Source: Apple MPP (developer.apple.com, 2021); Litmus "State of Email Privacy 2022".

---

### The `text/plain` Part Is Read by Spam Filters

The `text/plain` MIME part in your multipart/alternative email is read by spam filters, not just the `text/html` part. A minimal or auto-generated plain text version (e.g. "This email requires HTML") is a spam signal. A missing plain text part entirely is a stronger spam signal.

The plain text version should:
- Contain the same core content as the HTML version
- Be coherent and readable as a standalone email
- Include the unsubscribe URL as plain text

Fix: Generate a real plain text version from your HTML, or write one manually for critical transactional templates.

Source: SpamAssassin rule documentation; Postmark deliverability guide.

---

### `font-size: 0` Trick Has Side Effects

Setting `font-size: 0` on a wrapper element (to eliminate inline-block whitespace gaps without changing HTML) suppresses the gap — but it also sets the font size to 0 for all descendants that use `em` units. Any child element with `font-size: 1em` inherits the 0px base and renders invisibly.

Fix: Always reset `font-size` explicitly on children inside a `font-size: 0` wrapper, and only use `px` units inside such wrappers.

Source: Stack Overflow `html-email`; Email on Acid.

---

### SVG Is Not Safe in Email (added from live research)

SVG images (`<img src="image.svg">` and inline `<svg>`) are not reliably supported across email clients:

| Client | SVG support |
|---|---|
| Apple Mail / iOS Mail | Supported |
| New Outlook (Edge renderer) | Supported |
| Outlook 2007–2019 (Word engine) | Not supported |
| Gmail (all platforms) | Not supported |
| Yahoo Mail | Not supported |

Gmail and Outlook Windows — the two most problematic email clients — both do not support SVG. This means SVG is only safe for audiences where you can guarantee no Gmail or legacy Outlook users exist (essentially: never).

Fix: Export all email images as PNG or GIF. For icons and logos, provide 2× PNG exports for retina displays. Never use SVG in email.

Source: caniemail.com (SVG feature data); email_rendering_compatibility.md feature matrix.

---

### CSS Custom Properties (Variables) Are Not Safe in Email (added from live research)

CSS Custom Properties (`--my-colour: #333; color: var(--my-colour);`) are not supported in the email clients that matter most for cross-client compatibility:

- Outlook 2007–2019: Not supported (Word engine has no CSS variable concept)
- Gmail (all platforms): Not supported
- Yahoo Mail: Not supported

CSS variables work in Apple Mail, iOS Mail, and modern WebKit-based clients, but this is insufficient for cross-client email. Any style system built on CSS variables will silently fail for a significant portion of recipients.

Fix: Do not use CSS Custom Properties in email HTML. Pre-process variables at build time (using SCSS, Less, or a build step) and output flat CSS values. Email should always receive computed values, never variable references.

Source: caniemail.com (CSS custom properties feature data); campaign monitor CSS support data.

---

### Web Fonts (`@font-face`) Gotchas

`@font-face` has partial support across email clients. The critical clients that **do not** support it:

- Outlook 2007–2019 (Word engine): not supported
- Gmail (all platforms): not supported
- Yahoo Mail / AOL: not supported

Clients that **do** support it: Apple Mail, iOS Mail, Outlook for Mac, Samsung Email, Thunderbird, ProtonMail.

The trap: web fonts fail silently. When `@font-face` is unsupported, the browser falls back to the next font in the `font-family` stack. If your fallback stack is poorly ordered, you get an unexpected system font.

**Font fallback ordering gotcha**: The order of fonts in the fallback stack matters on every platform. The system font name varies:
```css
font-family: 'YourCustomFont', -apple-system, BlinkMacSystemFont,
             'Segoe UI', Arial, Helvetica, sans-serif;
```
- `-apple-system` selects San Francisco on macOS/iOS
- `BlinkMacSystemFont` selects San Francisco in Chrome on macOS
- `'Segoe UI'` selects the Windows system font
- `Arial` / `Helvetica` are the reliable universal fallbacks

If you list only `'YourCustomFont', sans-serif`, the `sans-serif` generic resolves to different fonts on different platforms (Times New Roman on some Windows configurations before Arial is tried, for example).

Fix: Always provide a complete font stack. Test with the custom font disabled to verify the fallback renders acceptably.

Source: Litmus "Web Fonts in Email"; caniemail.com/features/css-at-font-face/; Campaign Monitor CSS support guide.

---

### Retina / HiDPI Image Gotchas (added from live research)

High-density displays (Retina on Apple devices, most modern Android flagships) render images at 2× or 3× density. If you serve a 600px-wide image at an actual resolution of 600px, it appears blurry on retina displays.

**The pattern:**
```html
<!-- Serve at 2× actual resolution, display at 1× size -->
<img src="hero@2x.png" width="600" height="300" alt="Hero" style="max-width: 100%;" />
```

**Gotchas:**
- The `width` HTML attribute must be set to the **display** width (600), not the image file width (1200). If you omit `width` or set it to 1200, the image renders at 1200px wide and overflows its container in all clients.
- Outlook 2007–2019 ignores `max-width: 100%` — use only the `width` attribute to control image size in Outlook. This means the image renders at the attribute width (600px) in Outlook, which is correct.
- Do not serve 3× images as a default — the file size increase is significant and the perceived quality improvement over 2× is minimal on most devices.
- Samsung Email requires at least one `<img>` in the email for background images to download — but retina foreground images work normally.

Fix: Serve all images at 2× dimensions with `width` and `height` attributes set to the intended display dimensions. Keep file sizes manageable with compression (use tools like ImageOptim or Squoosh).

Source: Campaign Monitor "Retina Images in Email"; Litmus "Email Image Best Practices"; email_rendering_compatibility.md.

---

### `<details>` / `<summary>` — Interactive Elements in Email (added from live research)

The HTML `<details>` and `<summary>` elements (native accordion/disclosure widgets) have very limited email support:

| Client | Support |
|---|---|
| Apple Mail / iOS Mail | Supported |
| New Outlook (Edge renderer) | Supported |
| Outlook 2007–2019 | Not supported (falls back to open state — all content visible) |
| Gmail | Not supported |
| Yahoo Mail | Not supported |

In clients that do not support `<details>`, the content inside is not hidden — it is simply displayed as static, open content. This means the accordion "collapses to open", which is acceptable if your fallback design accounts for it.

Fix: Use `<details>`/`<summary>` only where always-visible fallback content is acceptable. Do not use it to hide content that must be hidden (e.g. do not use it as an unsubscribe confirmation gate). If you use it, test the open-state fallback carefully.

Source: caniemail.com (html-details feature); email_rendering_compatibility.md feature matrix.

---

### AMP for Email — The Invisible Failure Mode (added from live research)

AMP for Email (`text/x-amp-html` MIME part) is supported in Gmail and Yahoo Mail. It allows interactive email components (carousels, forms, real-time data). However, the failure mode is opaque:

- **CORS requirements**: AMP email components that fetch data (`<amp-list>`) require your endpoints to respond with `Access-Control-Allow-Origin: https://mail.google.com` (for Gmail). Missing CORS headers cause the AMP component to silently fail and show nothing.
- **Required fallback MIME part**: Gmail requires the email to include a standard `text/html` MIME part alongside the AMP part. Users on clients that do not support AMP (Outlook, Apple Mail) see the `text/html` fallback. If your AMP and HTML parts are out of sync in content, users see different emails.
- **AMP cache invalidation**: Gmail caches AMP email content. Real-time data fetched by `<amp-list>` is re-fetched on each open, but the AMP HTML structure itself is cached. Dynamic content in the AMP markup (not fetched via XHR) does not update after send.
- **`<!--[if mso]>` conditionals are ignored in AMP**: AMP email has its own HTML subset. MSO conditional comments are not processed.
- **No support in Outlook or Apple Mail**: AMP emails always fall back to the `text/html` part in these clients. Do not expect AMP interactivity in Outlook or Apple Mail contexts.

Source: Google AMP for Email documentation; hteumeuleu email-bugs TODO; email_rendering_compatibility.md.

---

## Sending & Deliverability Surprises

### Google/Yahoo 2024 Bulk Sender Requirements

From February 2024, both Google and Yahoo enforced new requirements for senders of **5,000+ emails/day**:
- SPF **and** DKIM authentication (both required, not just one)
- DMARC policy at minimum `p=none` (with `rua` reporting address)
- One-click unsubscribe: `List-Unsubscribe: <https://...>` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
- Spam complaint rate below **0.10%** (warning threshold, Google Postmaster Tools), **0.30%** (hard rejection/blocking threshold)

**The exact one-click unsubscribe header syntax (verified against RFC 8058):**
```
List-Unsubscribe: <https://example.com/unsubscribe/opaquetoken>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

Critical RFC 8058 requirement: the message **must have a valid DKIM signature covering at least the `List-Unsubscribe` and `List-Unsubscribe-Post` headers**. Both headers must be in the DKIM signature's `h=` tag. A one-click unsubscribe header without DKIM coverage does not satisfy the requirement.

**The transactional email trap**: "I only send transactional email, so I'm exempt." This is partially wrong. The authentication requirements (SPF, DKIM, DMARC) apply to all senders. The one-click unsubscribe requirement applies to **marketing/promotional** email — but Gmail's classifier determines what is promotional, not you. A transactional email that Gmail classifies as promotional must have unsubscribe.

Source: Google Sender Guidelines 2024 (support.google.com/mail/answer/81126); Yahoo Sender Requirements 2024; RFC 8058 (rfc-editor.org/rfc/rfc8058, verified 2026-03-18).

---

### Gmail's Image Proxy Changes Your Image URLs

After the first delivery, Gmail rewrites all image URLs to route through `ci3.googleusercontent.com`. Your analytics platform sees requests from Google's IP ranges, not from user devices. Image load analytics from Gmail are Google proxy requests, not user requests.

This interacts badly with:
- Short-lived signed URLs (the URL in the email is the original; Google caches and serves from its proxy, but the original URL may expire)
- IP-based geo-targeting of images (all requests appear to come from Google's infrastructure)

Source: Google Help documentation; Litmus "Gmail Image Proxy".

---

### Transactional Email Can Still Be Filtered as Spam

"Transactional" is a sender's classification, not Gmail's or Yahoo's. If your order confirmation emails have high complaint rates (users marking them as spam), your delivery reputation degrades. This is especially common when:
- Users don't recognise the sender name
- The `From` address domain doesn't match the brand they recognise
- Transactional emails are sent from the same IP pool as marketing emails (reputation cross-contamination)

Fix: Separate sending infrastructure for transactional and marketing email. Use dedicated IPs for transactional. Ensure `From` name matches brand recognition.

Source: Postmark "Transactional Email Deliverability Guide"; SendGrid best practices.

---

## Testing Traps

### Litmus/Email on Acid Use Specific Client Versions

Screenshot testing tools run emails through specific versions of email clients — often not the latest. Always check which version a test is running against. Gmail webmail tests may lag the live product by weeks; Outlook tests run specific installed versions.

A rendering issue that appears in a test may be fixed in the live client, and a new live regression won't appear in the test until the tool updates.

Source: Litmus documentation; Email on Acid version notes.

---

### Dark Mode Is Rarely Tested, Often Shipped Broken

Most email QA processes default to light mode screenshots. Dark mode requires explicit test configuration. The result: dark mode rendering is the most common category of production email bugs in teams that haven't specifically addressed it.

Specific dark mode untested scenarios:
- White `<td>` background with white text (invisible in light mode; visible in dark mode due to forced inversion)
- Logo with transparent background (dark logo on inverted dark background — invisible)
- Status colour badges (green/red badges inverted to different shades that fail contrast)
- `color: inherit` in dark mode contexts resolving to unexpected values
- Near-white colours (`#fffffe`) altered by Yahoo dark mode just as aggressively as pure white (see Yahoo section above)

Fix: Add explicit dark mode renders to your QA checklist. Test in Apple Mail macOS dark mode and Gmail app dark mode as minimum.

Source: Litmus "Dark Mode Testing"; Email on Acid.

---

### Seed List Testing Is Not Inbox Placement Testing

Testing your email by sending to seed addresses (your own Gmail, Yahoo, Outlook accounts) confirms rendering and delivery. It does not confirm inbox placement for your actual subscriber list — because inbox placement depends on your sending domain/IP reputation, the recipient's engagement history, and list quality.

A clean seed list test does not mean your live send reaches inbox.

Fix: Use deliverability tools (GlockApps, Mail-Tester, MXToolbox) for inbox placement testing. Monitor your ESP's bounce rate and spam complaint dashboards.

Source: GlockApps documentation; Postmark deliverability guide.

---

## Quick Reference: The Nastiest Gotchas

| # | Gotcha | Client | Impact |
|---|--------|--------|--------|
| 1 | `url()` in inline styles strips ALL inline styles on the element | Gmail desktop | Layout destruction |
| 2 | Apple MPP pre-fetches tracking pixels — open rates unreliable | Apple Mail | Analytics corruption |
| 3 | 102KB HTML clip removes everything after the cutoff | Gmail | Email appears truncated |
| 4 | `aria-label` stripped entirely | Outlook 2007–2019 | Accessibility failure |
| 5 | Ghost table whitespace gap between columns | Gmail, Apple Mail | Multi-column layout broken |
| 6 | `prefers-color-scheme` rewritten to non-matching query | Yahoo Mail | Dark mode silently broken |
| 7 | DMARC subdomain strict alignment — subdomain fails for root domain | All | Deliverability failure |
| 8 | Image URL not versioned — Gmail cache serves old image forever | Gmail | Stale imagery post-update |
| 9 | `display: none` insufficient to hide preheader in all clients | Outlook preview pane | Preheader text leaks |
| 10 | `mso-line-height-rule: exactly` missing — Outlook inflates line height | Outlook 2007–2019 | Typography broken |
| 11 | Gmail strips rules using whitespace colour syntax (`rgb(0 0 0)`) | Gmail (all) | Silent style loss |
| 12 | Yahoo/AOL strip `class` attribute from `<img>` — image CSS rules lost | Yahoo, AOL | Dark mode / responsive image swap fails |
| 13 | SVG not supported in Gmail or legacy Outlook | Gmail, Outlook 2007–2019 | Images missing |
| 14 | CSS Custom Properties (`var()`) not supported in Gmail or Outlook | Gmail, Outlook 2007–2019 | All variable-based styles silently fail |
| 15 | Relative URLs silently fail — `<base href>` is stripped | All webmail clients | Broken images and links |

---

## Sources

1. **caniemail.com** — Feature-by-feature client support data. Verified against specific features throughout.
   - /scoreboard/ — 303 features tested; Apple Mail 283/303; Gmail desktop 152/303; Outlook Windows 59/302 (lowest of active clients).
   - /features/css-display-flex/ — ~83% support; not supported in Outlook Windows 2007–2019; Yahoo partial (no `inline-flex`); Gmail: not supported with non-Google accounts.
   - /features/html-style/ — Gmail 16KB `<style>` block limit confirmed; Yahoo Android removes first `<head>`; Yahoo desktop CSS rule after comment is dropped. Last tested July 2023.
2. **hteumeuleu/email-bugs** — github.com/hteumeuleu/email-bugs — documented, reproduced email client bugs. Issues #146, #148, #152, #156, #157, #158, #160, #161, #162 reviewed 2026-03-18.
3. **hteumeuleu.com** — Rémi Parmentier's email rendering research blog
4. **Litmus Blog** — litmus.com/blog — industry standard email testing and research
5. **Campaign Monitor CSS Support** — campaignmonitor.com/css
6. **Email on Acid Blog** — emailonacid.com/blog
7. **Stack Overflow `html-email` tag** — stackoverflow.com/questions/tagged/html-email
8. **Google Sender Guidelines 2024** — support.google.com/mail/answer/81126
9. **RFC 7489 (DMARC)** — rfc-editor.org/rfc/rfc7489
10. **RFC 8058 (List-Unsubscribe One-Click)** — rfc-editor.org/rfc/rfc8058. Verified 2026-03-18: exact syntax `List-Unsubscribe-Post: List-Unsubscribe=One-Click`; DKIM coverage of both headers required; POST body as `application/x-www-form-urlencoded` or `multipart/form-data`.
11. **Apple MPP announcement** — developer.apple.com (2021)
12. **Postmark Deliverability Guide** — postmarkapp.com/guides/email-deliverability
13. **Google AMP for Email** — developers.google.com/gmail/ampemail

---

## TODOs

- [ ] **hteumeuleu/email-bugs repo audit**: Continue reviewing the full issue list beyond the issues checked on 2026-03-18. Issues #1–#145 not reviewed in this pass.
- [ ] **New Outlook (Edge renderer) gotchas**: The new Outlook for Windows uses an Edge-based renderer. Continue monitoring hteumeuleu/email-bugs #148 for the hybrid layout regression in 2025 Outlook 365 builds.
- [ ] **AMP for Email gotchas**: AMP introduces its own category of gotchas (cache invalidation, fallback rendering, CORS requirements for XHR). The section above covers the major ones; research CORS error handling patterns specifically.
- [ ] **ESP-specific gotchas**: Each major ESP (SendGrid, Mailchimp, Postmark, Mailgun) has its own quirks for template variable syntax, link wrapping, and header injection. Document per-ESP.
- [ ] **Apple Intelligence email summaries**: iOS 18+ Apple Intelligence may summarise email content in the notification or inbox view. Monitor whether the summarisation engine can be influenced by structured content placement or semantic markup.
- [ ] **`prefers-reduced-motion` client support matrix**: Map which email clients honour this for engineers using CSS animations.
- [ ] **Emoji rendering differences**: Emoji render differently across clients (Apple emoji style vs Windows emoji style vs Android emoji style). Document which clients render which emoji set and whether any clients strip or replace emoji.
- [ ] **`target="_blank"` security in email links**: `target="_blank"` without `rel="noopener noreferrer"` exposes the opener context — primarily a concern in webmail (Gmail, Outlook.com) where the email renders in a browser tab. Assess whether this is a meaningful attack surface in email vs web.

COMPLETE
