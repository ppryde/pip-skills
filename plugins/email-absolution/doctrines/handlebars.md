# Handlebars — Email Doctrine

## Purpose

Rules and gotchas for engineers building transactional email templates with Handlebars.js, or the Handlebars subsets used by SendGrid Dynamic Templates and Mandrill. Covers data safety, helper patterns, and the critical differences between full Handlebars.js and the restricted subsets exposed by ESPs.

## Rule Catalog

---

**[HBS-001]** `transactional: mortal | marketing: mortal` — All template variables must have fallback values. No variable should render as an empty string silently.
> `{{firstName}}` renders as empty string when the value is missing. "Hi , your order..." is sent to thousands of recipients when data is incomplete. Use conditional blocks or a registered `defaultIfEmpty` helper for every optional field. Source: production email incident patterns.
> `detect: contextual` — test every template with a payload where all optional string fields are `undefined`

**[HBS-002]** `transactional: mortal | marketing: mortal` — Use `{{variable}}` (double-stache) for all user-provided content. Triple-stache `{{{rawHtml}}}` must only be used for pre-rendered, trusted HTML from your own system.
> Triple-stache bypasses HTML escaping. If the value contains user-generated content, this is an XSS vector in email webview rendering and in-app browser contexts (opening links, CSP-exempted webviews). Source: OWASP XSS Prevention Cheat Sheet.
> `detect: regex` — pattern: `\{\{\{[^}]+\}\}\}`

**[HBS-003]** `transactional: mortal | marketing: mortal` — Do not rely on `@index`, `@first`, or `@last` loop metadata in `{{#each}}` when templates run through SendGrid Dynamic Templates.
> SendGrid's Handlebars subset does not document `@index`/`@first`/`@last` as supported. Templates that use these work in local Handlebars.js but silently fail in SendGrid — the metadata variables render as empty or cause unexpected output. Source: SendGrid Dynamic Templates documentation.
> `detect: regex` — pattern: `@(?:index|first|last)\b`

**[HBS-004]** `transactional: mortal | marketing: mortal` — Postmark uses Mustache, not Handlebars. Do not use `{{#each}}`, `{{#if condition}}`, or custom helpers in Postmark templates.
> Postmark's template engine is standard Mustache (RFC). Mustache uses `{{#section}}` for both conditionals (renders if truthy) and loops (renders once per array element). `{{^section}}` renders when the value is falsy or the array is empty. No block helpers, no custom helpers, no `@index` metadata. Source: Postmark developer documentation.
> `detect: contextual` — if `stack.esp` is "postmark", flag `{{#each}}`, `{{#if}}` comparisons, and `@`-variables

**[HBS-005]** `transactional: mortal | marketing: mortal` — Partials must be registered with `Handlebars.registerPartial()` before `Handlebars.compile()` is called. Unregistered partials throw at compile time — not at send time.
> Missing partial registration causes an immediate error. More dangerous is the inverse: partial registration in one service instance not reflected in another (e.g., in a multi-process Node.js cluster). Use a centralised registration module loaded at startup.
> `detect: contextual` — verify all `{{> partial_name}}` references have corresponding `registerPartial()` calls in the initialisation module

**[HBS-006]** `transactional: mortal | marketing: mortal` — Never concatenate unescaped user data into the template source string before `Handlebars.compile()`. This is a server-side template injection (SSTI) vector.
> Template source must come from trusted files. User data is passed as the context object to the compiled function. Any pattern that builds the template string from user input allows injection of Handlebars syntax — including `{{#each}}` loops that expose server-side data objects.
> `detect: contextual` — code review concern; flag any code path that builds a template string from request parameters

**[HBS-007]** `transactional: venial | marketing: venial` — Register a `formatCurrency` helper for monetary values. Do not format currency inline.
> Inline currency (`${{price}}`) outputs `$9.9` for a `9.90` float. Currency formatting requires locale-aware handling of decimal places and symbol placement. Register once, use everywhere. Source: Handlebars.js helper documentation.
> `detect: contextual` — check for monetary variables used without a currency format helper

