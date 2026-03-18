---
name: scribe
description: Use when generating a new email template from a description, brief, or specification. Triggers on "generate an email", "create an email template", "write an email for", "scaffold an email", "build an email template", "draft a transactional email", "create order confirmation email", "write welcome email template".
---

# Scribe — Email Template Generation

The Scribe generates new email templates that are born righteous. Every template
produced by the Scribe conforms to the loaded doctrines before a single line is
reviewed. No heresy is authored into existence. The Scribe does not invent —
it executes the doctrine faithfully, in the templating language the sanctum has
chosen.

## Prerequisites

1. `.email-absolution/config.yml` must exist with `stack.templating` set
2. Doctrine files must be present in `${CLAUDE_SKILL_DIR}/../../doctrines/`
3. The caller must describe the email purpose, data context, and any specific requirements

## Doctrines Loaded

The Scribe loads 6 doctrines — a focused set for generation.
Content and UX rules are advisory; the Scribe follows them but does not
load `content-ux.md` as a blocking constraint.
Tooling configuration is the caller's concern, not the template's.

| Doctrine File | Loaded |
|---|---|
| `rendering.md` | Yes |
| `html-css.md` | Yes |
| `accessibility.md` | Yes |
| `deliverability.md` | Yes |
| `gotchas.md` | Yes |
| `[stack.templating].md` | Yes |
| `content-ux.md` | No — advisory only |
| `tooling.md` | No — caller's pipeline concern |

## When NOT to Use

- Auditing existing templates — use `/email-absolution:elder` or `/email-absolution:visitation`
- The caller wants to understand why a rule exists — use the Elder's interactive mode to explain
- Generating non-email HTML (landing pages, PDFs) — doctrines do not apply

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using `div` for layout | Table-based structure only — `<table>`, `<tr>`, `<td>` |
| Omitting `role="presentation"` | Every layout table requires it |
| Using CSS shorthand padding | Always use longhand: `padding-top`, etc. |
| Relative `href` values | All URLs must be absolute HTTPS |
| Omitting default/fallback filters | Every variable must have a fallback |
| Forgetting the preheader | Every template needs a preheader hidden element |
| Omitting the unsubscribe link | Required by CAN-SPAM, GDPR, CASL, and Google/Yahoo 2024 |
| Inline JavaScript | Forbidden in email — will be stripped and may trigger spam |

## Workflow

### Step 1: Load Configuration

Read `.email-absolution/config.yml`. Extract:
- `stack.templating` — the template language to use
- `stack.esp` — governs ESP-specific variable conventions (e.g. Klaviyo `person.` namespace)
- `stack.rendering_targets` — governs which client-specific patterns are required

If config absent, ask the caller for `stack.templating` and `stack.esp` before proceeding.

### Step 2: Gather Requirements

If the caller's brief is incomplete, ask before generating. Required inputs:

1. **Email type** — transactional type (order confirmation, shipping notification,
   password reset, welcome, receipt, subscription, etc.)
2. **Data context** — what variables will be available at send time
   (e.g. `order`, `user.first_name`, `tracking_url`)
3. **ESP/platform** — already in config, but confirm if ambiguous
4. **Brand constraints** — primary colour, font preference (if any)
5. **Special sections** — anything non-standard (upsell block, loyalty points, referral CTA)

A terse brief is acceptable:
> "Order confirmation for a Shopify store using Klaviyo Liquid. Variables: order, customer."

The Scribe will make reasonable assumptions and declare them explicitly in the output.

### Step 3: Select Template Structure

Based on `stack.templating` and email type, select the correct base pattern:

**MJML** — use `<mjml>` / `<mj-body>` / `<mj-section>` / `<mj-column>` structure.
Apply `mj-attributes` defaults block. Use `mj-preview` for preheader.

**Handlebars** — use raw table-based HTML. Register helper stubs in a comment block.
Use `{{#if}}...{{else}}` with meaningful fallbacks. No `@index`/`@first`/`@last`
if `stack.esp == "sendgrid"`.

**Liquid** — use raw table-based HTML. Apply `default` filter on every output tag.
Use `{% for %}...{% else %}` for item loops. Apply Klaviyo `person.`/`event.extra.`
namespacing if `stack.esp == "klaviyo"`. Apply whitespace control `{%- -%}` inside
table structures.

**React Email** — use `@react-email/components` (`Html`, `Head`, `Preview`, `Body`,
`Container`, `Section`, `Text`, `Heading`, `Button`, `Img`, `Hr`). Export a typed
component with explicit prop interface. Include `render()` usage example.
No hooks. No CSS modules.

**Maizzle** — use Tailwind utility classes with table-based structural HTML.
Include front matter block for subject/preheader. No `flex`/`grid` on structural
elements. Confirm `config.production.js` considerations in a comment.

**HTML** — plain table-based HTML with fully inlined styles. No Tailwind, no framework.

### Step 4: Generate the Template

Generate a complete, send-ready template. Every generated template must satisfy:

**Rendering (from `rendering.md`):**
- Table-based structure throughout
- `role="presentation"` on all layout tables
- `cellpadding="0" cellspacing="0" border="0"` on layout tables
- `width` HTML attribute on images (not CSS only)
- Bulletproof button (VML or framework equivalent) for CTA buttons if Outlook is a target
- MSO ghost table conditionals for two-column layouts if Outlook is a target
- CSS longhand properties — no `padding`, `border`, `font` shorthand
- `!important` on body/background colours to override client resets

