# Content & UX — Email Doctrine

## Purpose

Guards against content, copy, and structural UX patterns that undermine the effectiveness, trustworthiness, or legibility of transactional and marketing emails. Rendering correctness means nothing if the copy does not communicate clearly or the CTA is not actionable. Rules here apply to template structure, copy patterns, and send-time configuration — not to infrastructure.

## Rule Catalog

---

**[UX-001]** `transactional: mortal | marketing: mortal` — Subject line must be 40–50 characters for mobile-safe display.
> Mobile clients truncate subject lines at 33–41 characters depending on screen width and OS font scaling. The 40–50 character range is the safest cross-client target. Subjects over 60 characters are truncated on all mobile clients. Source: Campaign Monitor Benchmark Data 2023.
> `detect: contextual` — check `subject:` in email.config.yml; flag if over 60 characters; warn if over 50

**[UX-002]** `transactional: mortal | marketing: mortal` — Preheader text must be explicitly set and under 90 characters.
> If no preheader is configured, mail clients pull the first visible body text — often a navigation link or "View in browser" notice. Gmail adjusts preheader width inversely to subject length; target 85–100 combined characters. Source: Litmus "Ultimate Guide to Email Preheader Text" 2022.
> `detect: contextual` — check `preheader:` field in email.config.yml; flag if absent or over 90 chars

**[UX-003]** `transactional: venial | marketing: venial` — Preheader must extend or complement the subject line — never repeat it.
> A preheader that restates the subject wastes the second-highest-value inbox real estate. "Your order is confirmed. Your order is confirmed." Source: Litmus 2022.
> `detect: contextual` — check if preheader and subject text are identical or near-identical

**[UX-004]** `transactional: mortal | marketing: mortal` — All template variables must have fallback values. A naked `{{ first_name }}` or `{{firstName}}` with no fallback sends "Hi , your order..." to thousands of recipients when data is incomplete.
> Merge tag failures are silent — the variable renders as an empty string without errors. Always define fallbacks: `{{ first_name | default: "Valued Customer" }}` (Liquid), `{{#if firstName}}{{firstName}}{{else}}Valued Customer{{/if}}` (Handlebars). Source: Mailchimp Email Marketing Benchmarks 2023.
> `detect: regex` — pattern: `\{\{[\s]*[a-zA-Z_][a-zA-Z0-9_.]*[\s]*\}\}(?!\s*\|)` (output without filter/fallback — check per-engine syntax)

**[UX-005]** `transactional: mortal | marketing: mortal` — CTA button copy must not use generic phrases: "Click here", "Read more", "Learn more", "Submit", "Go now", "Find out more".
> Generic CTA copy is accessibility-hostile (screen readers announce it without context) and performs poorly vs. descriptive alternatives. "Click here" announces as meaningless in link-list navigation. Source: WebAIM "Links and Hypertext" 2023; Campaign Monitor CTA Guide 2022.
> `detect: regex` — pattern: `(?i)>(?:\s*)(click here|read more|learn more|submit|go now|find out more|click to|continue)(?:\s*)<`

**[UX-006]** `transactional: venial | marketing: venial` — CTA copy must be verb-first and 2–5 words.
> "Download the report" beats "Report download" — the first word sets intent. Single words ("Submit", "Go") are too vague. First-person copy ("Get my guide") outperforms second-person ("Get your guide") by 7–14% CTR in published A/B tests. Source: Unbounce Conversion Benchmark Report 2022.
> `detect: contextual` — review CTA button text for verb-first pattern

**[UX-007]** `transactional: venial | marketing: venial` — Transactional emails should have a single primary CTA.
> Every additional CTA reduces the probability of any CTA being clicked — Hick's Law. When multiple CTAs are unavoidable (digest, weekly summary), use visual hierarchy: one button, remaining as smaller text links. Source: Campaign Monitor "Best Email CTA Strategies" 2022.
> `detect: contextual` — count distinct CTA button elements; flag if more than one has equal visual weight

