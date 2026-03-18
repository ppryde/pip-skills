# Email Engineering: Master Research Summary

Synthesis of 6 research documents covering the full stack of transactional and marketing email engineering.
Compiled: 2026-03-18. Based on research verified against live sources in March 2026.

---

## Executive Summary

- **Outlook 2007–2019 on Windows governs the entire compatibility floor**: its Word rendering engine scores 59/302 on caniemail.com — the lowest of all tracked clients. No `border-radius`, no `background-image` on divs, no CSS `max-width` on tables, no Flexbox, no Grid, broken shorthand CSS. Table-based layout with VML fallbacks and MSO conditional comments are mandatory for enterprise B2B audiences where Outlook desktop can represent 30–50% of opens.

- **Inline CSS is the only universally safe styling mechanism**: Gmail historically strips `<head>` blocks (the `<style>` tag has a 16 KB limit in Gmail and is not supported inside `<body>`); many other clients partially or entirely ignore non-inlined styles. All layout-critical properties must be inlined; `<style>` blocks are safe only for media queries, resets, hover states, and dark mode overrides.

- **Gmail has a hard 102 KB HTML clip and a critical background-image bug**: Gmail clips email HTML at exactly 102,400 bytes; content below the clip is silently hidden. Separately, Gmail's desktop webmail strips the entire `style` attribute from any element whose inline styles contain a `background-image: url()` reference — not just the background-image rule, but all inline styles on that element.

- **Deliverability is an authentication engineering problem, not a content afterthought**: SPF, DKIM, and DMARC are now mandatory requirements enforced by Google and Yahoo for bulk senders as of February 2024. DMARC must be at minimum `p=none` with a valid `rua=` address; DKIM must use RSA-2048 or better. Failure cannot be compensated for by content quality or sender reputation alone. One-click unsubscribe (RFC 8058) is also mandated for bulk senders.

- **Accessibility and rendering resilience converge almost completely**: `role="presentation"` on layout tables, meaningful `alt` text on all images, semantic heading hierarchy (`<h1>`–`<h3>`), and 14px minimum font sizes are simultaneously required by WCAG 2.1 AA and by the practical realities of image-blocking (~43% of recipients), screen readers in enterprise environments, and dark mode inversions (~35% of opens).

- **The European Accessibility Act enforcement deadline passed in June 2025**: B2C transactional email from covered EU sectors must now meet WCAG 2.1 Level AA. This is no longer aspirational — it is an active compliance requirement with enforcement by national authorities in Germany, France, and the Netherlands active as of this writing.

- **The MJML + server-side templating pipeline is the dominant recommended architecture**: MJML handles cross-client complexity (table layouts, VML buttons, MSO conditionals, CSS inlining) at compile time; a separate engine (Jinja2, Handlebars, Nunjucks, or Liquid) injects per-recipient data at runtime. Keeping these concerns separate produces maintainable, testable pipelines. React Email is a viable TypeScript-stack alternative that eliminates the two-phase split.

- **Dark mode is a primary design constraint**: ~35% of opens occur in dark mode environments. Clients split into two groups: those that honour `prefers-color-scheme` (Apple Mail, Gmail web, Outlook.com), and those that apply forced colour inversion without honouring the media query (new Outlook for Windows, Gmail iOS). Yahoo Mail, AOL, Fastmail, and HEY transform the `prefers-color-scheme` query into a non-matching rule — dark mode overrides are silently discarded in those clients.

- **Template rendering failures are a distinct failure mode invisible to other test pipelines**: unresolved variables appearing as `undefined`, `NaN`, or literal `{{variable}}` strings in sent email, empty `href` attributes on CTA buttons, and missing fallback values for null data are production defects that cannot be caught by rendering-compatibility or deliverability testing. They require dedicated render-time unit tests with representative fixture data.

- **Legal compliance obligations span multiple jurisdictions and apply to both email types**: CAN-SPAM (US), GDPR/UK GDPR (EU/UK), CASL (Canada, stricter implied consent expiry at 2 years), and the EAA collectively impose physical address disclosure, unsubscribe mechanism, consent records, and WCAG 2.1 AA requirements. Mixing promotional content into a transactional email can reclassify it under CAN-SPAM and impose full marketing obligations.

---

## 1. Rendering & Client Compatibility

### Source: `email_rendering_compatibility.md`

