# Email Accessibility & Inclusivity

Comprehensive reference for engineers building inclusive transactional and marketing email systems.
Covers WCAG alignment, screen reader behaviour, semantic HTML patterns, client ARIA support data,
and regulatory context.

Last verified against live sources: 2026-03-17.

---

## Accessibility Checklist

Use this before shipping any email template. Items are ordered by impact.

### Critical (must-fix before send)
- [ ] All images have `alt` attributes — either descriptive text or `alt=""` for decorative images
- [ ] Body text meets WCAG 2.1 AA contrast ratio: 4.5:1 against background
- [ ] Large text (18px+ regular, 14px+ bold) meets 3:1 contrast ratio
- [ ] Interactive elements (buttons, links) meet 3:1 contrast against adjacent colours
- [ ] All layout tables have `role="presentation"` to suppress screen reader table announcements
- [ ] Link text is descriptive — no "click here", "read more", or "learn more" without context
- [ ] Email has a meaningful `<title>` element in `<head>`
- [ ] Logical reading order: source HTML order matches visual reading order

### High priority
- [ ] Heading hierarchy is logical: one `<h1>`, followed by `<h2>`, `<h3>` — no skipped levels
- [ ] Lists use semantic `<ul>` / `<ol>` markup, not manually formatted with hyphens or numbers in `<p>` tags
- [ ] Data tables (if any) have `<th scope="col">` or `<th scope="row">` for column/row headers
- [ ] Minimum font size 14px for body text; 16px preferred
- [ ] Line height at least 1.4 for body text
- [ ] Colour is not the sole means of conveying information (e.g. red error text must also have an icon or label)
- [ ] Language attribute is set: `lang="en"` on the `<html>` element

### Good practice
- [ ] Tap targets at least 44×44px (Apple HIG minimum)
- [ ] 8px minimum spacing between adjacent tap targets
- [ ] Focus indicators not suppressed (`:focus { outline: none; }` is accessible-hostile)
- [ ] Plain-text version is included in MIME multipart and is complete/coherent
- [ ] Decorative images use `alt=""` not `alt=" "` or omitted `alt`
- [ ] No content conveyed only through images of text

---

## ARIA Support in Email Clients

This section summarises verified client support data from Can I Email (caniemail.com), as of
the dates noted per feature. Because support is partial and uneven, use ARIA as progressive
enhancement — ensure the email is fully usable without ARIA, then add ARIA for clients that
honour it.

### role attribute (including role="presentation")

**Overall support: ~73% across tested clients** (caniemail.com/features/html-role/, last
verified 2020-02-04).

| Client | Support | Notes |
|---|---|---|
| Apple Mail (macOS 10.3+, iOS) | Full | role="presentation" suppresses table announcements |
| Gmail (webmail 2019-06+, Android 2020-01+) | Full | |
| Outlook (Windows 2019+, macOS 2019+, mobile) | Full | |
| Outlook Windows Mail (2020-01+) | Full | |
| ProtonMail (2020-03+) | Full | |
| Fastmail (2021-07+) | Full | |
| HEY (2020-06+) | Full | |
| Yahoo! Mail, AOL, Orange, SFR, GMX, WEB.DE, 1&1 | **Partial** | Only works on `<table>` tag — not on `<div>` or other elements |
| Outlook Windows 2007–2016 | No | Classic Word-engine rendering strips/ignores ARIA roles |
| Samsung Email | Limited | Older version data; behaviour unpredictable |

**Key implication**: `role="presentation"` on layout tables is broadly honoured by modern clients
(including Gmail and Outlook 365+) but is **not reliable in Outlook 2007–2016** (Word engine).
Those clients do not announce table structure regardless, so the net effect is still acceptable —
but do not rely on `role` alone to hide content from classic Outlook.

### aria-label

**Overall support: ~58.5%** (caniemail.com/features/html-aria-label/).

| Client | Support |
|---|---|
| Apple Mail (macOS, iOS) | Supported |
| Gmail (webmail, iOS, Android, mobile webmail) | Supported |
| Outlook Windows Mail 2020+ | Supported |
| Outlook macOS 2019+ | Supported |
| Outlook iOS / Android 2019+ | Supported |
| Outlook.com | Mixed (varies by version) |
| Yahoo! Mail, AOL, Orange | Supported |
| ProtonMail, Fastmail, HEY | Supported |
| Mozilla Thunderbird (macOS 60.8+) | Supported |
| Samsung Email (Android 5.0.10.2+) | Supported |
| **Outlook Windows 2007–2019** | **Not supported** |

`aria-label` on links and buttons is the single most impactful ARIA attribute for email
accessibility, but it is stripped entirely by Outlook 2007–2019. Visible link text must be
descriptive without relying on `aria-label` to carry meaning in those clients.

### aria-hidden

**Overall support: ~58.5%** (caniemail.com/features/html-aria-hidden/).

Broadly supported across the same clients as `aria-label`. Notable: Outlook Windows versions
2007–2019 pass `aria-hidden` through without stripping, and it is honoured by the Windows
accessibility layer — making it one of the more reliable ARIA attributes in classic Outlook
environments.

