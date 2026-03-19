# Email Templating Languages & Frameworks

Research for engineers building transactional email template pipelines.
Date: 2026-03-17
Last verified: 2026-03-17

---

## Templating Tools Overview

### MJML

MJML is a markup language designed specifically for responsive email. It abstracts away the infamous table-based layout hacks required by email clients into a set of high-level semantic components. The MJML compiler transpiles `.mjml` source files into cross-client HTML. It is maintained by Mailjet and open-sourced at https://github.com/mjmlio/mjml.

**Current version: 4.18.0** (stable, December 2024). MJML v5.0.0-beta.1 was released March 2025 and is under active development — see notes below.

Key characteristics:
- Component-based: head components (`mj-attributes`, `mj-breakpoint`, `mj-font`, `mj-html-attributes`, `mj-preview`, `mj-style`, `mj-title`) and body components (`mj-accordion`, `mj-button`, `mj-carousel`, `mj-column`, `mj-divider`, `mj-group`, `mj-hero`, `mj-image`, `mj-navbar`, `mj-raw`, `mj-section`, `mj-social`, `mj-spacer`, `mj-table`, `mj-text`, `mj-wrapper`).
- Outputs fully inlined CSS, nested tables, and MSO conditional comments for Outlook automatically.
- Available as a CLI tool (`mjml`), a Node.js API (`mjml` npm package), and an online editor.
- Does **not** handle dynamic data — it produces static HTML. Dynamic content must be injected before or after compilation via a separate templating layer (e.g. Handlebars or Liquid).
- Community-contributed components include chart libraries (`mj-chart`, `mj-chartjs`, `mj-bar-chart`) and `mj-qr-code`. Language bindings exist for Python, Ruby, Rust, PHP/Laravel, and .NET.
- Source: [MJML Documentation](https://documentation.mjml.io/)

**MJML v5 breaking changes (beta as of March 2025):**
- Minification backend replaced: `html-minifier` and `js-beautify` swapped for `htmlnano` and `cssnano`.
- The `<body>` tag is now controlled by `mj-body` (structure change in generated HTML).
- File includes are **disabled by default** for security; must be explicitly enabled via config.
- Migration helper tool removed.
- Node.js 16 and 18 dropped; requires Node 20, 22, or 24.
- Browser bundle reduced from 1.22 MB to 1.04 MB.
- Do not upgrade production pipelines to v5 without thorough visual regression testing.

### Handlebars

Handlebars is a logic-minimal JavaScript templating language descended from Mustache. Templates are compiled to JavaScript functions at build time or evaluated at runtime via `Handlebars.compile()`. It is widely used for server-side rendering of transactional email HTML.

Key characteristics:
- Double-curly syntax: `{{variable}}`, `{{#each}}`, `{{#if}}`, `{{#with}}`, `{{#unless}}`, `{{lookup}}`.
- Supports custom helpers for formatting (dates, currency, truncation) registered via `Handlebars.registerHelper()`.
- Supports partials (`{{> partial_name}}`) registered via `registerPartial()` for shared components (headers, footers).
- HTML-escapes output by default; triple-stache `{{{raw_html}}}` bypasses escaping.
- Available on npm (`handlebars`); also has ports in Ruby (handlebars.rb), PHP (LightnCandy), Java (handlebars.java).

**Handlebars vs Mustache distinctions:**
Handlebars is a strict superset of Mustache. Mustache has no built-in helpers, no custom helper registration, no partials beyond simple `{{> name}}` inclusion, and no block helpers. Handlebars adds: block helpers (`{{#each}}`, `{{#if}}`, `{{#with}}`, `{{#unless}}`), custom helpers, the `lookup` helper for dynamic property access, and the `log` helper. SendGrid and Postmark each use a *subset* of these — Postmark uses standard Mustache syntax (no block helpers beyond sections/inverted sections), while SendGrid uses Handlebars block helpers.

- Source: [Handlebars.js Guide](https://handlebarsjs.com/guide/)

### Liquid

Liquid is a templating language created by Shopify, open-sourced and used as the default template language in Shopify themes. It is also adopted by many ESPs (notably Klaviyo) for dynamic email content, and by static site generators (Jekyll, Bridgetown). It is safe to render user-controlled input because it has no access to the file system or arbitrary code execution.

Key characteristics:
- Output tags: `{{ variable }}`, filters via pipe: `{{ name | upcase }}`.
- Logic tags: `{% if %}`, `{% for %}`, `{% unless %}`, `{% case %}`.
- Strict separation between output (`{{}}`) and logic (`{% %}`).
- Filters are composable: `{{ price | times: 1.1 | round: 2 }}`.
- 60+ built-in filters covering strings, arrays, math, dates, encoding, and data transformation.
- Ruby gem (`liquid`); also available as a JavaScript port (`liquidjs`).
- In production at Shopify since 2006; also used by Jekyll, Zendesk, Desk, 500px, and others.
- Source: [Liquid Documentation (Shopify GitHub)](https://shopify.github.io/liquid/)

### Jinja2

Jinja2 is a Python templating engine modelled after Django's template language but significantly more expressive. It is the de facto standard for Python-based email rendering pipelines (Flask, FastAPI, Django all use it or integrate easily).

Key characteristics:
- Delimiters: `{{ variable }}` for output, `{% block %}` / `{% if %}` / `{% for %}` for logic, `{# comment #}` for comments.
- Template inheritance via `{% extends "base.html" %}` and `{% block content %}` — ideal for email layout hierarchies.
- Filters: `{{ amount | round(2) }}`, `{{ name | default("Valued Customer") }}`.
- Auto-escaping can be enabled globally or per-template; for HTML email, enable it.
- Sandboxed execution environment available for untrusted templates.
- Whitespace control: `-` modifier (`{%- -%}`) strips surrounding whitespace from block tags.
- Source: [Jinja2 Documentation](https://jinja.palletsprojects.com/en/stable/)

### Nunjucks

Nunjucks is Mozilla's JavaScript templating engine, heavily inspired by Jinja2. It is functionally the closest JS equivalent to Jinja2 and supports template inheritance, macros, filters, and async rendering.

Key characteristics:
- Same delimiter conventions as Jinja2: `{{ }}`, `{% %}`, `{# #}`.
- Template inheritance with `{% extends %}` and `{% block %}`.
- Macros (reusable template functions): `{% macro button(label, url) %}`.
- Can precompile templates to JavaScript for browser or Node.js use.
- Available on npm (`nunjucks`).
- Source: [Nunjucks Documentation (Mozilla)](https://mozilla.github.io/nunjucks/)

### React Email

React Email is a component library and development framework for building email templates using React and TypeScript. It is developed by Resend and open-sourced at https://github.com/resend/react-email.

**Current version: 5.2.10** (released March 17, 2026). The library is in active production use and maintained with a regular patch cadence.

Key characteristics:
- Write email templates as React components; the framework renders them to HTML strings at send time via server-side rendering.
- Core components: `<Body>`, `<Button>`, `<CodeBlock>`, `<CodeInline>`, `<Container>`, `<Heading>`, `<Hr>`, `<Img>`, `<Link>`, `<Preview>`, `<Text>`.
- `@react-email/tailwind` package provides Tailwind CSS v3/v4 support inside email components.
- Built-in development preview server (`@react-email/preview-server`) with hot reload.
- Integrates with any Node.js email sending library (Resend, Nodemailer, SendGrid, AWS SES, Postmark, etc.) — render to an HTML string and pass it to the ESP API.
- TypeScript-first; component props are typed, catching data-shape errors at compile time rather than at send time.
- Does not handle responsive layout automatically the way MJML does — developers are responsible for cross-client CSS compatibility.
- Source: [React Email Documentation](https://react.email/docs/introduction), [GitHub Releases](https://github.com/resend/react-email/releases)

### Maizzle

Maizzle is an email framework that uses Tailwind CSS as its styling system. It is open-sourced at https://github.com/maizzle/framework.

**Current version: 5.5.0** (released February 2026).

Key characteristics:
- Write emails in plain HTML with Tailwind CSS utility classes; Maizzle compiles and inlines the CSS for email clients.
- No custom component DSL — templates are plain HTML, making it more transparent and less opinionated than MJML.
- Supports PostCSS, component includes, and template inheritance.
- Does not abstract layout as aggressively as MJML — developers write table-based HTML themselves or use Maizzle's starter templates.
- Suited to teams already fluent in Tailwind CSS who want that workflow applied to email without learning MJML's component model.
- Source: [Maizzle Framework (GitHub)](https://github.com/maizzle/framework)

### ESP-Native Syntaxes

Each major ESP ships its own dynamic content syntax, evaluated server-side at send time. These are only available within the ESP's own sending infrastructure and are not portable.

#### SendGrid Dynamic Templates (Handlebars)

SendGrid's Dynamic Transactional Templates use a subset of Handlebars syntax. Templates are stored in the SendGrid dashboard or via the API and rendered at send time by injecting a `dynamic_template_data` JSON payload per recipient.

- Supported constructs: `{{variable}}`, `{{#if condition}}`, `{{#each array}}`, `{{#unless}}`.
- Does **not** support custom Handlebars helpers or partials beyond what SendGrid exposes.
- `@index`, `@first`, `@last` loop metadata variables are **not** reliably documented as supported in SendGrid's Handlebars subset — do not depend on them without live verification.
- Template versioning is managed via the SendGrid API (`POST /v3/templates/{id}/versions`).
- Source: [SendGrid Dynamic Templates Documentation](https://docs.sendgrid.com/ui/sending-email/how-to-send-an-email-with-dynamic-templates)

#### Mailchimp Merge Tags

Mailchimp uses its own proprietary merge tag syntax for personalisation in both campaign and transactional (Mandrill) emails.

- Syntax: `*|FNAME|*`, `*|EMAIL|*`, `*|MERGE1|*` through `*|MERGE30|*`.
- Conditional blocks: `*|IF:FNAME|* Hello *|FNAME|* *|ELSE:|* Hello there *|END:IF|*`.
- Mandrill (Mailchimp Transactional) also supports Handlebars via the `merge_language: "handlebars"` send option.
- Merge tags are evaluated at send time; no compile step exists outside the ESP.
- Source: [Mailchimp Merge Tags Reference](https://mailchimp.com/help/all-the-merge-tags-cheat-sheet/)

#### Postmark Templating

Postmark stores templates server-side with a **standard Mustache syntax** (not Handlebars). Templates are rendered at send time by passing a `TemplateModel` JSON object in the API request.

- Syntax is Mustache: `{{variable}}`, `{{#section}}` (renders if truthy/non-empty), `{{^inverted}}` (renders if falsy/empty), `{{> partial}}`.
- Triple-mustache `{{{raw}}}` for unescaped HTML.
- **No block helpers** (`#each`, `#if`) — Mustache uses sections for both conditionals and loops; `{{#items}}` iterates if `items` is an array, or renders once if it is a truthy non-array value.
- Postmark also exposes a template validation API endpoint (`POST /templates/validate`) to check for syntax errors and preview rendered output before deployment.
- Source: [Postmark Templating Documentation](https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates)

---

## Syntax Examples

### MJML — Responsive Section with Inline Styles

```xml
<mjml>
  <mj-head>
    <mj-attributes>
      <mj-text font-family="Arial, sans-serif" font-size="14px" color="#333333" />
    </mj-attributes>
  </mj-head>
  <mj-body>
    <mj-section background-color="#ffffff" padding="20px">
      <mj-column>
        <mj-text>
          Hello, world.
        </mj-text>
        <mj-button href="https://example.com" background-color="#007bff">
          Click Here
        </mj-button>
      </mj-column>
    </mj-section>
  </mj-body>
</mjml>
```

MJML compiles this to a ~100-line table-based HTML document with inlined CSS and MSO conditionals. The developer never writes that HTML directly.
Source: [MJML Documentation](https://documentation.mjml.io/)

### Handlebars — Variable Substitution and Loop

```handlebars
<p>Hello, {{firstName}} {{lastName}}!</p>

{{#if orderItems}}
<table>
  {{#each orderItems}}
  <tr>
    <td>{{name}}</td>
    <td>{{qty}}</td>
    <td>${{price}}</td>
  </tr>
  {{/each}}
</table>
{{else}}
<p>Your order is empty.</p>
{{/if}}

<!-- Fallback via helper -->
<p>Hi, {{defaultIfEmpty firstName "Valued Customer"}}!</p>
```

Custom helper for fallback:
```javascript
Handlebars.registerHelper('defaultIfEmpty', (value, fallback) =>
  value && value.trim() ? value : fallback
);
```
Source: [Handlebars.js Guide — Built-In Helpers](https://handlebarsjs.com/guide/builtin-helpers.html)

### Liquid — Filters and Conditional Blocks

```liquid
<p>Hello, {{ first_name | default: "Valued Customer" | capitalize }}!</p>

{% if order.items.size > 0 %}
<table>
  {% for item in order.items %}
  <tr>
    <td>{{ item.name }}</td>
    <td>{{ item.quantity }}</td>
    <td>{{ item.price | money }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No items in this order.</p>
{% endif %}

{% if customer.segment == "vip" %}
<p>As a VIP member, enjoy free shipping on this order.</p>
{% elsif customer.segment == "returning" %}
<p>Welcome back! Here is 10% off your next order.</p>
{% else %}
<p>Thank you for your first order.</p>
{% endif %}
```

Source: [Liquid Reference — Filters](https://shopify.github.io/liquid/filters/default/), [Liquid Reference — Tags](https://shopify.github.io/liquid/tags/control-flow/)

### Jinja2 — Template Inheritance

```
{# base_email.html #}
<!DOCTYPE html>
<html>
<body>
  <table width="600">
    <tr><td>{% block content %}{% endblock %}</td></tr>
    <tr><td>{% block footer %}© {{ year }} Acme Corp{% endblock %}</td></tr>
  </table>
</body>
</html>
```

```
{# order_confirmation.html #}
{% extends "base_email.html" %}
{% block content %}
<p>Hello, {{ first_name | default("Valued Customer") }}!</p>
<p>Your order {{ order.id }} has been confirmed.</p>
<table>
{% for item in order.items %}
  <tr>
    <td>{{ item.name }}</td>
    <td>{{ item.quantity }}</td>
    <td>{{ item.unit_price | round(2) }}</td>
  </tr>
{% endfor %}
</table>
<p><strong>Total: {{ order.total | round(2) }}</strong></p>
{% endblock %}
```

Python render call:
```python
from jinja2 import Environment, FileSystemLoader

env = Environment(
    loader=FileSystemLoader("templates/"),
    autoescape=True
)
template = env.get_template("order_confirmation.html")
html = template.render(
    first_name=user.first_name,
    order=order,
    year=2026
)
```
Source: [Jinja2 Documentation — Template Inheritance](https://jinja.palletsprojects.com/en/stable/templates/#template-inheritance)

### Nunjucks — Macro for Reusable Components

```nunjucks
{# macros/button.njk #}
{% macro ctaButton(label, url, color="#007bff") %}
<a href="{{ url }}" style="background-color: {{ color }}; color: #fff; padding: 12px 24px; text-decoration: none;">
  {{ label }}
</a>
{% endmacro %}

{# order_confirmation.njk #}
{% from "macros/button.njk" import ctaButton %}
{% extends "base.njk" %}

{% block content %}
<p>Hello, {{ firstName | default("Valued Customer") }}!</p>
{{ ctaButton("View Your Order", order.trackingUrl) }}
{% endblock %}
```
Source: [Nunjucks Documentation — Macros](https://mozilla.github.io/nunjucks/templating.html#macro)

### React Email — Component-Based Template

```tsx
import {
  Body, Button, Container, Head, Heading, Hr, Html, Img, Preview, Text
} from '@react-email/components';

interface OrderConfirmationProps {
  firstName: string;
  orderId: string;
  trackingUrl: string;
}

export default function OrderConfirmation({
  firstName = 'Valued Customer',
  orderId,
  trackingUrl,
}: OrderConfirmationProps) {
  return (
    <Html>
      <Head />
      <Preview>Your order {orderId} has been confirmed.</Preview>
      <Body style={{ fontFamily: 'Arial, sans-serif', backgroundColor: '#ffffff' }}>
        <Container style={{ maxWidth: '600px', margin: '0 auto' }}>
          <Heading>Hello, {firstName}!</Heading>
          <Text>Your order <strong>{orderId}</strong> has been confirmed.</Text>
          <Hr />
          <Button href={trackingUrl} style={{ backgroundColor: '#007bff', color: '#fff' }}>
            Track Your Order
          </Button>
        </Container>
      </Body>
    </Html>
  );
}
```

Render to HTML string for sending:
```typescript
import { render } from '@react-email/components';
import OrderConfirmation from './emails/order-confirmation';

const html = await render(
  <OrderConfirmation firstName="Alice" orderId="ORD-001" trackingUrl="https://track.example.com/ORD-001" />
);
// Pass `html` to your ESP API
```

Source: [React Email Documentation](https://react.email/docs/introduction)

### SendGrid Dynamic Templates (Handlebars subset)

```handlebars
<p>Hi {{first_name}},</p>

{{#if items}}
<table>
{{#each items}}
  <tr>
    <td>{{this.name}}</td>
    <td>{{this.quantity}}</td>
    <td>{{this.price}}</td>
  </tr>
{{/each}}
</table>
{{/if}}

{{#if is_vip}}
<p>As a VIP, your discount has been applied.</p>
{{/if}}
```

API payload excerpt:
```json
{
  "template_id": "d-xxxxxxxxxxxx",
  "personalizations": [{
    "to": [{"email": "user@example.com"}],
    "dynamic_template_data": {
      "first_name": "Alice",
      "is_vip": true,
      "items": [
        {"name": "Widget", "quantity": 2, "price": "$9.99"}
      ]
    }
  }]
}
```
Source: [SendGrid API Reference — Send Mail](https://docs.sendgrid.com/api-reference/mail-send/mail-send)

### Mailchimp Merge Tags

```
*|IF:FNAME|*
  Hi *|FNAME|*,
*|ELSE:|*
  Hi there,
*|END:IF|*

Your order *|ORDER_ID|* has shipped.

Track it here: *|TRACKING_URL|*
```

Mandrill (Handlebars mode) via API:
```json
{
  "merge_language": "handlebars",
  "template_name": "order-shipped",
  "merge_vars": [{
    "rcpt": "user@example.com",
    "vars": [
      {"name": "FNAME", "content": "Alice"},
      {"name": "ORDER_ID", "content": "ORD-1234"}
    ]
  }]
}
```
Source: [Mailchimp Merge Tags Cheat Sheet](https://mailchimp.com/help/all-the-merge-tags-cheat-sheet/), [Mandrill API — Messages](https://mailchimp.com/developer/transactional/api/messages/send-using-message-template/)

### Postmark Templates (Mustache)

```mustache
<p>Hello, {{#first_name}}{{first_name}}{{/first_name}}{{^first_name}}Valued Customer{{/first_name}}!</p>

{{#order}}
<p>Order ID: {{id}}</p>
<table>
{{#items}}
  <tr>
    <td>{{name}}</td>
    <td>{{quantity}}</td>
    <td>{{price}}</td>
  </tr>
{{/items}}
</table>
{{/order}}
```

Note: `{{#items}}` iterates over the array when `items` is an array, and renders once when `items` is a truthy object. `{{^items}}` renders when `items` is falsy or an empty array. This is standard Mustache behaviour — there is no separate `#each` helper.

API request:
```json
{
  "TemplateId": 12345,
  "TemplateModel": {
    "first_name": "Alice",
    "order": {
      "id": "ORD-5678",
      "items": [
        {"name": "Widget", "quantity": 1, "price": "$9.99"}
      ]
    }
  },
  "From": "no-reply@example.com",
  "To": "alice@example.com"
}
```
Source: [Postmark Developer Docs — Templates](https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates)

---

## Workflow Patterns

### Pattern 1: Build-Step Compilation (MJML + Handlebars/Nunjucks/Jinja2)

This is the most common architecture for teams maintaining their own template source files. The pipeline has two distinct phases:

**Phase 1 — Design Compilation (CI / build step):**
1. Write layout and structure in `.mjml` source files.
2. Run `mjml src/order-confirmation.mjml -o dist/order-confirmation.html` (or the Node API equivalent).
3. Commit the compiled `dist/` HTML to the repository, or publish it as an artefact.

**Phase 2 — Dynamic Rendering (runtime / send time):**
1. Load the compiled HTML template.
2. Inject per-recipient data using Handlebars, Nunjucks, Jinja2, or Liquid.
3. Pass the fully rendered HTML string to the ESP API (`html` field in SendGrid, Mailgun, SES, etc.).

```
[.mjml source]
    |
    v  mjml compile (build step / CI)
[static HTML with {{placeholders}}]
    |
    v  Handlebars/Jinja2/Nunjucks render (runtime)
[per-recipient HTML string]
    |
    v  ESP API (SendGrid /v3/mail/send, SES SendRawEmail, etc.)
```

This pattern keeps design concerns (responsiveness, cross-client layout) separate from data concerns (personalisation).

Source: [MJML Documentation — Use with Node.js](https://documentation.mjml.io/)

### Pattern 2: Runtime Rendering Only (Jinja2 / Nunjucks server-side)

For teams without MJML, the full HTML is maintained as a Jinja2 or Nunjucks template. A web server or background worker renders the template per-request or per-job:

```
[.html.jinja2 / .njk template on disk]
    |
    v  Template engine render (FastAPI endpoint / Celery task)
[per-recipient HTML string]
    |
    v  ESP API
```

Suited to: high-volume transactional pipelines where send events are triggered by application code (order placed, password reset). The render step is synchronous and happens in-process.

Source: [Jinja2 Documentation — Environment](https://jinja.palletsprojects.com/en/stable/api/#jinja2.Environment)

### Pattern 3: ESP-Native Templates (SendGrid / Postmark / Mailchimp)

Templates are stored inside the ESP. The application sends only data, never HTML. The ESP renders the template server-side at delivery time.

```
[Template stored in ESP dashboard / via API]
    |
    v  Application sends TemplateId + data payload
[ESP renders HTML at send time]
    |
    v  Delivered to recipient
```

Advantages:
- No HTML delivery over the network per send.
- Non-engineers can edit templates via the ESP's visual editor.
- Template versioning and A/B testing managed by the ESP.

Disadvantages:
- Template source is locked in the ESP; migrating ESPs requires rewriting all templates.
- Logic capabilities are constrained to what the ESP exposes (SendGrid's Handlebars subset lacks custom helpers; Postmark is limited to standard Mustache without block helpers).
- Local development and testing requires either the ESP's API or mock rendering.

Source: [SendGrid Dynamic Templates](https://docs.sendgrid.com/ui/sending-email/how-to-send-an-email-with-dynamic-templates), [Postmark Templates](https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates)

### Pattern 4: Liquid at Runtime (Klaviyo / Jekyll-style pipelines)

Liquid is evaluated at render time, making it suitable for event-driven pipelines where templates reference profile properties resolved at send time. Klaviyo's template engine evaluates Liquid expressions against the recipient's profile data at the moment of send.

```
[Liquid template stored in Klaviyo / CMS]
    |
    v  Event triggers send (e.g. "Placed Order")
[Klaviyo resolves {{ person.first_name }}, order event properties]
    |
    v  Rendered HTML delivered
```

For self-hosted pipelines, `liquidjs` (npm) or the Ruby `liquid` gem can render templates server-side before dispatch.

Source: [Klaviyo Developer Docs — Liquid Overview](https://developers.klaviyo.com/en/docs/liquid-overview), [LiquidJS npm](https://www.npmjs.com/package/liquidjs)

### Pattern 5: Hybrid — MJML Compile + ESP Native Templates

Some teams compile MJML to HTML and then upload the compiled HTML as the ESP template body, leaving SendGrid/Postmark Handlebars/Mustache placeholders intact inside the MJML source.

```xml
<mj-text>
  Hello, {{first_name}}!
</mj-text>
```

After MJML compilation, `{{first_name}}` is preserved verbatim inside the output HTML (MJML does not interpret non-MJML content). The compiled HTML is uploaded to the ESP as the template body, and per-send data injection is handled by the ESP at send time.

This is the recommended pattern for teams that want MJML's responsive output and SendGrid/Postmark's template management.

Source: [MJML Documentation](https://documentation.mjml.io/), [SendGrid Dynamic Templates](https://docs.sendgrid.com/ui/sending-email/how-to-send-an-email-with-dynamic-templates)

### Pattern 6: React Email + ESP API

React Email templates are React components rendered server-side to HTML strings, then passed directly to an ESP API. No separate templating language is involved — the data model is typed TypeScript props.

```
[React Email component (.tsx)]
    |
    v  render() call (Node.js server / serverless function)
[HTML string]
    |
    v  ESP API (Resend, SendGrid, SES, Postmark, etc.)
```

Suited to: TypeScript/Node.js stacks where email templates and application code share the same type definitions, catching data-shape mismatches at compile time rather than at send time.

Source: [React Email Documentation](https://react.email/docs/introduction)

---

## Dynamic Content

### Loops Over Order Items

Every engine supports iteration. The key concern is rendering tabular data inside HTML email tables correctly, and avoiding trailing commas or extra whitespace that breaks layout.

**Handlebars:**
```handlebars
{{#each order.items}}
<tr>
  <td style="padding: 8px;">{{this.name}}</td>
  <td style="padding: 8px; text-align: right;">{{this.quantity}}</td>
  <td style="padding: 8px; text-align: right;">${{this.unit_price}}</td>
</tr>
{{/each}}
```
`this` refers to the current iteration context. `@index`, `@first`, `@last` are available as loop metadata in full Handlebars — **not** reliably supported in SendGrid's Handlebars subset.
Source: [Handlebars Guide — #each](https://handlebarsjs.com/guide/builtin-helpers.html#each)

**Liquid:**
```liquid
{% for item in order.items %}
<tr>
  <td>{{ item.name }}</td>
  <td>{{ item.quantity }}</td>
  <td>{{ item.unit_price | money }}</td>
</tr>
{% else %}
<tr><td colspan="3">No items found.</td></tr>
{% endfor %}
```
The `{% else %}` block within `{% for %}` renders if the array is empty — a clean pattern for graceful fallback.
Source: [Liquid Tags — for](https://shopify.github.io/liquid/tags/iteration/)

**Jinja2:**
```jinja2
{% for item in order.items %}
<tr>
  <td>{{ item.name }}</td>
  <td>{{ item.quantity }}</td>
  <td>{{ "%.2f" | format(item.unit_price) }}</td>
  {% if loop.last %}{# no trailing separator #}{% endif %}
</tr>
{% else %}
<tr><td colspan="3">No items found.</td></tr>
{% endfor %}
```
`loop.index`, `loop.first`, `loop.last`, `loop.length` are available as loop variables.
Source: [Jinja2 — For Loop](https://jinja.palletsprojects.com/en/stable/templates/#for)

**Nunjucks:**
```nunjucks
{% for item in order.items %}
<tr>
  <td>{{ item.name }}</td>
  <td>{{ item.quantity }}</td>
  <td>{{ item.unit_price | round(2) }}</td>
</tr>
{% else %}
<tr><td colspan="3">No items found.</td></tr>
{% endfor %}
```
Source: [Nunjucks — For Tag](https://mozilla.github.io/nunjucks/templating.html#for)

**SendGrid (Handlebars subset):**
```handlebars
{{#each items}}
<tr>
  <td>{{this.name}}</td>
  <td>{{this.quantity}}</td>
  <td>{{this.price}}</td>
</tr>
{{/each}}
```
Note: `@index`/`@first`/`@last` metadata variables are **not** documented as supported in SendGrid's Handlebars subset. Do not rely on them.
Source: [SendGrid Dynamic Templates — Handlebars](https://docs.sendgrid.com/for-developers/sending-email/using-handlebars#iteration)

**Postmark (Mustache sections — loop behaviour):**
```mustache
{{#items}}
<tr>
  <td>{{name}}</td>
  <td>{{quantity}}</td>
  <td>{{price}}</td>
</tr>
{{/items}}
```
When `items` is an array, Mustache renders the block once per element, with each element's properties available directly (no `this.` prefix). When `items` is empty or falsy, the block is suppressed.
Source: [Mustache(5) — Sections](https://mustache.github.io/mustache.5.html#Sections)

### Conditionals for User Segments

Segmentation logic inside email templates is common for: VIP vs. standard messaging, locale-specific content, plan tier upsells, and promotional banner injection.

**Multi-tier conditional (Jinja2):**
```jinja2
{% if user.plan == "enterprise" %}
  <p>Your dedicated support line: +1-800-555-0100</p>
{% elif user.plan == "pro" %}
  <p>Priority support: <a href="https://support.example.com">Open a ticket</a></p>
{% else %}
  <p>Need help? <a href="https://docs.example.com">Browse our docs</a></p>
{% endif %}
```

**Boolean flag (Handlebars):**
```handlebars
{{#if user.isVip}}
<div style="background:#fff3cd; padding:12px;">
  <strong>VIP Exclusive:</strong> Your order ships free.
</div>
{{/if}}
```

**Locale/language block (Liquid):**
```liquid
{% case user.locale %}
{% when "fr" %}
  <p>Merci pour votre commande.</p>
{% when "de" %}
  <p>Vielen Dank für Ihre Bestellung.</p>
{% else %}
  <p>Thank you for your order.</p>
{% endcase %}
```
Source: [Liquid Tags — case/when](https://shopify.github.io/liquid/tags/control-flow/#casewhen)

**Mailchimp merge tag conditional:**
```
*|IF:MEMBER_RATING >= 4|*
You are one of our top customers!
*|END:IF|*
```
Source: [Mailchimp Conditional Merge Tag Blocks](https://mailchimp.com/help/use-conditional-merge-tag-blocks/)

### Variable Substitution with Fallbacks

Missing variables in templates can produce blank spaces, broken sentences, or layout shifts. Each engine provides a fallback mechanism.

| Engine | Fallback syntax |
|---|---|
| Jinja2 | `{{ name \| default("Valued Customer") }}` |
| Liquid | `{{ name \| default: "Valued Customer" }}` |
| Nunjucks | `{{ name \| default("Valued Customer") }}` |
| Handlebars | Custom helper (no built-in default filter) |
| Mustache/Postmark | Section inversion: `{{^name}}Valued Customer{{/name}}` |
| SendGrid HBS | No built-in default; use `{{#if name}}{{name}}{{else}}Valued Customer{{/if}}` |
| React Email | TypeScript default props: `firstName = 'Valued Customer'` |

**Handlebars custom default helper:**
```javascript
Handlebars.registerHelper('default', (value, fallback) =>
  (value !== undefined && value !== null && value !== '') ? value : fallback
);
// Usage: {{default firstName "Valued Customer"}}
```
Source: [Handlebars.js — Custom Helpers](https://handlebarsjs.com/guide/helpers.html)

**Postmark Mustache inverted section for fallback:**
```mustache
Hi {{#first_name}}{{first_name}}{{/first_name}}{{^first_name}}there{{/first_name}},
```
An inverted section `{{^var}}` renders when `var` is falsy (undefined, false, empty array).
Source: [Mustache(5) — Inverted Sections](https://mustache.github.io/mustache.5.html#Inverted-Sections)

### Numeric and Currency Formatting

Raw floats from application data (`199.9`) must be formatted before rendering. Never trust the application to pre-format every value — use template filters.

```jinja2
{# Jinja2 — custom filter registration #}
{{ item.price | currency }}  {# outputs "$199.90" #}
```

```python
# Register filter in Jinja2 env
def currency_filter(value, symbol="$"):
    return f"{symbol}{value:,.2f}"

env.filters["currency"] = currency_filter
```

```liquid
{{ item.price | money }}   {# Liquid — requires money filter defined in context #}
{{ 199.9 | round: 2 }}     {# outputs 199.9 — round does not add trailing zero #}
```

```handlebars
{{formatCurrency price}}
```
```javascript
Handlebars.registerHelper('formatCurrency', (value) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
);
```

**Pitfall:** Liquid's built-in `money` filter is only available in the Shopify context. In `liquidjs` or self-hosted Liquid, you must register it as a custom filter.
Source: [LiquidJS — Custom Filters](https://liquidjs.com/tutorials/register-filters-tags.html)

---

## Compiled Output & Validation

### What Each Tool Generates

**MJML**

MJML outputs a single self-contained HTML file with:
- Nested `<table>` / `<tr>` / `<td>` layout structures for cross-client compatibility.
- All CSS inlined as `style` attributes on every element.
- MSO (Microsoft Office) conditional comments for Outlook's Word rendering engine:
  ```html
  <!--[if mso | IE]>
  <table role="none" ... >
  <![endif]-->
  ```
- A `<style>` block in `<head>` for media queries (responsive breakpoints). Most email clients ignore the `<head>` style block, so MJML duplicates critical rules inline.
- Output is typically 200–600 lines for a simple transactional email. Do not manually edit compiled output — regenerate from source.

**Note on MJML v5:** The `<body>` tag structure in compiled output changes in v5 (now controlled by `mj-body`). HTML formatting is also affected by the switch from `js-beautify` to `htmlnano`. Run visual regression tests when upgrading.

Source: [MJML Documentation](https://documentation.mjml.io/)

**Handlebars / Jinja2 / Nunjucks / Liquid (server-side render)**

These produce standard HTML strings. The quality of the output depends entirely on the template source. Common issues in compiled output:
- Whitespace inflation: Jinja2 and Nunjucks block tags produce newlines, which can cause extra whitespace in `<table>` cells. Use whitespace control (`{%- -%}`) to strip surrounding whitespace.
- HTML encoding: Jinja2 and Handlebars HTML-escape output by default (`<` → `&lt;`). Liquid does the same. If application data contains intentional HTML (e.g. a rich-text product description), use the unescaped output tag (`{{{ }}}` in Handlebars, `{{ x | safe }}` in Jinja2, `{{ x | raw }}` in Nunjucks). Treat any un-escaped content as a potential XSS vector — sanitise before rendering.

**Jinja2 whitespace control:**
```jinja2
{%- for item in items -%}
<tr><td>{{ item.name }}</td></tr>
{%- endfor -%}
```
The `-` modifier strips whitespace before and after the tag.
Source: [Jinja2 — Whitespace Control](https://jinja.palletsprojects.com/en/stable/templates/#whitespace-control)

**React Email**

React Email renders via `render()` from `@react-email/components`, which calls React's server-side renderer. Output is a complete HTML string with inline styles. The framework does not automatically generate MSO Outlook conditionals or table-based layout — this is the developer's responsibility (or handled by components within the library). The rendered output does not require a separate compile step; rendering happens at runtime when the component function is called.

### Common Pitfalls in Compiled HTML

| Pitfall | Engine(s) | Symptom | Fix |
|---|---|---|---|
| Unclosed tags in loop body | All | Broken layout below loop | Validate output HTML with an HTML parser |
| Double-escaped entities | Jinja2, HBS | `&amp;lt;` in rendered output | Ensure input data is not pre-escaped; let the engine escape once |
| Missing `alt` on images | MJML, all | Accessibility failure; broken layout in image-blocking clients | Always set `mj-image alt=""` explicitly |
| Empty `href` on links | All | Broken CTA buttons | Use fallback: `{{url \| default: "#"}}` |
| Outlook ignores `<style>` | MJML output | Responsive styles ignored in Outlook | MJML handles this via MSO conditionals — do not strip them post-compile |
| `NaN` / `undefined` rendered | HBS, Jinja2 | "undefined" visible in email | Use fallback filters / helpers on all variable output |
| Liquid `money` filter missing | LiquidJS | Template error / blank | Register custom filter before render |
| Extra whitespace in `<a>` | Nunjucks | Underline extends past link text in some clients | Use `{%- -%}` whitespace control |
| MJML v5 body structure change | MJML v5 | Layout differences vs v4 output | Re-test all templates after upgrading to v5 |
| React Email missing Outlook conditionals | React Email | Layout breaks in Outlook | Use explicit table-based layouts or MSO-aware components |

### Validating Compiled Output

**1. MJML validator (build-time)**

The MJML CLI exits with a non-zero code on invalid syntax:
```bash
mjml --validate src/order-confirmation.mjml
```
Invalid MJML component attributes (e.g. unrecognised `mj-text` attribute) produce warnings but still compile; validate that compiled output is visually correct.
Source: [MJML CLI Documentation](https://documentation.mjml.io/)

**2. Postmark template validation API**

Postmark exposes a dedicated endpoint to validate template syntax before deployment:
```bash
curl -X POST https://api.postmarkapp.com/templates/validate \
  -H "X-Postmark-Server-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "Subject": "Order {{order_id}}",
    "HtmlBody": "<p>Hello {{#first_name}}{{first_name}}{{/first_name}}!</p>",
    "TestRenderModel": { "order_id": "ORD-001", "first_name": "Alice" }
  }'
```
The response contains `AllContentIsValid`, `HtmlBody.ValidationErrors`, and `SuggestedTemplateModel`.
Source: [Postmark API — Validate Template](https://postmarkapp.com/developer/api/templates-api#validate-template)

**3. HTML validation and linting**

Use `html-validate` (npm) or `tidy` to catch structural issues:
```bash
html-validate dist/order-confirmation.html
```
For email-specific validation, use the Email on Acid API or Litmus API to programmatically run cross-client previews.

**4. Rendering smoke tests**

Write unit tests that render each template with representative fixture data and assert:
- No `undefined`, `null`, `NaN`, or `{{...}}` strings appear in the output (indicates un-resolved variables).
- All `href` and `src` attributes are non-empty.
- The HTML is parseable by an HTML parser without errors.

**Jest / Node.js example:**
```javascript
const Handlebars = require('handlebars');
const fs = require('fs');

test('order confirmation renders without unresolved variables', () => {
  const source = fs.readFileSync('dist/order-confirmation.html', 'utf8');
  const template = Handlebars.compile(source);
  const html = template({
    firstName: 'Alice',
    order: { id: 'ORD-001', items: [{ name: 'Widget', qty: 1, price: '9.99' }] }
  });
  expect(html).not.toMatch(/undefined/);
  expect(html).not.toMatch(/\{\{/);
});
```

**Python / pytest example:**
```python
from jinja2 import Environment, FileSystemLoader

def test_order_confirmation_no_unresolved_vars():
    env = Environment(loader=FileSystemLoader("templates/"), autoescape=True)
    template = env.get_template("order_confirmation.html")
    html = template.render(
        first_name="Alice",
        order={"id": "ORD-001", "items": [{"name": "Widget", "quantity": 1, "unit_price": 9.99}]},
        year=2026
    )
    assert "undefined" not in html
    assert "{{" not in html
```

**5. Character encoding**

Always declare `charset=UTF-8` in the compiled HTML `<head>`. MJML does this automatically. For manually authored templates, include:
```html
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta charset="UTF-8">
```
Some older email clients (notably Outlook 2007) use the `Content-Type` `http-equiv` over the HTML5 `charset` attribute.
Source: [Mailchimp — Email Design Reference: Character Sets](https://mailchimp.com/resources/email-design-reference/)

---

## Framework Comparison Summary

| | MJML | React Email | Maizzle | Handlebars/Jinja2/Nunjucks | Liquid |
|---|---|---|---|---|---|
| **Current version** | 4.18.0 (v5 beta) | 5.2.10 | 5.5.0 | — (stable) | — (stable) |
| **Language** | XML DSL | React/TSX | HTML + Tailwind | JS / Python / JS | Ruby / JS (liquidjs) |
| **Layout abstraction** | High (auto tables + MSO) | Low (manual) | Medium (Tailwind, manual tables) | None | None |
| **Dynamic data** | None (separate layer needed) | TypeScript props | Separate layer needed | Core feature | Core feature |
| **Outlook MSO support** | Automatic | Manual | Manual | n/a | n/a |
| **Type safety** | None | TypeScript | None | None | None |
| **ESP-native use** | No | No | No | SendGrid, Mandrill | Klaviyo |
| **Production ready** | Yes | Yes | Yes | Yes | Yes |

---

## Sources

| Source | URL |
|---|---|
| MJML Documentation | https://documentation.mjml.io/ |
| MJML GitHub — Releases | https://github.com/mjmlio/mjml/releases |
| Handlebars.js Guide | https://handlebarsjs.com/guide/ |
| Handlebars Built-In Helpers | https://handlebarsjs.com/guide/builtin-helpers.html |
| Handlebars Custom Helpers | https://handlebarsjs.com/guide/helpers.html |
| Liquid Documentation (Shopify GitHub) | https://shopify.github.io/liquid/ |
| Liquid Filters — default | https://shopify.github.io/liquid/filters/default/ |
| Liquid Tags — for | https://shopify.github.io/liquid/tags/iteration/ |
| Liquid Tags — case/when | https://shopify.github.io/liquid/tags/control-flow/#casewhen |
| Jinja2 Documentation | https://jinja.palletsprojects.com/en/stable/ |
| Jinja2 Template Inheritance | https://jinja.palletsprojects.com/en/stable/templates/#template-inheritance |
| Jinja2 Whitespace Control | https://jinja.palletsprojects.com/en/stable/templates/#whitespace-control |
| Jinja2 For Loop | https://jinja.palletsprojects.com/en/stable/templates/#for |
| Nunjucks Documentation (Mozilla) | https://mozilla.github.io/nunjucks/ |
| Nunjucks Macros | https://mozilla.github.io/nunjucks/templating.html#macro |
| Nunjucks For Tag | https://mozilla.github.io/nunjucks/templating.html#for |
| React Email Documentation | https://react.email/docs/introduction |
| React Email GitHub — Releases | https://github.com/resend/react-email/releases |
| Maizzle Framework (GitHub) | https://github.com/maizzle/framework |
| LiquidJS npm | https://www.npmjs.com/package/liquidjs |
| LiquidJS Custom Filters | https://liquidjs.com/tutorials/register-filters-tags.html |
| SendGrid Dynamic Templates | https://docs.sendgrid.com/ui/sending-email/how-to-send-an-email-with-dynamic-templates |
| SendGrid API — Send Mail | https://docs.sendgrid.com/api-reference/mail-send/mail-send |
| SendGrid Handlebars Reference | https://docs.sendgrid.com/for-developers/sending-email/using-handlebars |
| Mailchimp Merge Tags Cheat Sheet | https://mailchimp.com/help/all-the-merge-tags-cheat-sheet/ |
| Mailchimp Conditional Merge Tag Blocks | https://mailchimp.com/help/use-conditional-merge-tag-blocks/ |
| Mailchimp Email Design Reference | https://mailchimp.com/resources/email-design-reference/ |
| Mandrill API — Messages | https://mailchimp.com/developer/transactional/api/messages/send-using-message-template/ |
| Postmark Templating Documentation | https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates |
| Postmark API — Validate Template | https://postmarkapp.com/developer/api/templates-api#validate-template |
| Klaviyo Developer Docs — Liquid Overview | https://developers.klaviyo.com/en/docs/liquid-overview |
| Mustache(5) Man Page — Sections | https://mustache.github.io/mustache.5.html#Sections |
| Mustache(5) Man Page — Inverted Sections | https://mustache.github.io/mustache.5.html#Inverted-Sections |

---

## TODOs

- [ ] Verify whether SendGrid's Handlebars subset supports `@index`, `@first`, `@last` loop metadata — documentation is ambiguous; confirm by live test against the SendGrid API.
- [ ] Add a worked example of MJML + Handlebars hybrid pipeline (MJML compile → Handlebars render → SendGrid API send) as a runnable Node.js script.
- [ ] Document Klaviyo's Liquid extensions beyond standard Liquid (e.g. `person` object properties, event properties access syntax).
- [ ] Monitor MJML v5 stability — currently at v5.0.0-beta.1 (March 2025). Track release for production-readiness, especially the include security changes and Node 20+ requirement.
- [ ] Add cross-client test matrix: which email clients support which CSS properties that MJML relies on; link to caniemail.com as reference.
- [ ] Document Mailchimp Transactional (Mandrill) `merge_language: "handlebars"` vs default merge tag behaviour — confirm which Handlebars helpers are available in Mandrill vs SendGrid.
- [ ] Add section on preview text / preheader patterns: the invisible text after the subject line that appears in inbox previews, and how to inject it via each templating engine (MJML uses `mj-preview`; React Email uses `<Preview>`).
- [ ] Add dark mode CSS patterns — `@media (prefers-color-scheme: dark)` support in MJML and its limits in Outlook.
- [ ] Add guidance on template testing tools: Litmus, Email on Acid, and their programmatic APIs for CI integration.
- [ ] Expand React Email section with full component list and Tailwind integration details once rate-limit issues with react.email docs resolve.
- [ ] Add Maizzle worked example showing Tailwind-based email template and compilation output.

COMPLETE