**[UX-008]** `transactional: mortal | marketing: mortal` — Use bulletproof HTML/VML buttons — not image-based buttons.
> Image buttons disappear when images are blocked, and approximately 43% of recipients have images blocked by default in some clients (Litmus "Email Client Market Share" 2023). The CTA is the most important element — it must render without images. Use `<a>` with inline styles + VML Outlook fallback (see RENDER-014).
> `detect: contextual` — check if CTAs use `<a>` or `<img>` as the interactive element

**[UX-009]** `transactional: venial | marketing: venial` — At least one CTA must be visible above the fold without scrolling.
> On mobile, the visible area is approximately the first 500–600px of rendered height. Recipients who do not scroll never see below-fold CTAs. Source: Litmus "Email Design Reference" 2023.
> `detect: contextual` — check that first CTA appears in the first third of template structure

**[UX-010]** `transactional: venial | marketing: venial` — Transactional emails must have one purpose. Order confirmations confirm orders. Shipping notifications confirm shipping. Do not combine with upsell content.
> Multi-purpose transactional emails increase cognitive load at a moment when the user's primary need is task confirmation. Mixing purposes also risks CAN-SPAM reclassification. Source: Litmus "Transactional Email Best Practices" 2023.
> `detect: contextual` — advisory; check template type in email.config.yml against content sections

**[UX-011]** `transactional: venial | marketing: venial` — Lead with the key fact — inverted pyramid structure. State the main point in the first sentence.
> Eye-tracking research (Nielsen Norman Group F-Pattern 2017) confirms that readers scan from the top. The first full sentence after the preheader/header is what Apple Intelligence and Gmail snippets will surface as the summary. Source: Nielsen Norman Group.
> `detect: contextual` — advisory; verify first body sentence contains the key transactional fact

**[UX-012]** `transactional: counsel | marketing: counsel` — Body copy paragraphs must be 3–4 sentences maximum.
> Email is a low-attention medium. Dense paragraphs are read less thoroughly than identical content broken into smaller chunks. Source: Nielsen Norman Group "How Little Do Users Read?" 2020.
> `detect: contextual` — advisory

**[UX-013]** `transactional: venial | marketing: venial` — Do not inject marketing urgency language into transactional emails at anxious moments.
> "Your password was reset. WHILE YOU'RE HERE — CHECK OUT OUR SALE!" treats a security moment as a sales opportunity, erodes trust, and causes recipients to doubt the email's legitimacy. Urgency in transactional email must be factual: "This link expires in 60 minutes." Source: Litmus "Transactional Email Best Practices" 2023.
> `detect: contextual` — check template type against presence of promotional language patterns

**[UX-014]** `transactional: mortal | marketing: mortal` — Critical transactional content — order details, amounts, tracking numbers — must be live text, not embedded in images.
> Images are blocked by default in many corporate email clients. If the order summary is an image, corporate users see a blank white area where their order details should be. Live text is searchable, accessible, and renders without images. Source: Litmus "Images Off in Outlook".
> `detect: contextual` — check that transactional data fields are in text nodes, not only in image assets

**[UX-015]** `transactional: venial | marketing: venial` — Password reset emails must state the link expiry time explicitly.
> "This link expires in 60 minutes" is security information, not urgency marketing. Users who do not act on the email need to know whether to request a new one. Source: OWASP Forgot Password Cheat Sheet 2023.
> `detect: contextual` — check password-reset template type for expiry time copy

**[UX-016]** `transactional: mortal | marketing: mortal` — Unsubscribe link must be clearly visible in the footer — not hidden, minimised, or rendered in low-contrast text.
> Deliberately obscuring the unsubscribe mechanism is a dark pattern flagged by Gmail's spam classifier. It also violates GDPR/ICO requirements for easy unsubscribe access. Source: Google Postmaster Tools documentation 2023; ICO Direct Marketing Guidance 2020.
> `detect: contextual` — check footer for unsubscribe link presence and verify it is not rendered in text smaller than 10px or contrast below 3:1