### aria-describedby and aria-labelledby

**Overall support: ~41%** for both (caniemail.com/features/html-aria-describedby/ and
/html-aria-labelledby/).

These attributes depend on `id` references, which creates a critical failure mode in several
clients:

| Client | Behaviour |
|---|---|
| Apple Mail | Supported |
| Outlook Windows Mail 2020+, macOS, iOS/Android | Supported |
| Yahoo!, AOL, Samsung Email, Thunderbird, ProtonMail, HEY | Supported |
| **Gmail (all platforms)** | **Buggy** — Gmail prefixes element `id` values but does not update `aria-describedby`/`aria-labelledby` values, breaking the reference |
| **Fastmail** | **Buggy** — same id-prefix mismatch as Gmail |
| **Outlook.com** | **Buggy** — id-prefix mismatch |
| **Outlook Windows 2007–2019** | `id` attributes stripped entirely; references broken |

**Practical guidance**: Do not use `aria-describedby` or `aria-labelledby` as the primary
accessibility mechanism for content that must be accessible in Gmail, Outlook.com, or Fastmail.
Use `aria-label` instead where a direct label is needed.

### aria-live

**Overall support: ~48.8%** (caniemail.com/features/html-aria-live/).

- Supported in Apple Mail, Gmail, Outlook.com, Yahoo!, most webmail clients.
- **Outlook Windows (2007–2019)**: Code is not stripped, but live region changes cannot be
  triggered — the email content is static so this is rarely relevant.
- **Practical note**: `aria-live` is only meaningful in AMP for Email interactive components.
  In standard static email, there is nothing to announce dynamically. Do not use `aria-live`
  in static email.

---

## Semantic HTML Patterns

### Document Language

Always declare the language on the `<html>` element. Screen readers use this to select the
correct voice/pronunciation engine. Without it, JAWS and NVDA fall back to the system default
language, which may mispronounce non-English content.

```html
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
```

For multilingual emails, use `lang` attributes on individual sections:
```html
<td lang="fr">Bienvenue chez Acme</td>
```

Source: W3C WCAG 2.1 Success Criterion 3.1.1 — Language of Page (Level A). https://www.w3.org/TR/WCAG21/#language-of-page

### Heading Hierarchy

Email headings must follow a logical hierarchy. Screen reader users commonly navigate by
headings; an illogical hierarchy (jumping from `<h1>` to `<h3>`) breaks this navigation pattern.

```html
<!-- CORRECT: logical hierarchy -->
<h1 style="font-family: Arial, sans-serif; font-size: 28px; color: #1a1a1a; margin: 0 0 16px;">
  Order Confirmed
</h1>
<h2 style="font-family: Arial, sans-serif; font-size: 20px; color: #333333; margin: 0 0 12px;">
  Order Summary
</h2>
<h3 style="font-family: Arial, sans-serif; font-size: 16px; color: #444444; margin: 0 0 8px;">
  Shipping Details
</h3>

<!-- WRONG: skips h2, confuses heading navigation -->
<h1>Order Confirmed</h1>
<h3>Order Summary</h3>
```

**Heading count per email**: one `<h1>` per email (the email subject/purpose), multiple `<h2>`
for major sections, `<h3>` for subsections. Never use heading elements purely for visual
sizing — use styled `<p>` or `<span>` instead.

Source: Email on Acid "Email Accessibility Guide" (emailonacid.com); WebAIM "Semantic Structure"
(webaim.org/techniques/semanticstructure/).

### List Markup

Use semantic list elements. Screen readers announce "list, 3 items" for `<ul>`, giving users
structural context. A visually identical list created with `<p>• Item one</p>` receives no
structural announcement.

```html
<!-- CORRECT: semantic list -->
<ul style="margin: 0 0 16px; padding-left: 20px; font-family: Arial, sans-serif;
           font-size: 14px; line-height: 1.5; color: #333333;">
  <li style="margin-bottom: 8px;">Item shipped: Blue Widget x1</li>
  <li style="margin-bottom: 8px;">Expected delivery: Friday, March 20</li>
  <li>Tracking number: 1Z999AA10123456784</li>
</ul>

<!-- CORRECT: ordered steps -->
<ol style="margin: 0 0 16px; padding-left: 20px;">
  <li style="margin-bottom: 8px;">Click the tracking link below</li>
  <li style="margin-bottom: 8px;">Enter your postcode on the carrier site</li>
  <li>Select a redelivery date if needed</li>
</ol>
```

**Known issue**: Outlook 2007–2019 adds unwanted margins to `<ul>` and `<ol>`. Fix with
MSO-specific styles:
```html
<!--[if mso]>
<style>ul, ol { margin-left: 20px !important; }</style>
<![endif]-->
```

Source: Litmus "Accessible Email Design" (litmus.com); Campaign Monitor "HTML Email Best Practices".

### Table Roles

Every layout table must carry `role="presentation"`. Without it, screen readers announce "table,
3 columns, 5 rows" for every structural wrapper — creating significant noise for visually impaired
users.

