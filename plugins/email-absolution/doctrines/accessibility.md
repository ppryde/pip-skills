# Accessibility — Email Doctrine

## Purpose

Guards against HTML patterns that exclude users with visual, motor, or cognitive disabilities from transactional email content. The European Accessibility Act (EAA) enforcement began in June 2025, making accessibility compliance a legal requirement in EU markets. WCAG 2.1 AA is the target standard. Accessibility rules here apply regardless of client — an inaccessible template fails users across all rendering environments.

## Rule Catalog

---

**[ACCESS-001]** `mortal` — All `<img>` elements must have an `alt` attribute.
> Screen readers announce the filename when `alt` is absent ("one-pixel-spacer-dot-gif"). Omitting `alt` entirely is never correct. Decorative images use `alt=""`. Informative images use descriptive text. Source: WCAG 2.1 SC 1.1.1 — Non-text Content (Level A).
> `detect: regex` — pattern: `<img(?![^>]*\balt=)[^>]*>`

**[ACCESS-002]** `mortal` — Decorative images must use `alt=""` (empty string, not omitted, not a space).
> `alt=" "` (a space) is not treated as empty by all screen readers — some announce it as an unlabelled image or pause. `alt` omitted causes filename announcement. Empty string `alt=""` is the correct signal for decorative content. Source: WebAIM "Alternative Text"; WCAG 2.1 SC 1.1.1.
> `detect: regex` — pattern: `<img[^>]*\balt=["']\s+["'][^>]*>` (alt with only whitespace)

**[ACCESS-003]** `mortal` — All layout `<table>` elements must have `role="presentation"`.
> Without `role="presentation"`, screen readers announce table structure ("table, 3 columns, 5 rows") for every visual layout table, creating noise that obscures actual content. Layout tables must be marked as presentational. Source: WCAG 2.1 SC 1.3.1 — Info and Relationships (Level A); caniemail.com/features/html-role/ (~73% support).
> `detect: regex` — pattern: `<table(?![^>]*\brole=)[^>]*>`

**[ACCESS-004]** `mortal` — `<html>` element must have `lang` attribute set to the primary language of the email.
> Screen readers use the `lang` attribute to select the correct pronunciation engine and language rules. Without it, JAWS and NVDA fall back to the system default, mispronouncing non-English content. Source: WCAG 2.1 SC 3.1.1 — Language of Page (Level A).
> `detect: regex` — pattern: `<html(?![^>]*\blang=)[^>]*>`

**[ACCESS-005]** `mortal` — Body text must meet WCAG 2.1 AA contrast ratio of 4.5:1 against its background.
> Users with low vision or colour vision deficiency cannot read insufficient-contrast text. The WCAG 2.1 AA minimum is 4.5:1 for normal text (under 18px regular or 14px bold). Common failure: `#999999` on white is only 2.9:1 — use `#767676` as the minimum grey on white. Source: WCAG 2.1 SC 1.4.3 — Contrast (Minimum, Level AA).
> `detect: contextual` — verify text colour/background colour combinations against 4.5:1 threshold

**[ACCESS-006]** `mortal` — CTA buttons and interactive elements must meet 3:1 contrast ratio against adjacent colours.
> UI component contrast (buttons, links as distinct from body) requires a minimum 3:1 ratio between the component and adjacent colours per WCAG 2.1. A blue button (`#0066cc`) on white achieves 4.6:1 — compliant. Source: WCAG 2.1 SC 1.4.11 — Non-text Contrast (Level AA).
> `detect: contextual` — check button background vs surrounding background colour ratio

**[ACCESS-007]** `mortal` — Link text must be descriptive without relying on surrounding context.
> "Click here", "read more", and "learn more" are meaningless when a screen reader announces them in isolation (e.g. via link list navigation). Use descriptive text: "Track your order", "Download invoice", "Confirm your email". Source: WCAG 2.1 SC 2.4.6 — Headings and Labels (Level AA); WebAIM "Links and Hypertext".
> `detect: contextual` — check link anchor text for generic phrases

**[ACCESS-008]** `mortal` — Email must have a meaningful `<title>` element in `<head>`.
> Screen readers announce the `<title>` when the email is opened. An absent or generic `<title>` (e.g. "Email") provides no context. Use the email subject or a descriptive title: "Order #12345 Confirmed — Acme". Source: WCAG 2.1 SC 2.4.2 — Page Titled (Level A).
> `detect: regex` — pattern: `<title\s*>(\s*|email\s*|untitled\s*)</title>` (absent or generic title)