**[HBS-008]** `transactional: venial | marketing: venial` — Register a `formatDate` helper for date values. Never render raw ISO 8601 strings into email copy.
> `2026-03-18T14:00:00.000Z` in email copy is unacceptable. A `formatDate` helper converts to locale-appropriate display: "Wednesday 18 March 2026". Source: Handlebars.js guide.
> `detect: regex` — pattern: `\{\{[^}]*[Dd]ate[^}]*\}\}(?![^{]*formatDate)` (date variable without format helper)

**[HBS-009]** `transactional: venial | marketing: venial` — Pre-compile templates at build/deploy time using `Handlebars.precompile()`. Do not call `Handlebars.compile()` per send in a high-volume pipeline.
> `Handlebars.compile()` parses and compiles the template source on every invocation. Pre-compiled templates are JavaScript functions — send-time rendering is orders of magnitude faster. Source: Handlebars.js API documentation.
> `detect: contextual` — check if the production send path calls `Handlebars.compile()` on the template source

**[HBS-010]** `transactional: venial | marketing: venial` — Handlebars `{{#if}}` tests truthiness only — no comparison operators. Comparisons must be expressed as registered helpers.
> `{{#if user.tier === "vip"}}` is not valid Handlebars — the `===` is syntax Handlebars does not parse. It silently evaluates to falsy. Register a helper: `{{#ifEquals user.tier "vip"}}...{{/ifEquals}}`. Source: Handlebars.js guide — built-in helpers.
> `detect: regex` — pattern: `\{\{#if[^}]*(?:===|!==|>=|<=|>|<)[^}]*\}\}`

**[HBS-011]** `transactional: venial | marketing: venial` — Use partials for shared email components (header, footer, CTA button, order row).
> Duplicating boilerplate across templates creates divergence — the footer in `order-confirmation.hbs` and `shipping-notification.hbs` slowly drift. Partials enforce a single source of truth for shared components.
> `detect: contextual` — check if multiple templates contain identical HTML blocks (>10 lines) without using a partial

**[HBS-012]** `transactional: venial | marketing: venial` — `{{else}}` blocks must contain a complete, readable fallback — not empty `<td>` elements or whitespace.
> Recipients who trigger the else path (no order items, no shipping address) must still see a meaningful email. An empty else block produces a broken layout with missing table cells or conspicuous blank spaces.
> `detect: contextual` — check `{{else}}` blocks for empty or whitespace-only content

**[HBS-013]** `transactional: venial | marketing: venial` — Escape HTML entities in subject lines and preheaders — they are plain text fields.
> `&amp;`, `&lt;`, `&gt;` in subject lines render as literal HTML entity strings in email clients. If your template data is HTML-escaped before injection, the subject field receives `Acme &amp; Co.` and displays as `Acme &amp; Co.` in the inbox. Pre-process entity decoding for subject/preheader fields.
> `detect: contextual` — check if subject/preheader values pass through HTML unescaping before being passed to the ESP API

**[HBS-014]** `transactional: venial | marketing: venial` — Test with a deliberately incomplete payload — all optional fields `undefined`, all arrays empty.
> The `{{#each items}}` empty path and the `{{#unless}}` truthy path are the most common sources of broken layout. Comprehensive testing always uses complete data. Fail testing uses null/undefined/empty-array data.
> `detect: contextual` — advisory; ensure test harness includes a "minimum data" test fixture

**[HBS-015]** `transactional: counsel | marketing: counsel` — Use `{{#with}}` sparingly to reduce nesting verbosity — not as a general code-organisation strategy.
> `{{#with order.shipping}}...{{/with}}` gives direct access to `address`, `city`, `postcode` without `order.shipping.` prefix. Overuse makes templates opaque — `{{city}}` with no clear context makes code review and debugging harder.
> `detect: contextual` — advisory

**[HBS-016]** `transactional: counsel | marketing: counsel` — Remove `{{log}}` helper calls before deploying templates to production.
> `{{log someValue}}` outputs to the console during local development. It has no output in the rendered HTML but is extraneous in production template files.
> `detect: regex` — pattern: `\{\{log\s`