**Client support caveat** (verified via caniemail.com): `role="presentation"` is fully honoured
by Apple Mail, Gmail, and Outlook 365+/macOS/mobile. Yahoo! Mail, AOL, and similar clients only
honour `role` on `<table>` tags (not `<div>`), which is exactly the use case here — so layout
table suppression works. Outlook Windows 2007–2016 (Word engine) ignores the role attribute, but
those clients do not independently announce table structure, so the practical result is still
correct behaviour.

```html
<!-- Layout table: role="presentation" suppresses screen reader table semantics -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600">
  <tr>
    <td><!-- content --></td>
  </tr>
</table>

<!-- Data table: uses proper scope and th elements -->
<table role="table" border="1" cellpadding="8" cellspacing="0"
       style="border-collapse: collapse; width: 100%;">
  <thead>
    <tr>
      <th scope="col" style="background-color: #f4f4f4; text-align: left;">Item</th>
      <th scope="col" style="background-color: #f4f4f4; text-align: right;">Qty</th>
      <th scope="col" style="background-color: #f4f4f4; text-align: right;">Price</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Blue Widget</td>
      <td style="text-align: right;">1</td>
      <td style="text-align: right;">£24.99</td>
    </tr>
  </tbody>
  <tfoot>
    <tr>
      <th scope="row" colspan="2" style="text-align: right;">Total</th>
      <td style="text-align: right; font-weight: bold;">£24.99</td>
    </tr>
  </tfoot>
</table>
```

Source: W3C WCAG 2.1 Success Criterion 1.3.1 — Info and Relationships (Level A); WebAIM
"Tables" (webaim.org/techniques/tables/); caniemail.com/features/html-role/.

---

## Colour & Contrast

### WCAG 2.1 Contrast Requirements

| Element | WCAG AA | WCAG AAA |
|---|---|---|
| Normal text (< 18px regular, < 14px bold) | 4.5:1 | 7:1 |
| Large text (≥ 18px regular, ≥ 14px bold) | 3:1 | 4.5:1 |
| UI components (buttons, inputs, focus indicators) | 3:1 | n/a |
| Decorative elements, logos, disabled components | No requirement | No requirement |

Source: W3C WCAG 2.1 Success Criterion 1.4.3 — Contrast (Minimum) and 1.4.6 — Contrast (Enhanced).

### Common Colour Pairs

These text/background combinations are commonly used and accessible:

| Text Colour | Background | Ratio | Pass |
|---|---|---|---|
| #333333 (dark grey) | #ffffff (white) | 12.6:1 | AA + AAA |
| #000000 (black) | #ffffff (white) | 21:1 | AA + AAA |
| #ffffff (white) | #0066cc (blue) | 4.6:1 | AA |
| #ffffff (white) | #cc0000 (red) | 4.5:1 | AA (borderline) |
| #666666 (mid grey) | #ffffff (white) | 5.7:1 | AA |
| #767676 (minimum grey) | #ffffff (white) | 4.5:1 | AA (minimum) |
| #999999 (light grey) | #ffffff (white) | 2.9:1 | FAIL |
| #ffffff (white) | #28a745 (green) | 2.9:1 | FAIL |

**#999999 on white fails** — a very common mistake in footer text and secondary labels. Use
#767676 as the minimum grey on white (4.5:1 exactly).

Verification tool: WebAIM Contrast Checker (webaim.org/resources/contrastchecker/).

Source: W3C WCAG 2.1 SC 1.4.3; WebAIM Contrast Checker.

### Non-Colour Information

WCAG 2.1 SC 1.4.1 (Use of Colour, Level A) requires that colour is not the sole means of
conveying information. This affects:

- **Error/success states**: A red border alone is insufficient. Add an icon or explicit label
  ("Error: ..." or "✓ Confirmed").
- **Required fields**: Don't mark required fields with red asterisks alone — add "(required)"
  text.
- **Links in body text**: Underline links or make them bold, not just a different colour. Some
  clients strip colour; some users have colour vision deficiency.
- **Status indicators**: "Green = active, Red = paused" needs a text label alongside.

```html
<!-- Bad: colour only -->
<span style="color: #cc0000;">Your payment failed</span>

<!-- Good: icon + colour + explicit text -->
<span style="color: #cc0000;" aria-label="Error">
  ⚠ Your payment failed. Please update your card details.
</span>
```

Source: W3C WCAG 2.1 Success Criterion 1.4.1 — Use of Colour (Level A).

### Dark Mode Contrast

When designing for `prefers-color-scheme: dark`, re-verify contrast ratios in both modes. A
contrast ratio that passes in light mode may fail in dark mode if only the background changes
and text colour stays the same.

For transactional emails with coloured status badges (e.g. green "Delivered" badge), provide
explicit dark mode colour overrides:

```css
@media (prefers-color-scheme: dark) {
  .badge-delivered {
    background-color: #0a3d1f !important;
    color: #4ade80 !important;
  }
}
```

Source: Litmus "Dark Mode Email Design" (litmus.com/blog/dark-mode-email-design-the-complete-guide).

---

## Alt Text Guidelines

### Informative Images

Alt text for informative images should convey the **purpose or message** of the image, not a
literal description of what's in it.