**[ACCESS-009]** `venial` — Heading hierarchy must be logical: one `<h1>`, followed by `<h2>`, `<h3>` with no skipped levels.
> Screen reader users navigate by headings. A heading structure that jumps from `<h1>` to `<h3>` or uses headings purely for visual sizing disrupts this navigation pattern. Every email should have exactly one `<h1>`. Source: WCAG 2.1 SC 1.3.1 — Info and Relationships.
> `detect: contextual` — check heading sequence for skipped levels and multiple h1 elements

**[ACCESS-010]** `venial` — Lists must use semantic `<ul>` or `<ol>` markup — not manually formatted with bullets or numbers in `<p>` tags.
> Screen readers announce "list, 3 items" for `<ul>`, giving structural context. A visually identical list created with `<p>• Item one</p>` receives no structural announcement. Outlook 2007–2019 adds unwanted margins to `<ul>`/`<ol>` — correct with MSO styles rather than removing semantic markup. Source: WCAG 2.1 SC 1.3.1.
> `detect: contextual` — check for manually bulleted paragraphs (common patterns: `<p>•`, `<p>-`, `<p>1.`)

**[ACCESS-011]** `venial` — Data tables (order summaries, line items) must use `<th scope="col">` or `<th scope="row">` for header cells.
> Without scope attributes, screen readers cannot associate data cells with their headers, making order summaries and pricing tables inaccessible. Layout tables use `role="presentation"` (ACCESS-003); data tables use `<th>` with `scope`. Source: WCAG 2.1 SC 1.3.1; WebAIM "Tables".
> `detect: contextual` — check if tables containing price/item/quantity data have `<th>` with scope attributes

**[ACCESS-012]** `venial` — Minimum font size for body text is 14px. 16px is preferred.
> iOS Mail auto-inflates fonts below 13px, potentially breaking layouts. Users with low vision rely on adequate base font sizes. `pt` units render inconsistently across email clients — use `px` exclusively. Source: Email on Acid "Mobile Email Rendering" (2022); WCAG 2.1 SC 1.4.4 — Resize Text.
> `detect: regex` — pattern: `font-size\s*:\s*([0-9]+)px` (flag values below 14, excluding footer/legal text)

**[ACCESS-013]** `venial` — Body text must have `line-height` of at least 1.4 (1.5 preferred).
> WCAG 2.1 SC 1.4.12 (Text Spacing, Level AA) specifies that content must remain accessible when line height is set to 1.5× font size. Compact line spacing reduces readability for users with dyslexia, cognitive disabilities, and low vision. Source: WCAG 2.1 SC 1.4.12 — Text Spacing (Level AA).
> `detect: contextual` — check line-height on primary body text paragraphs

**[ACCESS-014]** `venial` — Tap targets must be at least 44×44px.
> Apple Human Interface Guidelines require 44×44px tap targets on iOS. Google Material Design specifies 48×48dp. Email buttons must have sufficient padding on the `<a>` element to meet this size. A CTA with `line-height: 44px` and horizontal padding creates the correct target. Source: Apple HIG; Google Material Design.
> `detect: contextual` — check button `<a>` or `<td>` computed height from line-height and padding

**[ACCESS-015]** `venial` — Colour must not be the sole means of conveying information.
> Users with colour vision deficiency cannot distinguish colour-only signals. Red error text must have an icon or label. Status indicators (active/paused) need text labels, not just colour differences. Link text must be distinguishable from body text via underline or weight, not colour alone. Source: WCAG 2.1 SC 1.4.1 — Use of Colour (Level A).
> `detect: contextual` — check if error states, status badges, and links are distinguishable without colour

**[ACCESS-016]** `venial` — `aria-label` on links and buttons must provide meaningful context in supporting clients.
> `aria-label` overrides the accessible name of an element for screen readers in ~58% of clients. However, Outlook 2007–2019 strips `aria-label` entirely. Visible link text must always be descriptive without relying solely on `aria-label` — it is an enhancement layer, not the primary accessibility mechanism. Source: caniemail.com/features/html-aria-label/ (~58.5% support).
> `detect: contextual` — check if any links rely solely on `aria-label` for their accessible name with no visible descriptive text