**[UX-017]** `transactional: venial | marketing: venial` — Transactional emails must include trust signals: company trading name, a reference number, and a support contact method.
> These allow recipients to verify the email is legitimate. An order confirmation without a company name and order number looks like phishing. Source: Litmus "Transactional Email Best Practices" 2023.
> `detect: contextual` — check footer/header for company name and support contact; check template variables include order/reference number

**[UX-018]** `transactional: mortal | marketing: mortal` — Never include full card numbers, bank account numbers, or passwords in email body content.
> Full card numbers are PCI DSS prohibited in email. Passwords must never be sent in plaintext. Show only partial identifiers: last 4 digits of card, masked account numbers. Source: PCI DSS v4.0; OWASP.
> `detect: regex` — pattern: `\b[3-9]\d{13,15}\b` (16-digit sequences suggesting unmasked card numbers)

**[UX-019]** `transactional: counsel | marketing: counsel` — Emoji in subject lines must not be the sole carrier of meaning, and must not exceed one per subject line.
> Enterprise mail gateways strip non-ASCII characters. "🚀 Your shipment" becomes " Your shipment" after stripping. Multiple emoji read as spam to both algorithms and humans. Source: Campaign Monitor 2022.
> `detect: contextual` — check subject line in email.config.yml for emoji usage

**[UX-020]** `transactional: counsel | marketing: counsel` — Left-align body text. Reserve centred alignment for headings and short single-line CTAs only.
> F-pattern scanning (Nielsen Norman Group 2017) relies on a clean left edge. Centred body copy breaks the scan pattern and reduces comprehension for anything over a single line.
> `detect: contextual` — check `text-align` on primary body copy containers

**[UX-021]** `transactional: venial | marketing: venial` — Preheader text must not duplicate the primary `<h1>` heading of the email.
> The preheader is inbox-preview real estate — read before opening. The `<h1>` is the first thing seen after opening. If both are identical the recipient sees the same words twice: once in the inbox list and once at the top of the opened email. This wastes the preheader slot entirely. Compare UX-003, which covers preheader vs subject-line duplication — this rule covers preheader vs in-email heading duplication, which is an equally common failure pattern.
> `detect: contextual` — compare preheader text against the first `<h1>` heading content; flag if they match or differ only in punctuation

---

## Patterns & Code Examples

### Subject + preheader pair (correct)

```yaml
# email.config.yml
subject: "Your order #12345 has shipped"          # 37 chars — mobile safe
preheader: "Arriving Friday. Track your parcel."  # 38 chars — extends subject
```

```yaml
# INCORRECT — preheader repeats subject
subject: "Your order has shipped"
preheader: "Your order has shipped — view your confirmation"  # repetition
```

### Bulletproof button vs image button

```html
<!-- INCORRECT: image button disappears when images are blocked -->
<a href="https://example.com/track/TOKEN">
  <img src="https://cdn.example.com/track-button.png" alt="Track Order" width="200" height="44" />
</a>

<!-- CORRECT: bulletproof HTML button — renders in all clients including Outlook -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
  <tr>
    <td align="center" bgcolor="#0066cc" style="border-radius: 4px; background-color: #0066cc;">
      <!--[if !mso]><!-->
      <a href="https://example.com/track/TOKEN" target="_blank"
         style="display: inline-block; color: #ffffff; font-family: Arial, sans-serif;
                font-size: 16px; font-weight: bold; line-height: 44px;
                text-decoration: none; padding: 0 24px; mso-hide: all;">
        Track Your Order
      </a>
      <!--<![endif]-->
      <!--[if mso]>
      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="https://example.com/track/TOKEN"
                   style="height: 44px; width: 200px; v-text-anchor: middle;"
                   arcsize="9%" stroke="f" fillcolor="#0066cc">
        <w:anchorlock/>
        <center style="color: #ffffff; font-family: Arial, sans-serif; font-size: 16px; font-weight: bold;">
          Track Your Order
        </center>
      </v:roundrect>
      <![endif]-->
    </td>
  </tr>
</table>
```