```html
<!-- Bad: describes the image visually -->
<img src="checkmark.png" alt="Green circle with white checkmark inside" />

<!-- Good: conveys the meaning -->
<img src="checkmark.png" alt="Order confirmed" />

<!-- Bad: redundant with caption -->
<img src="product.jpg" alt="Photo of blue widget" />
<p>Blue Widget — £24.99</p>

<!-- Good: alt adds context the caption doesn't -->
<img src="product.jpg" alt="Blue Widget shown in packaging" />
<p>Blue Widget — £24.99</p>
```

**Maximum alt text length**: aim for under 100 characters. Screen readers read alt text inline
with surrounding content; very long alt text disrupts the reading flow. For complex images
(charts, diagrams), provide a text alternative below the image instead.

Source: WebAIM "Alternative Text" (webaim.org/techniques/alttext/); W3C WCAG 2.1 SC 1.1.1 —
Non-text Content (Level A).

### Decorative Images

Images that are purely decorative (spacers, dividers, background textures, decorative borders)
must have `alt=""` (empty string — no space). Screen readers skip elements with empty alt.

**Never omit the `alt` attribute entirely** — missing `alt` causes screen readers to announce
the filename ("one-pixel-spacer-dot-gif"), which is meaningless and disruptive.

**Never use `alt=" "` (a space)** — a single space character is not treated as empty by all
screen readers; some will announce it as a pause or unlabelled image.

```html
<!-- Decorative divider: empty alt -->
<img src="divider.png" width="600" height="2" alt=""
     style="display: block; border: 0;" />

<!-- Spacer: empty alt -->
<img src="spacer.gif" width="1" height="16" alt=""
     style="display: block; border: 0;" />
```

Source: WebAIM "Alternative Text"; W3C WCAG 2.1 SC 1.1.1.

### Icon Buttons and Linked Images

When an image is wrapped in an `<a>` link with no accompanying visible text, the alt text
becomes the accessible name of the link.

```html
<!-- Bad: screen reader announces "link, image" -->
<a href="https://twitter.com/acme" target="_blank">
  <img src="twitter-icon.png" width="24" height="24" />
</a>

<!-- Good: alt text is the link's accessible name -->
<a href="https://twitter.com/acme" target="_blank"
   style="text-decoration: none;">
  <img src="twitter-icon.png" width="24" height="24"
       alt="Acme on Twitter" style="display: block; border: 0;" />
</a>
```

If an image is linked alongside visible text (e.g. a logo beside the company name), use
`alt=""` on the image to avoid double-announcing:

```html
<a href="https://acme.com">
  <img src="logo.png" width="150" alt="" style="vertical-align: middle;" />
  <span style="font-size: 18px; font-weight: bold;">Acme</span>
</a>
```

Source: W3C WCAG 2.1 SC 1.1.1; WebAIM "Alternative Text".

### Complex Images (Charts, Infographics)

For charts or data visualisations in email (rare but used in reports/digests):

```html
<!-- Short alt + long description below -->
<img src="quarterly-revenue-chart.png" width="580" alt="Q1–Q4 2025 revenue chart"
     style="display: block; border: 0;" />
<p style="font-size: 12px; color: #666666; margin: 8px 0 0;">
  Chart description: Revenue grew from £1.2M in Q1 to £2.1M in Q4, with a dip to £0.9M
  in Q2 due to seasonal factors.
</p>
```

This satisfies WCAG SC 1.1.1 (non-text content) by providing the same information in text form.

Source: W3C WCAG 2.1 SC 1.1.1; Deque "Alt Text Best Practices" (dequeuniversity.com).

---

## Typography & Interaction

### Font Size Minimums

- **Body text**: 14px minimum; 16px preferred. iOS Mail auto-inflates fonts below 13px,
  potentially breaking layouts (Email on Acid, 2022).
- **Heading H1**: 22–32px. H2: 18–22px. H3: 16–18px.
- **Secondary/footer text**: 12px is acceptable for legal/address text, but verify 4.5:1
  contrast — small grey text on white commonly fails.
- **Avoid `pt` units** — they render inconsistently across clients. Use `px`.

Source: Email on Acid "Mobile Email Rendering" (2022); W3C WCAG 2.1 SC 1.4.4 — Resize Text
(Level AA).

### Line Height and Spacing

WCAG 2.1 SC 1.4.12 (Text Spacing, Level AA) specifies that content must remain accessible when:
- Line height set to at least 1.5× font size
- Letter spacing set to at least 0.12× font size
- Word spacing set to at least 0.16× font size

In practice for email: set `line-height: 1.5` on body text. This improves readability for users
with dyslexia, cognitive disabilities, and low vision.

```html
<p style="font-family: Arial, sans-serif; font-size: 16px; line-height: 1.5;
          color: #333333; margin: 0 0 16px;">
  Your order #12345 has been confirmed and will ship by Thursday, March 20.
</p>
```

Source: W3C WCAG 2.1 SC 1.4.12 — Text Spacing (Level AA).

### Tap Target Size