**[ACCESS-017]** `venial` — Do not use `aria-describedby` or `aria-labelledby` as the primary accessibility mechanism for Gmail, Outlook.com, or Fastmail audiences.
> Gmail, Fastmail, and Outlook.com prefix element `id` values but do not update `aria-describedby`/`aria-labelledby` references, breaking the reference silently. Outlook 2007–2019 strips `id` attributes entirely. Use `aria-label` directly instead of reference-based ARIA where broad client support is needed. Source: caniemail.com/features/html-aria-describedby/ (~41% support).
> `detect: regex` — pattern: `aria-(?:describedby|labelledby)=`

**[ACCESS-018]** `counsel` — Plain-text MIME version must be a complete, coherent rendering of the HTML content.
> Screen reader users and accessibility tools on corporate mail gateways sometimes default to plain text. A stub ("View this in HTML") fails these users. CAN-SPAM also requires that required content (physical address, opt-out) appears in plain text. Source: WCAG 2.1; CAN-SPAM Act.
> `detect: contextual` — check if email config indicates plain-text version is present and complete

**[ACCESS-019]** `counsel` — Linked images alongside visible text should use `alt=""` to prevent double-announcing.
> When an image is linked alongside visible text (e.g. a logo beside the company name), screen readers will announce both the alt text and the visible text. Use `alt=""` on the image when visible text already provides the link's context. Source: WCAG 2.1 SC 1.1.1; WebAIM "Alternative Text".
> `detect: contextual` — check for linked images with non-empty alt that appear adjacent to link text conveying the same information

**[ACCESS-020]** `counsel` — Outlook 2007–2019 list margin fix should be included when `<ul>` or `<ol>` is present.
> Outlook adds large unwanted margins to lists. The MSO-specific conditional comment fix prevents lists from appearing indented off-screen in some Outlook configurations. Source: standard Outlook pattern.
> `detect: regex` — pattern: `<[uo]l(?![^>]*mso)[^>]*>` (check if MSO list margin fix is present elsewhere in template)

---

## Support Matrix

| Feature | Support | Notes |
|---------|---------|-------|
| `role="presentation"` | ~73% clients | Yahoo/AOL: table only; Outlook 2007–16: ignored (harmless) |
| `aria-label` | ~58.5% | Outlook 2007–19 strips it |
| `aria-hidden` | ~58.5% | More reliable in classic Outlook than aria-label |
| `aria-describedby` | ~41% | Gmail/Fastmail/Outlook.com: id-prefix mismatch breaks references |
| `aria-live` | ~48.8% | Only meaningful in AMP for Email |
| `lang` attribute on `<html>` | All clients | Parsed by screen readers universally |
| `<th scope>` on data tables | All clients | Standard HTML attribute |

## Patterns & Code Examples

### Correct alt text patterns

```html
<!-- Informative image: alt conveys meaning, not appearance -->
<img src="https://cdn.example.com/checkmark.png" width="32" height="32"
     alt="Order confirmed"
     style="display: block; border: 0;" />

<!-- Decorative image: empty alt, screen reader skips it -->
<img src="https://cdn.example.com/divider.png" width="600" height="2"
     alt="" style="display: block; border: 0;" />

<!-- Linked icon: alt text is the link's accessible name -->
<a href="https://twitter.com/acme" target="_blank" style="text-decoration: none;">
  <img src="https://cdn.example.com/twitter.png" width="24" height="24"
       alt="Acme on Twitter" style="display: block; border: 0;" />
</a>
```

### Data table with correct headers

```html
<!-- CORRECT: data table with scope attributes for screen reader association -->
<table role="table" border="1" cellpadding="8" cellspacing="0"
       style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; font-size: 14px;">
  <thead>
    <tr style="background-color: #f4f4f4;">
      <th scope="col" style="text-align: left; padding: 8px; font-weight: bold;">Item</th>
      <th scope="col" style="text-align: right; padding: 8px; font-weight: bold;">Qty</th>
      <th scope="col" style="text-align: right; padding: 8px; font-weight: bold;">Price</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="padding: 8px;">Blue Widget</td>
      <td style="text-align: right; padding: 8px;">1</td>
      <td style="text-align: right; padding: 8px;">£24.99</td>
    </tr>
  </tbody>
  <tfoot>
    <tr>
      <th scope="row" colspan="2" style="text-align: right; padding: 8px;">Total</th>
      <td style="text-align: right; padding: 8px; font-weight: bold;">£24.99</td>
    </tr>
  </tfoot>
</table>
```