**[HBS-017]** `transactional: counsel | marketing: counsel` — For SendGrid Dynamic Templates, prefer the Template API for version management over inlining template HTML in API calls.
> Templates stored in the SendGrid dashboard can be versioned and rolled back without a code deployment. A/B testing, scheduling, and suppression lists are also manageable at the template level.
> `detect: contextual` — advisory; check if SendGrid calls use `template_id` vs inline `content`

---

## Patterns & Code Examples

### registerHelper: formatCurrency and formatDate

```javascript
const Handlebars = require('handlebars');

Handlebars.registerHelper('formatCurrency', (amount, currency = 'GBP', locale = 'en-GB') => {
  if (amount == null || isNaN(amount)) return '—';
  return new Intl.NumberFormat(locale, {
    style: 'currency', currency, minimumFractionDigits: 2
  }).format(amount);
});

Handlebars.registerHelper('formatDate', (dateValue, format = 'long', locale = 'en-GB') => {
  if (!dateValue) return '—';
  const date = new Date(dateValue);
  const options = format === 'long'
    ? { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }
    : { year: 'numeric', month: 'short', day: 'numeric' };
  return new Intl.DateTimeFormat(locale, options).format(date);
});

Handlebars.registerHelper('defaultIfEmpty', (value, fallback) =>
  value && String(value).trim() ? value : fallback
);

Handlebars.registerHelper('ifEquals', function(a, b, options) {
  return a === b ? options.fn(this) : options.inverse(this);
});
```

Usage in template:
```handlebars
<p>Hi {{defaultIfEmpty firstName "Valued Customer"}},</p>
<p>Total: {{formatCurrency order.total "GBP" "en-GB"}}</p>
<p>Expected delivery: {{formatDate order.deliveryDate "long"}}</p>
```

### Order items loop with empty-array fallback

```handlebars
{{#if order.items.length}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <thead>
    <tr>
      <th style="text-align: left; padding: 8px; font-family: Arial, sans-serif; font-size: 13px;">Item</th>
      <th style="text-align: right; padding: 8px;">Qty</th>
      <th style="text-align: right; padding: 8px;">Price</th>
    </tr>
  </thead>
  <tbody>
    {{#each order.items}}
    <tr>
      <td style="padding: 8px; font-family: Arial, sans-serif; font-size: 14px;">{{this.name}}</td>
      <td style="text-align: right; padding: 8px;">{{this.quantity}}</td>
      <td style="text-align: right; padding: 8px;">{{formatCurrency this.unitPrice}}</td>
    </tr>
    {{/each}}
  </tbody>
</table>
{{else}}
<p style="font-family: Arial, sans-serif; font-size: 14px; color: #666666;">
  No items found in this order.
</p>
{{/if}}
```

### Partial: shared footer

```javascript
// Register at application startup
Handlebars.registerPartial('email-footer', `
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td style="padding: 24px; font-family: Arial, sans-serif; font-size: 12px;
               color: #666666; text-align: center;">
      <p style="margin: 0 0 8px;">{{companyName}} — {{companyAddress}}</p>
      <p style="margin: 0;">
        <a href="{{unsubscribeUrl}}" style="color: #666666;">Unsubscribe</a>
      </p>
    </td>
  </tr>
</table>
`);
```

Usage:
```handlebars
{{> email-footer companyName="Acme Ltd" companyAddress="123 High Street, London EC1A 1BB" unsubscribeUrl=unsubscribeUrl}}
```

### Handlebars vs Postmark Mustache comparison

Same data, both syntaxes — for teams working across both platforms:

```handlebars
{{! Handlebars (full) }}
{{#if order.items}}
  {{#each order.items}}
    <tr><td>{{this.name}}</td><td>{{this.quantity}}</td></tr>
  {{/each}}
{{else}}
  <tr><td colspan="2">No items.</td></tr>
{{/if}}
```

```mustache
{{! Postmark Mustache }}
{{#order}}
  {{#items}}
    <tr><td>{{name}}</td><td>{{quantity}}</td></tr>
  {{/items}}
  {{^items}}
    <tr><td colspan="2">No items.</td></tr>
  {{/items}}
{{/order}}
```

Key differences: Mustache uses `{{#section}}` for both conditionals and loops; no `#each`; context is the element directly (no `this.`); `{{^inverted}}` for falsy/empty.