### Inverted pyramid — order confirmation (correct)

```
WRONG: build to the main point
  "We hope you had a great shopping experience with us today..."
  "Here is a summary of what you ordered..."
  "Your order has been received and is being processed."

CORRECT: lead with the fact
  "Your order #12345 is confirmed."
  "Estimated delivery: Friday, March 20."
  "We'll email you when it ships."
```

### Trust signals — transactional footer pattern

```html
<!-- Transactional email footer: company name, reference, support, address, legal -->
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600">
  <tr>
    <td style="padding: 24px; font-family: Arial, sans-serif; font-size: 12px;
               color: #666666; text-align: center; border-top: 1px solid #e5e5e5;">
      <p style="margin: 0 0 8px;">
        Order reference: <strong>#12345</strong> &mdash;
        Questions? <a href="mailto:support@acme.com"
                      style="color: #0066cc; text-decoration: underline;">support@acme.com</a>
      </p>
      <p style="margin: 0 0 8px;">
        Acme Ltd &mdash; Registered in England &amp; Wales (No. 12345678)<br>
        123 High Street, London EC1A 1BB
      </p>
      <p style="margin: 0;">
        <a href="https://acme.com/unsubscribe/TOKEN"
           style="color: #666666; text-decoration: underline;">Unsubscribe</a> &nbsp;|&nbsp;
        <a href="https://acme.com/privacy"
           style="color: #666666; text-decoration: underline;">Privacy Policy</a>
      </p>
    </td>
  </tr>
</table>
```

### Merge tag fallback patterns — multi-engine reference

```handlebars
{{! Handlebars: conditional fallback }}
Hi {{#if firstName}}{{firstName}}{{else}}Valued Customer{{/if}},

{{! Or using a registered helper }}
Hi {{defaultIfEmpty firstName "Valued Customer"}},
```

```liquid
{# Liquid: default filter #}
Hi {{ first_name | default: "Valued Customer" }},

{# Liquid: capitalize + default #}
Hi {{ first_name | default: "Valued Customer" | capitalize }},
```

```mustache
{{! Postmark Mustache: inverted section fallback }}
Hi {{#first_name}}{{first_name}}{{/first_name}}{{^first_name}}Valued Customer{{/first_name}},
```

```tsx
{/* React Email: TypeScript default prop */}
interface Props { firstName?: string; }
const Email = ({ firstName = 'Valued Customer' }: Props) => (
  <Text>Hi {firstName},</Text>
);
```

### Dark mode copy considerations

Dark mode does not only affect colours — it affects how body copy density reads. Dense, image-heavy emails lose their visual hierarchy in dark mode when background colours invert. Copy-first guidelines:

- Lead with live text for critical information — do not rely on image-embedded text that may become invisible against an inverted background
- Avoid pure-white text on transparent image layers (the layer background inverts, white text on white)
- Preheader text is invisible to recipients — it is inbox metadata. Write it for the inbox list view, not for the open email

### Mobile reading patterns

Over 60% of email opens occur on mobile (Litmus 2023). Mobile-specific copy guidance:

- **Short paragraphs are critical on mobile**: even a 4-sentence paragraph appears wall-of-text on a 375px screen
- **Bold the key fact in each paragraph**: mobile readers scan, not read
- **Stack hierarchy**: on mobile, visual size differences between H1 and body collapse to less than they appear on desktop — use weight and colour to maintain hierarchy when size differentials are compressed
- **Thumb zone for CTAs**: primary CTA in the lower third of a short email lands in the comfortable thumb zone on most smartphones; anchoring it to the top header requires a grip shift

## Legal Requirements Reference