The email client landscape is defined by a fundamental split between WebKit-based clients (Apple Mail, iOS Mail, Outlook for Mac, Samsung Email, new Outlook for Windows) and the legacy Outlook for Windows 2007–2019 stack, which uses Microsoft Word's rendering engine. Apple Mail scores 283/303 on caniemail.com — the highest of any tracked client. iOS Mail scores 280/303. Outlook for Windows 2007–2019 scores 59/302 — the lowest, by a wide margin. That single client imposes the compatibility floor for the entire industry because it holds 5–10% of opens globally and potentially 30–50% of opens in enterprise B2B environments.

The consequences are specific and non-negotiable for enterprise-targeted email. CSS `max-width` on `<table>` elements is not supported per the CSS 2.1 spec that Word's renderer follows — use the `width` HTML attribute instead. Shorthand `padding` is unreliable — use explicit `padding-top`, `padding-right`, `padding-bottom`, `padding-left`. Vertical padding on `<td>` elements shares across all cells in a row; if one cell in a row has `padding-top: 40px`, all cells in that row get 40px regardless of individual declarations. `rgba()` colours are not supported — use hex fallbacks. `border-radius` requires a VML `<v:roundrect>` fallback for buttons. `background-image` on `<div>` elements requires a VML `<v:rect>` fallback for hero sections.

MSO conditional comments are the mechanism for these fallbacks. Written as HTML comments with `<!--[if mso]>` and `<![endif]-->`, they are processed by Outlook's Word renderer and ignored as comments by every other client. The "ghost table" pattern uses MSO conditionals to give Outlook a conventional two-column table while modern clients see `display: inline-block` divs — the central technique for column layouts that work universally without media queries. The new Outlook for Windows (2021+, Edge/Chromium renderer) still processes MSO conditionals, so existing code is safe, but VML is no longer required for that client.

Gmail's webmail introduces a separate constraint class. It clips HTML at exactly 102,400 bytes (the 102 KB clip), replacing truncated content with "[Message clipped] View entire message". This limit applies to the raw HTML including all inlined CSS — large templates with verbose inlined styles can hit it unexpectedly. Gmail also has a critical background-image bug: when `background-image: url()` referencing a valid image appears in an inline `style` attribute, Gmail strips the entire `style` attribute from that element, not just the background-image property. All other inline styles on that element are lost. The workaround is to apply background images only via a `<style>` block class selector, accepting that Gmail desktop will show the fallback background colour rather than the image.

The preheader is a hidden `<div>` placed immediately after `<body>`, containing the inbox preview text. It uses `display: none; max-height: 0; overflow: hidden; visibility: hidden; mso-hide: all; opacity: 0` to suppress visual rendering while remaining readable by inbox preview panes. Zero-width non-joiner characters (`&zwnj;`) pad it to prevent body text from bleeding into the preview after the intended preheader text ends. Without an explicit preheader, clients pull the first visible text from the email body — typically a "View in browser" link or navigation item.

Dark mode splits into two distinct behaviours that require separate handling. Clients honouring `prefers-color-scheme` (Apple Mail, Gmail web 2020+, Outlook.com) allow CSS media query overrides. Clients applying forced inversion without honouring the query (new Outlook for Windows 2021+, Gmail iOS) require the `color-scheme` meta tag approach and off-white (`#fffffe` instead of pure `#ffffff`) colour values that some inversion engines treat as already-dark and skip. Yahoo Mail, AOL, Fastmail, and HEY transform the media query into a non-matching rule — their users always see the light mode design. Roughly 42% of tracked clients support `prefers-color-scheme` per caniemail.com.

---

## 2. HTML/CSS Best Practices

### Source: `email_html_css_practices.md`

The three foundational laws of HTML email are: tables for structure, inline styles for guaranteed rendering, and defensive coding against Outlook's Word renderer. These are technical requirements, not stylistic preferences. Flexbox has approximately 83% overall support across tracked email clients per caniemail.com (supported in Apple Mail, Gmail, Outlook.com, Samsung Email, Thunderbird, and ProtonMail) but is not supported in Outlook 2007–2019 on Windows or in some Yahoo/AOL contexts for `inline-flex`. CSS Grid has approximately 56% support — not supported in Outlook 2007–2019, Gmail, or Yahoo. Neither can be used for layout-critical properties in emails targeting mixed audiences.

