# Template patterns

Read only the section for `stack.templating` and the section for the email type being generated.

## Structure by templating language

### mjml

**MJML** — use `<mjml>` / `<mj-body>` / `<mj-section>` / `<mj-column>` structure.
Apply `mj-attributes` defaults block. Use `mj-preview` for preheader.

### handlebars

**Handlebars** — use raw table-based HTML. Register helper stubs in a comment block.
Use `{{#if}}...{{else}}` with meaningful fallbacks. No `@index`/`@first`/`@last`
if `stack.esp == "sendgrid"`. If `stack.esp == "postmark"`, use Mustache sections
only — no `{{#if}}`, `{{#each}}` or helpers (HBS-004). For `mailchimp` or `custom`,
ask the caller which merge syntax applies.

### liquid

**Liquid** — use raw table-based HTML. Apply `default` filter on every output tag.
Use `{% for %}...{% else %}` for item loops. Apply Klaviyo `person.`/`event.extra.`
namespacing if `stack.esp == "klaviyo"`. Apply whitespace control `{%- -%}` inside
table structures.

### react-email

**React Email** — use `@react-email/components` (pin it to an exact version, REMAIL-007) (`Html`, `Head`, `Preview`, `Body`,
`Container`, `Section`, `Text`, `Heading`, `Button`, `Img`, `Hr`). Export a typed
component with explicit prop interface. Include `render()` usage example.
No hooks. No CSS modules.

### maizzle

**Maizzle** — use Tailwind utility classes with table-based structural HTML.
Include front matter block for subject/preheader. No `flex`/`grid` on structural
elements. Confirm `config.production.js` considerations in a comment.

### html

**HTML** — plain table-based HTML with fully inlined styles. No Tailwind, no framework.

## Required sections by email type

Wherever a footer below lists an address, the skill's footer rule governs it: a physical address is required for marketing, and for transactional email only when promotional content is present.

### Order confirmation

Required sections: header, greeting, order summary table, total row,
CTA (track order), footer with unsubscribe + address.

### Shipping notification

Required sections: header, greeting, tracking status, estimated delivery date,
items shipped (condensed), CTA (track shipment), footer.

### Welcome

Required sections: header, greeting, value proposition, single primary CTA,
optional social proof (1–2 items max), footer.

### Password reset

Required sections: header, brief explanation, single CTA (reset link — time-limited),
security notice ("If you didn't request this, ignore this email"), footer.
No order data. No marketing content. Plain and fast.

### Receipt / invoice

Required sections: header, line items table, totals table (subtotal, tax, total),
payment method (last 4 digits), billing address, footer.