| Requirement | CAN-SPAM (US) | GDPR/UK GDPR (EU/UK) | CASL (Canada) |
|-------------|:---:|:---:|:---:|
| Physical postal address | Required | Not required (but best practice) | Required |
| Working opt-out mechanism | Required (10 business days) | Required (promptly) | Required (10 business days) |
| Honest sender identification | Required | Required | Required |
| Consent for marketing | Not required (opt-out model) | Required (opt-in) | Required (express/implied) |
| Transactional email exempt from opt-out? | Yes (if primarily transactional) | Yes (legitimate interests) | Yes (non-commercial) |
| Implied consent expiry | N/A | N/A | 2 years |

## Pre-Send Content Checklist

Before any email template ships to production, verify:

```
Subject & Preheader
☐ Subject line: 40–50 characters (mobile-safe)
☐ Preheader: explicitly set, under 90 characters
☐ Preheader extends subject — does not repeat it
☐ No spam trigger words in subject (see DELIV-010)
☐ Merge tags tested with fallback values

CTA & Structure
☐ CTA copy is verb-first, descriptive, 2–5 words (not "Click here")
☐ Bulletproof HTML button — not image button
☐ Single primary CTA (or clear visual hierarchy if multiple)
☐ At least one CTA visible above the fold on mobile
☐ Critical content (amounts, order details) in live text, not images

Trust & Legal
☐ Company trading name present
☐ Reference/order number present
☐ Support contact present
☐ Unsubscribe link clearly visible in footer (marketing/subscribed sends)
☐ Physical address in footer (required by CAN-SPAM for commercial sends)
☐ No full card/account numbers
☐ Password reset: link expiry time stated

Copy Quality
☐ Inverted pyramid: key fact in first sentence
☐ Paragraphs: 3–4 sentences maximum
☐ No marketing urgency in transactional context
☐ One purpose per transactional email
```

## Known Afflictions

**Preheader text pulled from body copy** — When no `<preview>` / preheader element is present, or when the preheader is empty, clients pull the first visible text in the email. This is frequently a navigation link ("View in browser"), an `<img>` alt attribute, or an Outlook-specific conditional comment artefact.
Fix: Always set preheader explicitly in both the template element and `email.config.yml`.

**Generic CTA copy passing review** — "Click here" and "Learn more" are so ubiquitous that reviewers stop noticing them. They are invisible to manual review but visible to screen reader users who navigate by links.
Fix: Include CTA copy review in the email QA checklist. Run a regex check for known generic patterns.

**Merge tag failures in production** — Undetected missing data in the send payload renders as empty strings or garbled text ("Hi , your order of £ has been confirmed"). Tests that run with complete data never catch this.
Fix: Test every template with a deliberately incomplete payload where all optional fields are undefined/null. Assert the fallback values render correctly.

**Marketing content injected into transactional triggers** — Teams add promotional banners to high-open-rate transactional emails (order confirmations, shipping updates) without legal review. This can reclassify the email under CAN-SPAM's "primarily commercial" test, imposing marketing opt-out requirements on transactional sends.
Fix: Treat transactional email content as legally distinct from marketing content. Require sign-off before adding promotional content to transactional templates.

## Sources

1. **Campaign Monitor** — https://www.campaignmonitor.com — Benchmark data 2023, CTA Guide, Email Design Fundamentals, subject line best practices.
2. **Litmus** — https://www.litmus.com — State of Email 2023, Transactional Best Practices, Preheader Guide, Email Design Reference.
3. **Nielsen Norman Group** — https://www.nngroup.com — F-Pattern reading (Pernice 2017), How Little Do Users Read (2020), Email Newsletter Usability, Touch Target Sizes (2019).
4. **Unbounce** — https://unbounce.com/conversion-benchmark-report/ — CTA copy A/B test data 2022.
5. **OWASP** — https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html — Password reset expiry requirements.
6. **WebAIM** — https://webaim.org/techniques/hypertext/ — Link text accessibility.
7. **ICO** — https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/ — Direct Marketing Guidance 2020.
8. **FTC CAN-SPAM** — https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business — Commercial email compliance.