Every structural table requires four attributes applied together: `role="presentation"` (suppresses screen reader table announcements — an accessibility and compliance requirement), `border="0"` (removes default visible borders), `cellpadding="0"` (removes default cell padding), and `cellspacing="0"` (removes cell spacing — Outlook ignores CSS `border-spacing` but respects this HTML attribute). The canonical email structure is an outer 100%-width table filling the viewport, containing a centred inner content table with `width="600"` (HTML attribute) and `style="max-width: 600px; width: 100%;"` (CSS). Outlook honours the HTML attribute width and ignores CSS `max-width` on table elements; modern clients use the CSS to allow the table to shrink below 600px on narrow viewports.

CSS inlining strategy requires deliberate discipline. Properties that must always be inlined include: `background-color`, `color`, all `font-*` properties, individual `padding-top/right/bottom/left` sides (shorthand padding is unreliable in Outlook), `text-align`, `vertical-align`, and `width`/`height` on images and cells. Properties safe to place only in a `<style>` block include `@media` queries, `:hover` pseudo-classes, `@font-face` declarations, CSS resets, and `@media (prefers-color-scheme: dark)` overrides — those properties are progressive enhancements that degrade gracefully when the `<style>` block is stripped. Layout-critical properties must never rely solely on `<style>` block inclusion.

Custom web fonts degrade gracefully via `@font-face` in Apple Mail and iOS Mail but are ignored in Gmail, Outlook Windows, and Yahoo Mail. The fallback font stack must be explicitly designed and visually tested — custom font letter-spacing and sizing are not preserved in fallback rendering. The hybrid (spongy) layout technique creates mobile-responsive behaviour without relying on `@media` queries: outer tables at 100% width containing inner content with `max-width` and `width: 100%` shrinks on narrow viewports automatically in modern clients without any media query, which is critical for Gmail on Android and older webmail clients that do not support them.

Dark mode CSS requires `!important` on all overrides since they must override inlined light mode styles. The `color-scheme` and `supported-color-schemes` meta tags signal dark mode awareness to Apple Mail and iOS Mail and reduce unwanted colour inversion. Outlook.com uses custom `data-ogsb` / `data-ogac` attributes in dark mode that can be targeted as CSS selectors: `[data-ogsb] .email-bg { background-color: #1a1a1a !important; }`. Contrast ratios must be re-verified after applying dark mode overrides — a ratio that passes in light mode can fail when the background colour changes.

---

## 3. Content, Copy & UX

### Source: `email_content_copy_ux.md`

Subject line length should target 40–50 characters for reliable cross-client display. Most mobile clients truncate at 33–41 characters depending on screen width; desktop clients show up to 60–70 characters legibly. The preheader should complement — never repeat — the subject line, targeting under 90 characters as a safe universal limit (display length varies by client, but this avoids the risk of clients pulling fallback body text to fill the preview). Gmail's mobile rendering shows approximately 100 combined subject + preheader characters, so a shorter subject leaves more room for preheader value. The sender name is the more influential variable: 68% of recipients decide whether to open based on the "From" name alone — subject line optimisation delivers more value when sender trust is already established.

Body copy structure follows the F-pattern of on-screen reading documented by Nielsen Norman Group: readers scan fully across the first one or two lines, then progress down the left margin with progressively shorter horizontal reads. Critical information must appear in the first sentence of each paragraph. The single most important fact or action should be positioned within the first 200–300 pixels of the email body, visible above the fold on most mobile previews without scrolling. Paragraphs should be no more than 3–4 sentences; inverted pyramid structure (most important first, supporting detail second, background context last) consistently outperforms narrative build-up in email contexts. Left-aligned body text reinforces F-pattern scanning; centred body copy over three to four words is harder to scan.