- Minimum 44×44px per Apple Human Interface Guidelines (iOS/iPadOS)
- Minimum 48×48dp per Google Material Design (Android)
- At least 8px spacing between adjacent interactive elements

For email buttons, ensure the `<a>` tag has sufficient `padding` to create the tap target —
not the outer container:

```html
<a href="https://example.com/confirm"
   style="display: inline-block;
          font-family: Arial, sans-serif; font-size: 16px; font-weight: bold;
          color: #ffffff; text-decoration: none;
          background-color: #0066cc;
          padding: 14px 24px;   /* 14px top/bottom + 16px font = 44px height */
          border-radius: 4px;
          line-height: 1;">
  Confirm Order
</a>
```

With 16px font and `line-height: 1` plus `padding: 14px 0`, total height = 16 + 28 = 44px —
meets Apple HIG minimum exactly. Use `padding: 16px 24px` to add a comfortable margin.

Source: Apple HIG "Layout" (developer.apple.com/design/human-interface-guidelines/layout);
Google Material Design "Accessibility" (m3.material.io).

### Focus and Hover States

Email clients that render in a browser context (webmail: Gmail, Outlook.com, Yahoo Mail)
support `:hover` and `:focus` CSS pseudo-classes. Include them in the `<style>` block for
improved interactive accessibility:

```css
/* Hover and focus states for webmail clients */
a:hover { text-decoration: underline !important; }
.cta-button:hover { background-color: #0052a3 !important; opacity: 0.9; }
.cta-button:focus { outline: 3px solid #0066cc; outline-offset: 2px; }
```

Never use `outline: none` or `outline: 0` without providing an alternative focus indicator.

Source: W3C WCAG 2.1 SC 2.4.7 — Focus Visible (Level AA).

---

## Screen Reader Behaviour

### VoiceOver (macOS / iOS) with Apple Mail

Apple Mail provides one of the best email accessibility experiences. VoiceOver announces:
- Email `<title>` as the document title
- Heading levels (H1, H2, H3) with heading navigation (H key)
- List items with count ("list, 3 items")
- Link destinations on request
- `alt` text for images; skips images with `alt=""`
- Reads `role="presentation"` tables silently (no table structure announced) — full support
  confirmed via caniemail.com
- Reads data tables with column/row header relationships from `scope` attributes
- Honours `aria-label`, `aria-hidden`, `aria-describedby`, `aria-labelledby`, and `aria-live`

**Known issue with Apple Mail**: Auto-detected data (phone numbers, addresses, dates) are
announced as interactive links. Use `<a x-apple-data-detectors="false">` or the CSS reset
`a[x-apple-data-detectors] { color: inherit !important; text-decoration: none !important; }`
to suppress.

Source: Litmus "Accessible Email: VoiceOver Testing" (2022); caniemail.com ARIA feature pages.

### JAWS (Windows) with Outlook

JAWS + Outlook is the most common screen reader/client combination in enterprise environments.
Key behaviours vary significantly by Outlook version:

**Outlook 365 / Windows Mail / macOS Outlook (2019+)**:
- `role="presentation"` honoured — layout table structure not announced
- `aria-label` supported
- `aria-hidden` supported
- `aria-labelledby` / `aria-describedby` supported (id references intact)

**Outlook Windows 2007–2019 (Word rendering engine)**:
- `role` attribute ignored — but Word engine does not announce table structure independently,
  so layout tables are still not announced as tables (different mechanism, same result)
- `aria-label` **stripped** — visible link/button text is the only accessible name
- `aria-hidden` passed through and honoured by Windows accessibility layer
- `aria-labelledby` / `aria-describedby` broken — `id` attributes are stripped, breaking
  cross-references
- **Heading navigation**: Supported via H key; JAWS announces heading level for `<h1>`–`<h6>`
- **Image alt text**: Announced. Skips `alt=""`. Announces filename if `alt` is omitted
- **Link text**: JAWS Links List (Insert+F7) lists all links — every link must have
  descriptive visible text, not just `aria-label`
- **Reading order**: JAWS reads in DOM order; ensure source order matches visual reading order

**Critical Outlook-specific issue**: Outlook may render hidden text (including preheader text)
even if `display: none` is applied in some configurations. Use the full preheader hiding
technique to prevent preheader content from being read by JAWS:

```html
<span style="display:none; visibility:hidden; opacity:0; color:transparent;
             height:0; width:0; font-size:0; mso-hide:all;">
  Preheader text here
</span>
```

Source: Deque "Email Accessibility and JAWS" (dequeuniversity.com); caniemail.com ARIA feature pages.

### NVDA (Windows) with Thunderbird / Gmail Chrome

NVDA + Thunderbird uses the Gecko engine's accessibility tree; NVDA + Gmail in Chrome uses
Chromium's. Both provide good heading and link navigation.

- **NVDA Browse Mode**: Users navigate by headings (H), links (K), and form controls (F).
  Ensure all interactive elements are reachable via keyboard.
- **Forms in email**: NVDA enters Forms Mode when focus reaches a form control. AMP for Email
  interactive forms must be keyboard-navigable and ARIA-labelled.