## Support Matrix

| Feature | Handlebars.js | SendGrid subset | Postmark (Mustache) | Mandrill (HBS mode) |
|---------|:---:|:---:|:---:|:---:|
| `{{variable}}` | ✅ | ✅ | ✅ | ✅ |
| `{{#if}}` truthiness | ✅ | ✅ | `{{#section}}` | ✅ |
| `{{#each}}` | ✅ | ✅ | `{{#section}}` | ✅ |
| `{{#unless}}` | ✅ | ✅ | `{{^inverted}}` | ✅ |
| Custom helpers | ✅ | ❌ | ❌ | ❌ |
| `@index`/`@first`/`@last` | ✅ | ❌ | N/A | Undocumented |
| `{{> partial}}` | ✅ | ❌ | ❌ | ❌ |
| `{{{triple-stache}}}` | ✅ | ✅ | ✅ | ✅ |
| Pre-compilation | ✅ | N/A (server-side) | N/A | N/A |

### Pre-compile for production

```javascript
// build-templates.js — run at deploy time, not per-send
const Handlebars = require('handlebars');
const fs = require('fs');
const path = require('path');

// Register all helpers
require('./helpers/currency')(Handlebars);
require('./helpers/dates')(Handlebars);
require('./helpers/conditionals')(Handlebars);

// Register all partials
const partialsDir = path.join(__dirname, 'email-templates/partials');
fs.readdirSync(partialsDir).forEach(file => {
  const name = path.basename(file, '.hbs');
  const content = fs.readFileSync(path.join(partialsDir, file), 'utf8');
  Handlebars.registerPartial(name, content);
});

// Pre-compile all templates
const templatesDir = path.join(__dirname, 'email-templates');
const compiled = {};
fs.readdirSync(templatesDir).filter(f => f.endsWith('.hbs')).forEach(file => {
  const name = path.basename(file, '.hbs');
  const source = fs.readFileSync(path.join(templatesDir, file), 'utf8');
  // precompile() returns JS source; use compileAST() to get the function directly
  compiled[name] = Handlebars.compile(source);
});

module.exports = compiled;
```

```javascript
// send.js — use pre-compiled templates at send time
const templates = require('./build-templates');

function renderEmail(templateName, data) {
  const template = templates[templateName];
  if (!template) throw new Error(`Unknown email template: ${templateName}`);
  return template(data);
}
```

## Known Afflictions

**SendGrid `@index` silent failure** — `@index` inside `{{#each}}` compiles and runs locally without error. In SendGrid, the loop renders but `@index` outputs empty string. This is most commonly used for alternating row styling or first/last separators — both silently break in production.
Fix: Pre-process index values into the data model before injection, or use a background-colour on every other row via CSS rather than template logic.

**Handlebars partial scope isolation** — Partials in Handlebars inherit the current context by default. Passing explicit context to a partial (`{{> footer company=company}}`) does not merge with the parent context — the partial only sees the explicitly passed object. Teams that expect partials to inherit the full parent context encounter unexpected undefined variables.
Fix: Pass every variable the partial needs explicitly, or use `{{> partial .}}` to pass the entire current context.

**Double-escaping in HTML attributes** — When a Handlebars variable is used inside an HTML attribute that already contains encoded content (e.g., `href="mailto:{{email}}"` where `email` contains a `+` sign that was already URL-encoded), double-encoding can occur. Test with addresses containing `+`, `&`, and non-ASCII characters.
Fix: Register a helper for URL-unsafe contexts; do not rely on Handlebars' default HTML escaping for URL components.

## Sources

1. **Handlebars.js Guide** — https://handlebarsjs.com/guide/ — Built-in helpers, custom helper registration, partials, precompilation.
2. **SendGrid Dynamic Templates** — https://docs.sendgrid.com/for-developers/sending-email/using-handlebars — Handlebars subset, supported constructs.
3. **Postmark Developer Docs** — https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates — Mustache syntax.
4. **Mustache(5) Manual** — https://mustache.github.io/mustache.5.html — Sections, inverted sections, partials.
5. **OWASP** — https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html — XSS prevention; template injection.