### Outlook list margin fix

```html
<!--[if mso]>
<style>ul, ol { margin-left: 20px !important; }</style>
<![endif]-->
<ul style="margin: 0 0 16px; padding-left: 20px; font-family: Arial, sans-serif;
           font-size: 14px; line-height: 1.5; color: #333333;">
  <li style="margin-bottom: 8px;">Blue Widget × 1</li>
  <li style="margin-bottom: 8px;">Expected delivery: Friday, March 20</li>
  <li>Tracking: 1Z999AA10123456784</li>
</ul>
```

### Colour contrast reference

| Text | Background | Ratio | WCAG AA |
|------|-----------|-------|---------|
| `#333333` | `#ffffff` | 12.6:1 | ✅ Pass |
| `#000000` | `#ffffff` | 21:1 | ✅ Pass |
| `#ffffff` | `#0066cc` | 4.6:1 | ✅ Pass |
| `#ffffff` | `#cc0000` | 4.5:1 | ✅ Pass (borderline) |
| `#666666` | `#ffffff` | 5.7:1 | ✅ Pass |
| `#767676` | `#ffffff` | 4.5:1 | ✅ Pass (minimum grey) |
| `#999999` | `#ffffff` | 2.9:1 | ❌ Fail — common error |
| `#ffffff` | `#28a745` | 2.9:1 | ❌ Fail |

> **`#999999` on white is the most common contrast failure in production email** — used frequently for footer text and secondary labels. Replace with `#767676` minimum.

Verification: [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)

### Non-colour information pattern

```html
<!-- INCORRECT: colour only conveys status -->
<span style="color: #cc0000;">Payment failed</span>

<!-- CORRECT: icon + colour + explicit text -->
<span style="color: #cc0000; font-family: Arial, sans-serif; font-size: 14px;"
      aria-label="Error: payment failed">
  ⚠ Payment failed — please update your card details.
</span>

<!-- CORRECT: status badge with text label, not colour alone -->
<span style="background-color: #0a3d1f; color: #4ade80;
             padding: 2px 8px; border-radius: 4px; font-size: 12px;
             font-family: Arial, sans-serif;">
  ✓ Delivered
</span>
```

### Accessible button with correct tap target

```html
<!-- CORRECT: 44px tap target height via line-height, descriptive text -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       style="margin: 0 auto;">
  <tr>
    <td align="center" bgcolor="#0066cc"
        style="border-radius: 4px; background-color: #0066cc;">
      <!--[if !mso]><!-->
      <a href="https://example.com/track/TOKEN" target="_blank"
         style="display: inline-block; color: #ffffff;
                font-family: Arial, sans-serif; font-size: 16px;
                font-weight: bold; line-height: 44px;
                text-decoration: none; padding: 0 24px;
                mso-hide: all;"
         aria-label="Track your order #12345">
        Track Your Order
      </a>
      <!--<![endif]-->
    </td>
  </tr>
</table>
<!-- Note: aria-label is supplementary; visible text "Track Your Order" is already descriptive -->
```

## Known Afflictions

**`aria-label` stripped by Outlook 2007–2019** — Classic Outlook removes `aria-label` attributes from all elements. Accessible names provided only via `aria-label` are lost for this audience. Visible link text must be descriptive.
Affects: Outlook 2007–2019. Source: caniemail.com/features/html-aria-label/.
Fix: Use descriptive visible link text as the primary accessibility mechanism. `aria-label` may supplement but must not be the sole accessible name.

**`aria-describedby` id-prefix mismatch** — Gmail, Fastmail, and Outlook.com prefix element `id` values when processing email HTML, but do not update `aria-describedby` or `aria-labelledby` references. The referenced element becomes unreachable.
Affects: Gmail (all), Fastmail, Outlook.com. Source: caniemail.com/features/html-aria-describedby/.
Fix: Use `aria-label` directly instead of id-reference-based ARIA for cross-client accessibility.

**Outlook `<ul>`/`<ol>` margin** — Outlook 2007–2019 applies large default margins to `<ul>` and `<ol>` elements that override inline styles. Without the MSO conditional comment fix, lists appear heavily indented.
Affects: Outlook 2007–2019. Source: Email on Acid.
Fix: Include `<!--[if mso]><style>ul, ol { margin-left: 20px !important; }</style><![endif]-->`.