- **aria-live regions**: Supported in NVDA + Chrome (Gmail webmail), but most email clients
  strip ARIA from the email before rendering. Do not rely on live regions for email
  notifications. `aria-live` in static email has no effect.

Source: Email on Acid "Screen Reader Testing in Email".

### TalkBack (Android) with Gmail App

TalkBack on Android reads email content within the Gmail app. Key constraints:

- Gmail app uses a custom rendering engine; some ARIA attributes are stripped.
- `aria-label` is supported in Gmail Android (confirmed caniemail.com). `aria-labelledby`
  and `aria-describedby` are buggy due to Gmail's id-prefixing behaviour.
- Headings are announced if semantic `<h1>`–`<h6>` elements are used (not styled `<div>`
  or `<td>`).
- Images without `alt` attributes have their `src` URL announced — ensure all images have `alt`.
- Tap targets below 44px are difficult to activate via TalkBack's touch exploration mode.
- Two-finger swipe navigation jumps between elements; short descriptive link text is critical.

Source: Email on Acid "Mobile Email Accessibility" (2022); caniemail.com ARIA feature pages.

---

## Regulatory Context

### WCAG 2.1 and Email

The Web Content Accessibility Guidelines (WCAG) 2.1 apply to web content and are widely
referenced for email accessibility, though they were authored for web pages. The most relevant
success criteria for email are:

| Criterion | Level | Relevance to Email |
|---|---|---|
| 1.1.1 Non-text Content | A | Alt text for all images; empty alt for decorative |
| 1.3.1 Info and Relationships | A | Semantic structure, heading hierarchy, table markup |
| 1.3.2 Meaningful Sequence | A | Reading order matches DOM order |
| 1.4.1 Use of Colour | A | Colour not sole conveyor of information |
| 1.4.3 Contrast (Minimum) | AA | 4.5:1 body text, 3:1 large text |
| 1.4.4 Resize Text | AA | Text scalable to 200% without loss of content |
| 1.4.12 Text Spacing | AA | Line height ≥ 1.5, letter/word spacing |
| 2.4.4 Link Purpose | A | Descriptive link text |
| 3.1.1 Language of Page | A | `lang` attribute on `<html>` |
| 4.1.2 Name, Role, Value | A | Semantic HTML roles; ARIA where client supports it |

WCAG 2.2 (published October 2023) added SC 2.4.11 (Focus Appearance) and 2.4.12 (Focus
Appearance Enhanced) — focus styles must meet specific size and contrast requirements. These
are primarily relevant for interactive AMP emails.

Source: W3C WCAG 2.1 (w3.org/TR/WCAG21/); W3C WCAG 2.2 (w3.org/TR/WCAG22/).

### European Accessibility Act (EAA)

The **European Accessibility Act** (Directive 2019/882) came into force for businesses in
EU member states on **28 June 2025**. It requires that digital products and services —
including email communications from e-commerce and financial services companies — meet
accessibility requirements aligned with EN 301 549, which references WCAG 2.1 Level AA for
web/digital content.

**Who is affected**: Businesses in the EU providing consumer-facing products and services
including online shops, banking, e-tickets, transport, and media services. B2B communications
are broadly exempt, but B2C transactional emails (receipts, order confirmations) from covered
sectors are within scope.

**Post-June 2025 status**: The EAA deadline has now passed (as of the date of this document).
Covered businesses are required to comply. Enforcement is by EU member state national
authorities; enforcement timelines and penalties vary by country. German, French, and Dutch
implementations are active. Small businesses with fewer than 10 employees and annual turnover
below €2M may qualify for an exemption — check national implementation for your jurisdiction.

**Practical impact for transactional email**: WCAG 2.1 AA is the minimum baseline. The EAA
does not specifically enumerate email, but the consensus in legal and accessibility guidance
(AbilityNet, Deque, Government Digital Service) is that all digital customer communications
from covered organisations are in scope.

Source: European Commission EAA implementation guidance (ec.europa.eu/social/eaa);
AbilityNet "EAA Guide for Businesses" (2023/2025 update).

### ADA (US) — Section 508 and Title III

The Americans with Disabilities Act (ADA) Title III has been interpreted by courts to apply
to websites and digital communications of "places of public accommodation". Robles v.
Domino's Pizza (9th Circuit, 2019) established that digital accessibility lawsuits are
actionable under ADA Title III.

**Section 508** applies specifically to US federal agencies and their contractors — it
requires WCAG 2.0 AA compliance for ICT (including email).

**For private businesses**: There is no explicit federal email accessibility law, but email
that is part of a public-facing service is potentially subject to ADA Title III litigation.
WCAG 2.1 AA is the de facto standard cited in settlements and consent decrees.

Source: ADA.gov "Guidance on Web Accessibility and the ADA" (2022); Section508.gov
"ICT Standards and Guidelines".

### AODA (Canada — Ontario)

The Accessibility for Ontarians with Disabilities Act (AODA) Information and Communication
Standard requires that public-facing digital content meets WCAG 2.0 Level AA. This includes
email communications from organisations with 50+ employees in Ontario.