CTA buttons should use verb-first, first-person copy (2–5 words). First-person copy ("Get my guide", "Start my trial") outperforms second-person ("Get your guide") by 7–14% CTR in published A/B tests. Single primary CTAs outperform multiple CTAs: each additional CTA reduces the probability of any CTA being clicked (Hick's Law). When secondary links are unavoidable, they should be text links below the primary button, never equal-weight buttons side by side. Minimum button height is 44px (Apple Human Interface Guidelines tap target minimum; Google Material Design specifies 48dp — use 44px as the safe floor). Buttons must be bulletproof HTML buttons (VML/CSS hybrid), not image-based — image buttons disappear when images are blocked by roughly 43% of recipients.

Transactional emails must be direct, factual, and minimal. Injecting marketing language into a transactional context (a password reset, an order confirmation during a security-anxiety moment) erodes trust and can reclassify the email under CAN-SPAM, imposing full marketing obligations. Dark patterns in unsubscribe placement — hiding the unsubscribe in difficult-to-reach screen zones to reduce click-through — violate CAN-SPAM and GDPR requirements and are increasingly flagged by Gmail's spam classifier. Countdown timers to artificial deadlines are flagged by GDPR-focused regulators in the UK and EU. Password reset links should state a genuine expiry time ("This link expires in 60 minutes") — this is security information, not urgency marketing, and is recommended by OWASP.

CASL (Canada) requires either express or implied consent for commercial messages; implied consent from a business relationship expires after two years. Systems sending to Canadian addresses should track the consent date and suppress lapsed contacts. GDPR requires that the unsubscribe mechanism be as easy as subscribing — functionally, this means the one-click flow must work without requiring a separate login page or multi-step confirmation. Including a reference number in transactional subject lines reduces "did my order go through?" support tickets and improves trust signal by making the email verifiably specific to a user action.

---

## 4. Accessibility & Inclusivity

### Source: `email_accessibility_inclusivity.md`

WCAG 2.1 Level AA is the correct accessibility baseline for transactional email. It satisfies the European Accessibility Act (enforceable from 28 June 2025 for B2C digital services in the EU — this deadline has now passed), Section 508 (US federal agencies and contractors), AODA (Ontario, Canada, for organisations with 50+ employees), and provides a defensible position for ADA Title III claims. The most applicable WCAG criteria for email are: 1.1.1 (alt text for all non-text content), 1.3.1 (semantic structure including heading hierarchy and table markup), 1.3.2 (reading order matches DOM order), 1.4.1 (colour not sole conveyor of information), 1.4.3 (contrast minimum: 4.5:1 for body text, 3:1 for large text and UI components), 1.4.12 (text spacing: line height at least 1.5×), 2.4.4 (descriptive link text — no "click here"), and 3.1.1 (language attribute on `<html>`).

ARIA support in email clients is partial and uneven. The `role` attribute (including `role="presentation"`) has approximately 73% overall support across tracked clients per caniemail.com — fully supported in Apple Mail, Gmail (2019+), Outlook 365+/macOS/mobile, ProtonMail, Fastmail, and HEY, but only partial in Yahoo Mail and AOL (honoured only on `<table>` tags, not `<div>`), and not supported in Outlook 2007–2016. The practical consequence is acceptable: Outlook 2007–2016's Word renderer does not independently announce table structure, so the lack of `role` support in those clients still produces correct screen reader behaviour. `aria-label` has approximately 58.5% support but is stripped entirely by Outlook 2007–2019 — visible link and button text must be descriptive enough to stand alone without relying on `aria-label` in those clients. `aria-describedby` and `aria-labelledby` are buggy in Gmail, Fastmail, and Outlook.com due to id-prefix mangling — do not use them as the primary accessibility mechanism in email.

Colour contrast is among the most frequently violated requirements. A critical failure pattern is light grey footer text: `#999999` on white has a contrast ratio of 2.9:1 — it fails WCAG AA (minimum 4.5:1 for normal text). The minimum grey on white that passes AA is `#767676` (4.5:1 exactly). White text on the widely used `#28a745` green also fails (2.9:1). Colour must never be the sole conveyor of information — error states, status badges, and required fields must include icons or text labels alongside colour coding. When designing `prefers-color-scheme: dark` overrides, contrast ratios must be explicitly re-verified in the dark state, not assumed to pass because the light state passed.

The distinction between layout tables and data tables is one of the most commonly missed accessibility requirements in transactional email. Layout tables must carry `role="presentation"` to suppress screen reader table announcements. Data tables (order summaries, invoice line items) require the opposite treatment: `role="table"`, `<thead>` with `<th scope="col">` column headers, `<tfoot>` with `<th scope="row">` row headers for totals, and a `<caption>` element providing the accessible table name. Data tables without proper header markup cause screen readers to announce cell data without positional context — a user hears "2", "£49.98", "Blue Widget" without knowing which column they belong to.

Screen reader behaviour varies significantly by client/reader combination. VoiceOver with Apple Mail provides the best email accessibility experience: it honours heading navigation, list semantics, `role="presentation"`, `scope` attributes, `aria-label`, and `aria-hidden`. JAWS with Outlook 2007–2019 is the critical enterprise combination: `aria-label` is stripped entirely (visible text must carry meaning), `aria-labelledby`/`aria-describedby` references are broken (id attributes are stripped), but heading navigation (H key) and image alt text work correctly. Both JAWS and NVDA read in DOM order — source-order alignment with visual reading order is a hard requirement, not a recommendation. The `lang` attribute on `<html>` is required for TTS engines to select correct pronunciation; multilingual emails should use `lang` attributes on individual sections containing non-primary-language content.

---

## 5. Deliverability & Technical Hygiene

### Source: `email_deliverability_technical_hygiene.md`

Deliverability is the probability that a sent message reaches the recipient's inbox rather than their spam folder, quarantine queue, or a silent discard. It is a composite of sender reputation, authentication pass rates, content quality, and engagement signals. Technical delivery (the SMTP connection was accepted) and inbox placement (deliverability) are distinct. Authentication failure cannot be compensated for by good content or clean reputation.

The three-layer authentication stack — SPF, DKIM, DMARC — has been mandatory for bulk senders to Gmail and Yahoo since February 2024. SPF (RFC 7208) authorises sending IPs for the envelope `MAIL FROM` domain; SPF evaluation must not require more than 10 DNS lookups (exceeding this limit returns `permerror`, treated as a fail by many receivers). DKIM (RFC 6376) cryptographically signs outgoing messages; RSA-1024 is deprecated and rejected by Gmail — RSA-2048 is the minimum, with ed25519 recommended as a second signature. Canonicalisation must be `relaxed/relaxed` to tolerate minor whitespace changes introduced by mail transfer agents; DKIM keys should be rotated at least annually. DMARC (RFC 7489) requires identifier alignment — the authenticated domain from SPF or DKIM must match the RFC5322 `From:` header domain. For bulk senders (5,000+ messages/day to Gmail or Yahoo), DMARC must be published at minimum `p=none` with a valid `rua=` reporting address.

DMARC deployment follows a staged roadmap: publish `p=none` with aggregate reporting and collect data for at least two weeks; analyse reports with dmarcian or Google Postmaster Tools to identify third-party senders not covered by SPF/DKIM; advance to `p=quarantine` at partial percentage then 100%; advance to `p=reject` once quarantine shows negligible legitimate failures. BIMI (Brand Indicators for Message Identification) — logo display in Gmail, Yahoo, and Apple Mail — requires DMARC at `p=quarantine` or `p=reject` plus a Verified Mark Certificate.

One-click unsubscribe (RFC 8058) is mandated by Google's and Yahoo's 2024 sender requirements for all bulk/subscribed mail. The `List-Unsubscribe-Post: List-Unsubscribe=One-Click` header must be present alongside both a mailto and HTTPS URI in the `List-Unsubscribe` header. The HTTPS endpoint must: embed per-recipient token data to identify the subscription without requiring cookies or auth headers; process the POST body containing `List-Unsubscribe=One-Click`; suppress the address within 2 business days (Google requirement); and must NOT return HTTP redirects in response to POST requests. Suppression applied immediately on receipt is the correct engineering target.

Content and HTML hygiene affect spam scores independently of authentication. SpamAssassin's `UPPERCASE_25_50` rule fires when 25–50% of body words are capitalised; escalating rules fire up to 75% and 100%. Spam trigger word clusters (financial urgency, deceptive framing, excessive punctuation) raise composite scores. The "60% text / 40% images" ratio rule that circulated widely in the early 2010s is a discredited legacy heuristic — modern filters weight authentication state and sender reputation far more heavily than image ratio. The current valid guidance is: include at minimum 500 characters of live text for any image-heavy message, and never send a single-image-only email with no text body. Consumer URL shorteners (bit.ly, tinyurl.com) must never appear in email — shared shortener domains carry cumulative spam reputation and are permanently blocklisted in SURBL and URIBL.

MIME structure must be `multipart/alternative` with `text/plain` before `text/html` — RFC 2046 specifies that parts are listed in increasing preference order (the last part is preferred), so HTML must appear last. Plain-text versions must be genuine prose renderings of the HTML content, not stubs — their absence raises spam scores in Barracuda and Proofpoint, and CAN-SPAM requires physical address text to be present and readable in all MIME parts. IP warm-up is required for new dedicated IPs: volume is ramped from 200 messages/day over approximately 30+ days, sending initially only to highest-engagement recipients. Spam complaint rates above 0.08% trigger Google Postmaster Tools warnings; above 0.10% triggers enforcement action; above 0.30% causes delivery rejection. Apple Mail Privacy Protection (iOS 15+) pre-fetches all remote content through Apple's proxy servers — open rate is no longer a reliable deliverability signal and must not be used as the primary metric for IP warm-up calculations.

---

## 6. Templating Languages & Frameworks

### Source: `email_templating_languages_frameworks.md`

The dominant architecture for production transactional email separates two concerns across two pipeline phases. Phase 1 (design compilation, at build time): MJML source files are compiled to cross-client HTML — nested tables, inlined CSS, MSO conditional comments for Outlook, VML buttons — by the MJML compiler. MJML 4.18.0 is the current stable version (December 2024). MJML v5.0.0-beta.1 (March 2025) introduces breaking changes including a new minification backend, a changed `<body>` structure, disabled file includes by default, and dropped support for Node.js 16/18; production pipelines should not upgrade without visual regression testing. Phase 2 (dynamic rendering, at send time): a server-side templating engine injects per-recipient data. MJML passes placeholder tokens verbatim in its output, so compiled HTML can serve directly as the template body for the injection phase.

The major server-side engines divide by language ecosystem. For Python: Jinja2 is the de facto standard, with template inheritance (`{% extends %}`/`{% block %}`), composable filters (`{{ price | round(2) }}`), whitespace control (`{%- -%}` to strip whitespace from `<table>` cells), and sandboxed execution for untrusted templates. For JavaScript/Node.js: Handlebars provides logic-minimal double-curly syntax (`{{variable}}`, `{{#each}}`, `{{#if}}`) with custom helper extensibility; Nunjucks is the closest JS equivalent to Jinja2, with macros for reusable components. Liquid (Shopify-originated, used by Klaviyo for event-driven sends) is the safest engine for rendering user-controlled input because it has no file system access or arbitrary code execution capability. React Email (v5.2.10, released 17 March 2026, maintained by Resend) writes email templates as TypeScript React components rendered to HTML strings at send time — catching data-shape mismatches at compile time via TypeScript types rather than at send time when a broken email reaches a recipient.

ESP-native template systems (SendGrid Dynamic Templates using a Handlebars subset, Postmark using standard Mustache, Mailchimp/Mandrill using proprietary merge tags `*|FNAME|*`) store templates inside the ESP and render at send time from a JSON data payload. The advantages are non-engineer editability, built-in A/B testing, and no HTML delivery over the network per send. The critical disadvantage is lock-in — migrating ESPs requires rewriting all templates. SendGrid's Handlebars subset does not support custom helpers or `@index`/`@first`/`@last` loop metadata variables reliably. Postmark uses standard Mustache (not Handlebars), which means no block helpers — `{{#items}}` iterates arrays via Mustache's section syntax, not an `#each` helper. The hybrid pattern — MJML-compiled HTML uploaded as the ESP template body with ESP-native placeholder syntax preserved inside the MJML source — is the recommended approach for teams wanting MJML's rendering quality alongside ESP-managed template versioning.

Fallback values for missing template variables are an engineering requirement, not an optional refinement. Every variable output tag must have a fallback: Jinja2 and Liquid have built-in `| default(...)` filters; Handlebars requires a registered custom helper or explicit `{{#if name}}...{{else}}...{{/if}}` patterns; Postmark Mustache uses inverted sections `{{^first_name}}Valued Customer{{/first_name}}`. React Email uses TypeScript default props. Currency and numeric formatting must use template filters or helpers — raw floats (`199.9` instead of `$199.90`) and unformatted numbers are common production defects. Render-time unit tests should assert that no compiled template output contains `undefined`, `NaN`, literal `{{variable}}` strings, empty `href` attributes on CTA buttons, or empty `src` attributes on images with representative fixture data covering missing, null, and empty-array cases.

---

## Cross-Cutting Themes

### 1. Outlook Windows is the universal pain point

Outlook for Windows 2007–2019 is the single most constraining factor across every domain in this research. In rendering compatibility: it defines the floor for table-based layouts, VML fallbacks, and MSO conditionals. In HTML/CSS practices: it explains why inline CSS, explicit padding longhand, HTML attribute widths, and the `<table>` layout mandate exist. In templating: it is the primary reason MJML exists as a compile-step tool. In accessibility: its Word renderer strips `aria-label` attributes, requiring visible text to carry full meaning. In deliverability: MSO-conditional-wrapped VML content must be syntactically valid to avoid triggering HTML-malformation spam rules. Every technical decision traces back to this one client. The new Outlook for Windows (Edge renderer, deployed through 2024–2025) will eventually eliminate most of these constraints, but enterprise volume licensing keeps legacy builds active for an indeterminate period, and MSO conditionals remain harmless to include.

### 2. The 2024 Google/Yahoo sender requirements cross multiple domains

Google's and Yahoo's February 2024 mandatory sender requirements for bulk senders affect both deliverability and content. From the deliverability side: SPF, DKIM (RSA-2048+), and DMARC (`p=none` minimum with `rua=`) are now enforced, not recommended. From the content/UX side: one-click unsubscribe (RFC 8058) must be present in the email headers and the endpoint must process POST requests correctly. From the rendering side: the `List-Unsubscribe` header appears in the raw message, not in the template HTML, and must be generated by the sending infrastructure. From the legal compliance side: this is aligned with CAN-SPAM's opt-out requirement and GDPR's ease-of-unsubscribe requirement. These requirements are not siloed in a single domain — they require coordination across infrastructure, content, and engineering teams.

### 3. Inline CSS is the connective tissue

CSS inlining appears as a requirement in the HTML/CSS practices document for rendering fidelity, in the deliverability document as a spam filter hygiene concern (malformed HTML raises scores), in the templating document as the core value proposition of MJML, and in the accessibility document (Gmail's `<style>` block stripping means class-based dark mode overrides may not reach all recipients). Gmail's style-stripping behaviour and Outlook's limited CSS parser converge on the same engineering solution: critical styles must live on the element. MJML's compile-step automation of this inlining is its primary engineering justification.

### 4. Accessibility and image-blocking resilience are the same requirement

The requirement to provide meaningful `alt` text, use semantic HTML headings, keep critical content in live text rather than images, and maintain adequate contrast ratios is justified twice over — once by WCAG and once by practical rendering constraints. Image blocking affects approximately 43% of recipients across clients. Screen readers in enterprise environments (JAWS+Outlook) are common. Dark mode inversions affect 35%+ of opens. Designing for accessibility and designing for image-blocking and dark-mode resilience converge almost completely — there is very little conflict and substantial overlap between these requirements.

### 5. Legal compliance cascades through the full engineering stack

CAN-SPAM, GDPR, CASL, and the EAA create engineering requirements that manifest across multiple layers. The physical mailing address must be present in the MIME plain-text part (deliverability and CAN-SPAM). The unsubscribe must be a functional link with RFC 8058 one-click support (deliverability, rendering, and legal). Consent basis must be documented in the sending platform (content/UX and GDPR). WCAG 2.1 AA must be met for EU B2C transactional email (accessibility and EAA, now in enforcement). CASL requires suppression of contacts whose implied consent has expired after two years, which requires a consent timestamp in the sending data model. These are not documentation items for legal teams — they have concrete implementation consequences in template code, sending infrastructure, and data models.

### 6. Template rendering failures are invisible to other test pipelines

The rendering compatibility testing pipeline (Litmus, Email on Acid cross-client screenshots) tests the structural HTML. The deliverability testing pipeline (mail-tester.com, GlockApps spam scoring) tests authentication and content hygiene. Neither catches unresolved template variables appearing as `undefined` or literal `{{variable}}` strings, empty `href` attributes on CTA buttons, missing currency formatting, or `NaN` in calculated order totals. These failures are only caught by render-time unit tests with representative fixture data, including edge cases: missing first name, empty order items array, null tracking URL, zero-amount invoice line. This class of failure is among the most visible engineering defects in production email systems because it reaches recipients directly.

---

## Quick Reference Table

One critical rule or checklist item from each domain:

| Domain | Single Most Important Rule |
|---|---|
| Rendering & Compatibility | Use `<table role="presentation" border="0" cellpadding="0" cellspacing="0">` for all structural layout — it is the only layout primitive that works in all clients including Outlook 2007–2019. Set `width="600"` as an HTML attribute (not just CSS) on inner content tables. |
| HTML/CSS Practices | Inline all layout-critical CSS directly on elements; `<style>` blocks are progressive enhancement only. Never use shorthand `padding` in Outlook — always use `padding-top/right/bottom/left` individually. |
| Content, Copy & UX | One primary CTA per email on a bulletproof HTML button (VML+CSS hybrid) at least 44px tall, with verb-first first-person copy of 2–5 words. Never an image-based button — images are blocked for ~43% of recipients. |
| Accessibility & Inclusivity | Every layout table must have `role="presentation"`; every image must have an `alt` attribute (descriptive for informative images, `alt=""` — never omitted — for decorative). Body text at minimum 4.5:1 contrast ratio; `#999999` on white fails (2.9:1). |
| Deliverability & Technical Hygiene | Publish and actively maintain SPF, DKIM (RSA-2048, `relaxed/relaxed`), and DMARC (`p=none` minimum with `rua=`) for all sending domains. Implement RFC 8058 one-click unsubscribe for bulk sending streams. |
| Templating Languages & Frameworks | Write render-time unit tests asserting that no compiled output contains `undefined`, `NaN`, or literal `{{...}}` strings, and that all `href` and `src` attributes are non-empty. Every variable output tag must have an explicit fallback value. |

---

## Notable Corrections from Live Source Verification

The following items were incorrect or outdated in earlier versions of this research and have been corrected based on live source verification performed against caniemail.com, Litmus, and other primary sources in March 2026:

**1. Flexbox and Grid support figures were significantly understated**
Earlier research cited Flexbox support in email at "~50%" and Grid at "~40%". Live caniemail.com data shows `display: flex` at approximately 83% and `display: grid` at approximately 56% across tracked clients. The blocking factor for broad use of both remains unchanged — neither is supported in Outlook 2007–2019 on Windows — but the majority of other clients support them. The practical guidance (use tables for Outlook-target layouts) is unchanged; the support numbers are not.

**2. The "60% text / 40% images" ratio rule is discredited**
Earlier research and many industry guides present a 60%/40% text-to-image ratio as a formal spam filter threshold. This was a rule of thumb from early-2010s ESP guidance, not a formally specified filter. Current guidance from major ESPs (Litmus, Campaign Monitor, Mailchimp) is that modern filters weight authentication state and sender reputation far more heavily than image ratio. The valid practical guidance is: include at minimum 500 characters of live text for image-heavy messages; single-image-only emails with no text body are high-risk regardless of ratio.

**3. Google Material Design accessibility URL changed**
Earlier research cited `https://m2.material.io/design/usability/accessibility-basics` (or similar) for the 48dp tap target size. This URL returns 404 as of March 2026. The current URL is `https://m3.material.io/foundations/accessible-design/overview`.

**4. `emailclientmarketshare.com` now redirects to Litmus**
Earlier research cited `emailclientmarketshare.com` as a standalone resource. As of March 2026, this domain redirects to `litmus.com/email-client-market-share/`. The Litmus page is JavaScript-rendered and cannot be accessed via automated fetching — data must be retrieved manually via a browser.

**5. Litmus State of Email reports are now gated**
Earlier research cited Litmus State of Email statistics as freely accessible. As of March 2026, the report is gated behind an email sign-up form. Statistics cited in this research are from the 2022/2023 editions retrieved before gating, and remain accurate as directional benchmarks.

**6. Dark mode `prefers-color-scheme` support in Yahoo/AOL/Fastmail/HEY is more broken than "unsupported"**
Earlier research described `prefers-color-scheme` as "not supported" in Yahoo Mail, AOL, Fastmail, and HEY. The more precise finding is that these clients actively transform the media query into a non-matching rule (`@media ( _filtered_a )` in Yahoo, `@media none` in Fastmail, `@media (false)` in HEY). This means dark mode overrides are not merely ignored — they are silently discarded by a transformation, which could cause confusion when debugging unexpected light-mode rendering.

**7. caniemail.com Outlook Windows score precision**
Earlier research cited Outlook Windows as scoring "the lowest of all tracked clients" without a precise figure. The confirmed score from caniemail.com/scoreboard/ is 59/302 (or 59/303 depending on when the count of features is sampled). For context: Apple Mail is 283/303, iOS Mail 280/303, Samsung Email 250/300, Outlook Mac 175/301, Outlook.com 172/303, Gmail desktop webmail 152/303, Yahoo 125–136/301–303. Outlook Windows at 59 is not a close second-to-last — it is substantially lower than every other tracked client.

**8. React Email current version**
Earlier research noted React Email without a version. The current verified stable version as of 17 March 2026 is `5.2.10`, released that same day. The library is in active production maintenance with a regular patch cadence.

---

COMPLETE