**Outlook alt text rendering** — Outlook 2007–2019 displays alt text as visible black text on a white box when images are blocked (the default for many corporate Outlook installs). Alt text that contains internal reference text ("hero-banner-v3-FINAL") becomes the first thing corporate users see. Write alt text as if it will be read aloud and displayed in the email body.
Affects: Outlook 2007–2019 (images blocked by default in many enterprise configurations). Source: Litmus "Images Off in Outlook".
Fix: Write descriptive, user-facing alt text for all informative images. Apply `style="color: #333333; font-family: Arial, sans-serif;"` to img elements so Outlook renders alt text with appropriate styling.

**iOS 13+ forced text sizing** — iOS Mail adjusts font sizes it considers too small, which can cause layout reflow. The `x-apple-disable-message-reformatting` meta tag prevents this but is separate from the `text-size-adjust: 100%` CSS property. Both are required for predictable rendering.
Affects: iOS Mail (iOS 13+). Source: Campaign Monitor iOS email rendering guide.
Fix: Include both `<meta name="x-apple-disable-message-reformatting">` and `-webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;` in the `<style>` block.

### Preheader accessible hiding pattern

```html
<!-- CORRECT: preheader hidden from visual display but available to screen readers -->
<!-- Use max-height:0 + overflow:hidden; do NOT use display:none which hides from AT -->
<div style="display: none; font-size: 1px; color: #fefefe; line-height: 1px;
            font-family: Arial, sans-serif; max-height: 0px; max-width: 0px;
            opacity: 0; overflow: hidden; mso-hide: all;"
     aria-hidden="true">
  Your order #12345 has shipped and will arrive by Friday.
</div>
<!-- aria-hidden="true" prevents double-announcement: preheader content is
     already in the email body — announcing it twice adds noise -->
```

### Skip-link pattern (for long emails)

```html
<!-- CORRECT: skip navigation for long newsletter-style transactional emails -->
<!-- Not required for short single-CTA transactional emails -->
<a href="#main-content"
   style="position: absolute; left: -9999px; top: auto; width: 1px; height: 1px;
          overflow: hidden; font-family: Arial, sans-serif;"
   class="skip-link">
  Skip to main content
</a>
<!-- ... header content ... -->
<div id="main-content">
  <!-- Primary email content starts here -->
</div>
```

## Cognitive Accessibility Notes

WCAG 2.1 SC 3.1.5 (Reading Level, Level AAA) recommends plain language at lower secondary education reading level for broad audiences. Transactional emails are not legally required to meet AAA, but plain language reduces support burden:

- Avoid jargon: "Your order has been dispatched" not "Your parcel has been processed through the logistics fulfilment pipeline"
- One idea per sentence. Active voice.
- Spell out abbreviations on first use: "estimated time of arrival (ETA)"
- Error messages must explain the problem AND the resolution: "Payment failed — your card was declined. Please update your payment details." not "Error code 402."

These are not auditable rules — they are editorial guidance for template authors. The scribe skill applies these when generating email copy.

## Sources

1. **W3C WCAG 2.1** — https://www.w3.org/TR/WCAG21/ — Contrast (1.4.3, 1.4.11), Non-text Content (1.1.1), Language (3.1.1), Info and Relationships (1.3.1), Text Spacing (1.4.12).
2. **caniemail.com** — https://www.caniemail.com — ARIA feature support: role (~73%), aria-label (~58.5%), aria-hidden (~58.5%), aria-describedby (~41%), aria-live (~48.8%).
3. **WebAIM** — https://webaim.org — Alternative text guidance, contrast checker, tables, links.
4. **Email on Acid** — https://www.emailonacid.com — Mobile rendering, font size minimums, Outlook list margins.
5. **European Accessibility Act** — https://ec.europa.eu/social/main.jsp?catId=1480 — Enforcement began June 2025; covers digital products and services including transactional communications.
6. **Apple HIG** — https://developer.apple.com/design/human-interface-guidelines/ — Tap target sizing (44×44px minimum).
7. **Litmus "Images Off in Outlook"** — https://www.litmus.com/blog/the-ultimate-guide-to-email-image-blocking/ — Corporate Outlook image-blocking behaviour and alt text display.