Source: Ontario AODA Integrated Accessibility Standards Regulation O. Reg. 191/11.

### Key Practical Takeaway

For teams building transactional email:
- Target **WCAG 2.1 Level AA** as the baseline — this satisfies EAA, Section 508, AODA,
  and positions for ADA defence.
- The EAA deadline of 28 June 2025 has passed; EU-facing transactional email must now comply.
- Level AAA (7:1 contrast, sign language interpretation) is aspirational but not required.
- Document your accessibility testing process — evidence of good-faith compliance effort is
  relevant in dispute resolution.

---

## Code Patterns

### Accessible Button (Full Pattern)

```html
<table role="presentation" border="0" cellpadding="0" cellspacing="0"
       style="margin: 0 auto;">
  <tr>
    <td align="center" bgcolor="#0066cc"
        style="border-radius: 4px; background-color: #0066cc;">
      <!--[if mso]>
      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                   xmlns:w="urn:schemas-microsoft-com:office:word"
                   href="https://example.com/confirm"
                   style="height:48px; v-text-anchor:middle; width:220px;"
                   arcsize="10%" stroke="f" fillcolor="#0066cc">
        <w:anchorlock/>
        <center style="color:#ffffff; font-family:Arial,sans-serif;
                        font-size:16px; font-weight:bold;">
          Confirm Your Order
        </center>
      </v:roundrect>
      <![endif]-->
      <!--[if !mso]><!-->
      <a href="https://example.com/confirm"
         target="_blank"
         aria-label="Confirm Your Order #12345"
         style="display: inline-block; color: #ffffff;
                font-family: Arial, sans-serif; font-size: 16px; font-weight: bold;
                text-decoration: none; padding: 14px 28px;
                border-radius: 4px; background-color: #0066cc; mso-hide: all;">
        Confirm Your Order
      </a>
      <!--<![endif]-->
    </td>
  </tr>
</table>
```

Notes:
- `aria-label` provides additional context (order number) for screen readers in clients that
  support it (Apple Mail, Gmail, Outlook 365+). In Outlook Windows 2007–2019, `aria-label` is
  stripped — the visible "Confirm Your Order" text must be descriptive enough on its own
- `padding: 14px 28px` with 16px font = 44px height (meets Apple HIG minimum)
- `color: #ffffff` on `#0066cc` = 4.6:1 contrast ratio (passes WCAG AA)
- The MSO VML block is used for Outlook Windows 2007–2019; the `<a>` block handles all other clients

Source: Campaign Monitor "Bulletproof Buttons"; W3C WAI-ARIA spec (w3.org/TR/wai-aria/).

### Accessible Data Table

```html
<table role="table" border="0" cellpadding="0" cellspacing="0" width="100%"
       style="border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px;">
  <caption style="text-align: left; font-weight: bold; font-size: 16px;
                  color: #1a1a1a; margin-bottom: 12px; caption-side: top;">
    Order Summary — #12345
  </caption>
  <thead>
    <tr style="background-color: #f4f4f4;">
      <th scope="col" style="padding: 12px; text-align: left; border-bottom: 2px solid #dddddd;
                              color: #333333; font-weight: bold;">
        Item
      </th>
      <th scope="col" style="padding: 12px; text-align: center; border-bottom: 2px solid #dddddd;
                              color: #333333; font-weight: bold;">
        Qty
      </th>
      <th scope="col" style="padding: 12px; text-align: right; border-bottom: 2px solid #dddddd;
                              color: #333333; font-weight: bold;">
        Price
      </th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="padding: 12px; border-bottom: 1px solid #eeeeee; color: #333333;">
        Blue Widget
      </td>
      <td style="padding: 12px; text-align: center; border-bottom: 1px solid #eeeeee; color: #333333;">
        2
      </td>
      <td style="padding: 12px; text-align: right; border-bottom: 1px solid #eeeeee; color: #333333;">
        £49.98
      </td>
    </tr>
  </tbody>
  <tfoot>
    <tr style="background-color: #f9f9f9;">
      <th scope="row" colspan="2"
          style="padding: 12px; text-align: right; font-weight: bold; color: #1a1a1a;">
        Total
      </th>
      <td style="padding: 12px; text-align: right; font-weight: bold; color: #1a1a1a;">
        £49.98
      </td>
    </tr>
  </tfoot>
</table>
```

Notes:
- `<caption>` gives the table an accessible name without needing `aria-label`
- `scope="col"` on header cells enables cell-to-header associations in screen readers
- `scope="row"` on the "Total" cell in `<tfoot>` identifies it as a row header
- `role="table"` overrides any `role="presentation"` that might be inherited from a parent table

Source: WebAIM "Tables" (webaim.org/techniques/tables/); W3C WCAG 2.1 SC 1.3.1.

### Language Switcher for Multilingual Emails

```html
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<body>
  <!-- English section -->
  <div lang="en">
    <p>Your order has been confirmed.</p>
  </div>

  <!-- French section with explicit lang override -->
  <div lang="fr">
    <p>Votre commande a été confirmée.</p>
  </div>
</body>
```

Screen readers select pronunciation rules based on `lang` — French text with `lang="en"` is
mispronounced in most TTS engines.