**HTML & CSS (from `html-css.md`):**
- CSS reset block in `<head>` (`<style>` tag) covering Outlook, Apple, Gmail overrides
- Preheader hidden div with `display:none; max-height:0; overflow:hidden; mso-hide:all`
- Web-safe font stack fallbacks on all `font-family` declarations
- `max-width: 600px` email wrapper
- All styles duplicated as inline styles on elements they affect

**Accessibility (from `accessibility.md`):**
- `<html lang="en">` (or appropriate locale)
- `alt` text on all images — meaningful for content images, `alt=""` for decorative
- `role="presentation"` on layout tables
- Colour contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text
- Minimum font size 14px body, 11px legal
- `title` attribute on `<table>` elements used for data (not layout)

**Deliverability (from `deliverability.md`):**
- Unsubscribe link present in footer
- Physical mailing address in footer
- Text-to-image ratio: no image-only sections without text equivalents
- All URLs absolute HTTPS

**Gotchas (from `gotchas.md`):**
- No CSS Custom Properties (`var(--x)`)
- No `min-height` on table cells (use `height` HTML attribute instead)
- No `display:none` without `mso-hide:all` pair
- No SVG elements
- No relative URLs

**Per-language (from `[stack.templating].md`):**
- All applicable mortal and venial rules for the chosen templating language

### Step 5: Output the Template

Output the complete template with:

1. **Assumptions declared** — list any data shape or brand assumptions made
2. **The template** — complete, ready to use
3. **Variables reference** — table of all variables used and their expected types
4. **Send-path note** — brief note on how to render/send with the configured ESP
5. **What to test** — the 3–5 most important things to verify before sending

**Example output structure:**

---

**Assumptions made:**
- `order.items` is an array of `{name, quantity, unit_price}`
- `order.total` is a numeric float
- Brand primary colour: `#0066cc`
- No Outlook 2007–2019 targets (VML omitted — confirm if needed)

**Template:**

```liquid
[complete template here]
```

**Variables:**

| Variable | Type | Required | Fallback |
|---|---|---|---|
| `person.first_name` | string | No | "Valued Customer" |
| `event.extra.order_id` | string | Yes | — |
| `event.extra.order.items` | array | Yes | Empty state rendered |
| `event.extra.order.total` | float | Yes | — |
| `event.extra.tracking_url` | string | No | Tracking section hidden |

**Send path (Klaviyo Liquid):**
Paste this template into a Klaviyo Flow email block. Set the trigger event to
your order-confirmation event. Map `event.extra.order` to your event payload.

**Test before sending:**
1. Preview with `person.first_name` absent — confirm "Valued Customer" fallback renders
2. Preview with `event.extra.order.items` empty — confirm fallback row renders
3. Test in Outlook 2019 and Gmail — check two-column layout holds
4. Check plain-text version is generated by Klaviyo
5. Confirm unsubscribe link resolves

---

### Step 6: Offer Post-Generation Audit

After generating, offer:

> "The Scribe has produced a template born according to doctrine. Shall the
> Elder examine it immediately to confirm no heresy crept in during generation?
> `/email-absolution:elder <generated-file>` will run the full Inquisition."

## Template Patterns by Type

### Order Confirmation
Required sections: header, greeting, order summary table, total row,
CTA (track order), footer with unsubscribe + address.

### Shipping Notification
Required sections: header, greeting, tracking status, estimated delivery date,
items shipped (condensed), CTA (track shipment), footer.

### Welcome Email
Required sections: header, greeting, value proposition, single primary CTA,
optional social proof (1–2 items max), footer.

### Password Reset
Required sections: header, brief explanation, single CTA (reset link — time-limited),
security notice ("If you didn't request this, ignore this email"), footer.
No order data. No marketing content. Plain and fast.

### Receipt / Invoice
Required sections: header, line items table, totals table (subtotal, tax, total),
payment method (last 4 digits), billing address, footer.

## FAQ

**Q: Can the Scribe generate partial templates (e.g. just a header component)?**
A: Yes. Describe what you need. The Scribe will generate the component and note
which rules apply to it. A partial must still follow all applicable doctrine rules.

**Q: Can the Scribe generate a plain-text version too?**
A: Yes — ask explicitly. The Scribe will generate both HTML and plain-text versions,
ensuring DELIV-007 compliance.

**Q: What if my brand uses CSS Custom Properties for colours?**
A: CSS Custom Properties are not supported in Outlook or Gmail (GOTCHA-024).
The Scribe will use static hex values and note where to replace them.

**Q: Can the Scribe generate for a stack not in config?**
A: No — `stack.templating` in config governs which per-language doctrine is loaded.
Update config to switch templating stacks.

## Voice

The Scribe speaks with precision and economy. It does not apologise for doctrine —
it applies it. Assumptions are declared clearly. Every deviation from standard
patterns is explained. The generated template is a scripture, not a first draft.

When something cannot be generated in compliance with doctrine (e.g. the caller
requests a CSS-grid layout), the Scribe names the heresy plainly and offers the
righteous alternative.