Source: W3C WCAG 2.1 SC 3.1.1 — Language of Page; SC 3.1.2 — Language of Parts (Level AA).

---

## Sources

1. **W3C WCAG 2.1** — w3.org/TR/WCAG21/
   Primary reference for all success criteria, levels, and definitions. Used throughout.

2. **W3C WCAG 2.2** — w3.org/TR/WCAG22/
   New criteria including Focus Appearance (2.4.11, 2.4.12). Used in Regulatory Context.

3. **Can I Email** — caniemail.com
   - html-role: caniemail.com/features/html-role/ (verified 2026-03-17)
   - html-aria-label: caniemail.com/features/html-aria-label/
   - html-aria-hidden: caniemail.com/features/html-aria-hidden/
   - html-aria-describedby: caniemail.com/features/html-aria-describedby/
   - html-aria-labelledby: caniemail.com/features/html-aria-labelledby/
   - html-aria-live: caniemail.com/features/html-aria-live/
   Used for the ARIA client support matrix. Data last tested dates vary per feature
   (2019–2022); treat as directionally accurate; re-verify for new client versions.

4. **WebAIM** — webaim.org
   - "Alternative Text" (webaim.org/techniques/alttext/)
   - "Semantic Structure" (webaim.org/techniques/semanticstructure/)
   - "Tables" (webaim.org/techniques/tables/)
   - Contrast Checker (webaim.org/resources/contrastchecker/)
   Used throughout for pattern guidance and contrast verification.

5. **Email on Acid** — emailonacid.com
   - "Email Accessibility Guide" (2022)
   - "Mobile Email Rendering" (2022)
   - "Screen Reader Testing in Email" (2022)
   Used for client-specific behaviour, mobile font sizes, screen reader notes.

6. **Litmus** — litmus.com
   - "Accessible Email Design" (2022, 2023)
   - "Dark Mode Email Design: The Complete Guide"
   - "VoiceOver Testing in Email"
   Used for accessibility checklist items, VoiceOver behaviour, dark mode guidance.

7. **Deque University** — dequeuniversity.com
   - "Alt Text Best Practices"
   - "Email Accessibility and JAWS"
   Used for alt text guidance and JAWS behaviour.

8. **Apple Human Interface Guidelines** — developer.apple.com/design/human-interface-guidelines/layout
   Used for 44×44pt tap target minimum.

9. **Google Material Design** — m3.material.io/foundations/accessible-design/accessibility-basics
   Used for 48×48dp tap target minimum.

10. **European Commission** — ec.europa.eu/social/eaa
    EAA (Directive 2019/882) implementation guidance. Used for EAA regulatory context.

11. **Section508.gov** — section508.gov
    "ICT Standards and Guidelines". Used for US Section 508 context.

12. **ADA.gov** — ada.gov
    "Guidance on Web Accessibility and the ADA" (2022). Used for ADA Title III context.

13. **Ontario AODA** — ontario.ca/laws/regulation/110191
    Accessibility for Ontarians with Disabilities Act, Integrated Accessibility Standards
    Regulation. Used for AODA context.

14. **W3C WAI-ARIA** — w3.org/TR/wai-aria/
    ARIA roles and properties specification. Used in code patterns section.

---

## TODOs

- [ ] **Re-verify Can I Email ARIA data**: The caniemail.com data for ARIA attributes was
  last tested in 2019–2022. Re-test against current client versions, particularly Gmail
  (id-prefix bug status), Outlook.com, and Fastmail. File: caniemail.com feature pages.

- [ ] **AMP for Email accessibility**: AMP interactive components (forms, accordions)
  introduce focus management requirements, ARIA live regions, and keyboard navigation that
  static email does not need. Research AMP-specific accessibility patterns.

- [ ] **Reduced motion support**: `prefers-reduced-motion` media query should disable
  animations in email for users with vestibular disorders or photosensitivity. Map which
  email clients support it.

- [ ] **PDF receipts vs email**: Some transactional systems offer PDF receipt attachments.
  PDFs have separate accessibility requirements (tagged PDF, reading order, alt text for
  images). If offering PDF receipts, research PDF/UA standard.

- [ ] **Accessible unsubscribe flows**: The unsubscribe landing page is part of the email
  journey and must also meet WCAG 2.1 AA. Consider testing the full flow (email → click →
  unsubscribe page) with screen readers.

- [ ] **EAA national enforcement tracking**: The EAA deadline passed June 2025. Track
  AT, DE, FR, NL enforcement activity specifically for digital communications. Update the
  regulatory section as enforcement precedent develops.

- [ ] **Dyslexia-friendly typography research**: OpenDyslexic and other dyslexia-focused
  fonts have limited evidence for effectiveness, but spacing and font-weight choices do
  matter. Research best practices specific to transactional email for dyslexic readers.

- [ ] **Cognitive accessibility (WCAG 2.2 SC 3.3.7, 3.3.8)**: New WCAG 2.2 criteria around
  redundant entry and accessible authentication are relevant for email-driven authentication
  flows (magic links, OTP emails).

COMPLETE
