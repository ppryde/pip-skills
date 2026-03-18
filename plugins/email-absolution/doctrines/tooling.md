# Tooling Overview — Email Doctrine

## Purpose

Selection guidance and cross-tool rules for email templating pipelines. This doctrine is the tooling overview — it covers when to use each engine, pipeline architecture patterns, and rules that apply regardless of which templating tool is selected. The per-language doctrines (mjml.md, handlebars.md, liquid.md, react-email.md, maizzle.md) cover tool-specific rules.

**Loading note:** Elder and visitation load this overview alongside the per-language doctrine. Scribe loads only the per-language doctrine — it does not load this file.

## Rule Catalog

---

**[TOOL-001]** `mortal` — Declare the templating stack in `.email-absolution/config.yml` as `stack.templating`.
> Without this declaration, skills cannot load the correct per-language doctrine. The scribe skill will refuse to generate code until a templating language is declared. Source: email-absolution plugin config schema.
> `detect: contextual` — check `.email-absolution/config.yml` for `stack.templating` field

**[TOOL-002]** `mortal` — Do not mix templating syntax from two different engines in one template file.
> Handlebars `{{#each}}` inside a Liquid template causes partial renders without errors. The Liquid engine passes `{{#each}}` through as literal text; recipients see raw template syntax. The same applies to Mustache `{{#section}}` inside Handlebars, or Jinja2 `{% for %}` inside a Nunjucks file that uses a non-compatible Jinja2 filter. Source: engineering incident patterns.
> `detect: contextual` — check template files for mixed syntax markers from multiple engines

**[TOOL-003]** `mortal` — Compiled output (MJML `dist/`, Maizzle `build/`) must never be hand-edited.
> The next compile overwrites any manual changes. Edits to compiled output create invisible drift between source and deployed HTML — the next CI build deploys source-derived output that silently discards the hand-edit.
> `detect: contextual` — check if dist/build files are committed with modifications not reflected in source

**[TOOL-004]** `mortal` — Pin email toolchain versions exactly in `package.json` or `requirements.txt`.
> MJML patch releases have changed spacing and table structure. React Email patch releases have changed component HTML output. Maizzle v4 → v5 changed the build engine. Tailwind v3 → v4 is a breaking change. Floating semver (`^`, `~`) causes undetected visual regressions on `npm install` or `pip install`.
> `detect: contextual` — check package.json / requirements.txt for caret/tilde ranges on email toolchain packages

**[TOOL-005]** `mortal` — MJML v5 (beta as of March 2025) must not be used in production without thorough visual regression testing.
> Breaking changes in MJML v5: file includes disabled by default (security), minification backend replaced (htmlnano/cssnano replaces html-minifier/js-beautify), `mj-body` HTML structure changed, Node.js 16/18 dropped (requires 20, 22, or 24). Source: MJML v5.0.0-beta.1 changelog, March 2025.
> `detect: contextual` — check package.json for MJML version; flag beta/v5 references

**[TOOL-006]** `mortal` — Test the full rendering pipeline end-to-end, not only the template output.
> Screenshot tools (Litmus, Email on Acid) do not test: dynamic rendering failures, broken ESP API calls, missing MIME parts, or truncation at the 102 KB Gmail clip. A screenshot test can pass while a production send fails silently. Source: Email on Acid "Limitations of Screenshot Testing".
> `detect: contextual` — advisory; verify test suite includes a real send-and-receive test

**[TOOL-007]** `venial` — Use the build-step compilation pattern for MJML and Maizzle: compile at CI time, inject data at runtime.
> Compiling MJML at send time (per-request) introduces compile latency into the send path. Pre-compiled HTML is a static asset; data injection at send time is fast. Source: MJML Documentation "Use with Node.js".
> `detect: contextual` — advisory; check if MJML compilation happens at build/CI or at send time

**[TOOL-008]** `venial` — ESP-native templates (SendGrid Dynamic Templates, Postmark Templates, Mailchimp) create vendor lock-in. Document this trade-off explicitly.
> Template source lives inside the ESP. Migrating ESPs requires rewriting all templates. Logic capabilities are limited to what the ESP exposes (SendGrid's Handlebars subset lacks custom helpers; Postmark is Mustache with no block helpers). Source: SendGrid and Postmark documentation.
> `detect: contextual` — if stack.esp is "sendgrid" or "postmark", flag that templates live in the ESP

**[TOOL-009]** `venial` — Maintain a plain-text version for every email template.
> React Email, MJML, and Maizzle do not generate plain text automatically. Author plain text manually or use a library (`html-to-text` for Node.js, `premailer` for Python/Ruby). Plain-text parts are required for DELIV-007 compliance and are read by spam filters. Source: SpamAssassin rule documentation.
> `detect: contextual` — check if project has a plain-text generation strategy

**[TOOL-010]** `venial` — In the MJML + ESP hybrid pattern, verify that ESP placeholder syntax is preserved verbatim through MJML compilation.
> MJML does not interpret non-MJML content. `{{first_name}}` (Handlebars) or `{{ first_name }}` (Liquid) inside `<mj-text>` compiles through to the output HTML unchanged. However, some preprocessors or minifiers may mangle double-brace syntax. Verify with a compilation smoke test. Source: MJML Documentation.
> `detect: contextual` — run compilation smoke test and grep for placeholder syntax in dist output

**[TOOL-011]** `counsel` — Use MJML when the team needs cross-client responsive layout without hand-writing table/VML markup and the template set is moderate in size.
> MJML compiles `.mjml` XML to cross-client HTML with inlined CSS, MSO conditionals, and VML buttons automatically. Best for teams with a JavaScript build pipeline and 5–50 templates. Not suited to teams that need full control of generated HTML.
> `detect: contextual` — selection guidance

**[TOOL-012]** `counsel` — Use Handlebars when the team is in a Node.js/JavaScript stack and needs a familiar, logic-minimal templating language with custom helper support.
> Handlebars is widely understood, has an excellent helper ecosystem, and integrates natively with SendGrid Dynamic Templates (Handlebars subset). Best for JavaScript-first teams. Note: SendGrid's Handlebars subset omits `@index`/`@first`/`@last` loop metadata and custom helpers — see HBS-003.
> `detect: contextual` — selection guidance

**[TOOL-013]** `counsel` — Use Liquid when sending via Klaviyo or another Liquid-native ESP, or when the team prioritises sandboxed rendering safety.
> Liquid has no filesystem access and cannot execute arbitrary code — safe to evaluate user-influenced templates. It is the native language of Klaviyo's template engine. Ruby and JavaScript ports are production-grade. Source: Shopify Liquid open-source documentation.
> `detect: contextual` — selection guidance

**[TOOL-014]** `counsel` — Use React Email when the team is TypeScript-first and wants compile-time type checking of email data shapes.
> React Email's primary advantage over text templating is typed component props. A data model change that renames `order.id` to `order.orderId` fails the TypeScript build rather than silently sending broken emails. Suited to Node.js stacks where application models can be shared with email component interfaces. Source: React Email Documentation.
> `detect: contextual` — selection guidance

**[TOOL-015]** `counsel` — Use Maizzle when the team is fluent in Tailwind CSS and prefers writing plain HTML rather than learning MJML's component model.
> Maizzle applies Tailwind's utility workflow to email, compiling and inlining CSS at build time. It does not abstract table-based layout — developers write tables directly or use Maizzle starter templates. Best for Tailwind-fluent teams who want that workflow without MJML's DSL. Source: Maizzle Framework documentation.
> `detect: contextual` — selection guidance

---

## Patterns & Code Examples

### Stack declaration in `.email-absolution/config.yml`

```yaml
# .email-absolution/config.yml
stack:
  templating: mjml          # options: mjml | handlebars | liquid | react-email | maizzle
  esp: sendgrid             # options: sendgrid | postmark | mailgun | ses | klaviyo | resend | custom
  language: typescript      # project language — informs code examples in scribe

email_defaults:
  from_name: "Acme"
  from_email: "hello@acme.com"
  reply_to: "support@acme.com"
  locale: "en-GB"
  tone: transactional       # transactional | marketing | digest

unsubscribe:
  enabled: false            # set true for marketing/subscribed sends
```

### Build pipeline: MJML + runtime data injection

```
[.mjml source files]
    |
    v  mjml compile (build step / CI)
         mjml src/order-confirmation.mjml -o dist/order-confirmation.html
[static HTML with {{placeholders}} intact]
    |
    v  Handlebars/Liquid/Mustache render (runtime / send time)
         template({ firstName: user.firstName, order: order })
[per-recipient HTML string]
    |
    v  ESP API (SendGrid /v3/mail/send, SES SendRawEmail, Postmark /email)
```

Separation of concerns: MJML owns layout and cross-client compatibility. The runtime templating layer owns per-recipient data injection. Neither concerns itself with the other.

### package.json version pinning — email toolchain

```json
{
  "dependencies": {
    "mjml": "4.18.0",
    "handlebars": "4.7.8",
    "@react-email/components": "0.0.31",
    "liquidjs": "10.19.0"
  },
  "devDependencies": {
    "maizzle": "5.5.0",
    "tailwindcss": "3.4.17"
  }
}
```

Use exact versions (no `^` or `~`) for all email rendering tools. The email output is a deployed artefact — treat version changes with the same care as infrastructure upgrades.

### Engine selection — quick reference

| Situation | Recommended engine |
|-----------|-------------------|
| Cross-client responsive layout, JS team, 5–50 templates | MJML |
| Node.js/JS stack, custom data formatting helpers, SendGrid | Handlebars |
| Klaviyo, Shopify, or sandboxed rendering required | Liquid |
| TypeScript-first, typed data models, React codebase | React Email |
| Tailwind-fluent team, full HTML control, no DSL | Maizzle |
| ESP-native, non-engineering editors, small template set | SendGrid Dynamic Templates / Postmark |

### React Email + Resend send pipeline

```typescript
// emails/order-confirmation.tsx
import { Html, Head, Preview, Body, Container, Text, Button } from '@react-email/components';

interface Props {
  firstName?: string;
  orderId: string;
  trackingUrl: string;
}

export default function OrderConfirmation({
  firstName = 'Valued Customer',
  orderId,
  trackingUrl,
}: Props) {
  return (
    <Html lang="en">
      <Head />
      <Preview>Your order {orderId} has been confirmed.</Preview>
      <Body style={{ fontFamily: 'Arial, sans-serif', backgroundColor: '#ffffff' }}>
        <Container style={{ maxWidth: '600px', margin: '0 auto' }}>
          <Text>Hi {firstName},</Text>
          <Text>Your order <strong>{orderId}</strong> is confirmed.</Text>
          <Button href={trackingUrl}
                  style={{ backgroundColor: '#0066cc', color: '#ffffff',
                           padding: '12px 24px', borderRadius: '4px' }}>
            Track Your Order
          </Button>
        </Container>
      </Body>
    </Html>
  );
}
```

```typescript
// send.ts
import { render } from '@react-email/components';
import { Resend } from 'resend';
import OrderConfirmation from './emails/order-confirmation';

const resend = new Resend(process.env.RESEND_API_KEY);

await resend.emails.send({
  from: 'Acme <hello@acme.com>',
  to: user.email,
  subject: `Your order #${order.id} is confirmed`,
  html: await render(<OrderConfirmation firstName={user.firstName}
                                         orderId={order.id}
                                         trackingUrl={order.trackingUrl} />),
});
```

### Liquid + Klaviyo event-triggered pipeline

```liquid
{# Klaviyo template: Order Shipped event trigger #}
Hi {{ person.first_name | default: "Valued Customer" | capitalize }},

Your order {{ event.extra.order_id }} has shipped.

Estimated delivery: {{ event.extra.delivery_date | date: "%B %-d, %Y" }}

{% if event.extra.tracking_url %}
Track your parcel: {{ event.extra.tracking_url }}
{% endif %}

--
{{ organization.name }}
{{ organization.address | default: "" }}
Unsubscribe: {{ unsubscribe_link }}
```

The Klaviyo `event` object exposes properties passed in the track event payload. `person` exposes profile properties. `organization` is provided by Klaviyo from account settings.

### Maizzle build commands reference

```bash
# Local development — browser preview with hot reload
maizzle serve

# Production build — CSS inlined, minified, URL rewriting applied
maizzle build production

# Build for specific environment
maizzle build staging

# Preview compiled output without full production settings
maizzle build local
```

## Support Matrix

| Engine | Language | Layout abstraction | Type safety | ESP-native option |
|--------|----------|-------------------|-------------|------------------|
| MJML | XML/HTML | Full (tables + VML) | None | No |
| Handlebars | JS/TS | None | Via TypeScript wrapper | SendGrid (subset) |
| Liquid | Ruby/JS | None | None | Klaviyo, Shopify |
| React Email | TypeScript/JSX | Partial (components) | Full (TypeScript) | Resend |
| Maizzle | HTML + Tailwind | None | None | No |
| Mustache | Any | None | None | Postmark |

## Known Afflictions

**MJML v5 file includes disabled by default** — MJML v5 disables `<mj-include>` by default as a security measure (prevents reading arbitrary files when user-supplied MJML is processed server-side). Teams migrating from v4 who use `<mj-include>` for shared components will find includes silently ignored. Enable via `mjml.config.js` if running in a trusted build environment.
Affects: MJML v5+. Source: MJML v5.0.0-beta.1 release notes.

**SendGrid Handlebars subset limitations** — SendGrid Dynamic Templates use a subset of Handlebars that does not support custom helpers or `@index`/`@first`/`@last` loop metadata. Templates that work in local Handlebars.js fail silently in SendGrid. Always test in the actual ESP environment, not only locally.
Affects: SendGrid Dynamic Templates. Source: SendGrid documentation.

**Plain-text generation not automatic** — MJML, React Email, and Maizzle generate HTML only. Plain-text MIME parts are required by RFC 2046 and read by spam filters. Teams using these frameworks often omit plain text, raising spam scores and violating DELIV-007. Use `html-to-text` (Node.js) or `premailer` (Python/Ruby) to generate plain text from compiled HTML.
Affects: All template engines. Source: Postmark deliverability guide.

**Tailwind v3 → v4 breaking change** — Tailwind CSS v4 has significant breaking changes that affect how Maizzle and `@react-email/tailwind` operate. Teams running `tailwindcss@^3` who run `npm update` may inadvertently upgrade to v4 if the caret range is used. Pin exactly.
Affects: Maizzle, React Email with `@react-email/tailwind`. Source: Tailwind CSS v4 migration guide.

**No email-safe Tailwind defaults without explicit config** — Standard Tailwind CSS generates classes like `flex`, `grid`, and `var(--colour)` that are not email-safe. Neither `@react-email/tailwind` nor Maizzle automatically restricts Tailwind to email-safe utilities. Teams must audit class usage and avoid flex/grid/custom-properties for structural layout.
Affects: Maizzle, React Email with `@react-email/tailwind`. Source: caniemail.com feature support data.

## Tooling Architecture Decision Records

When a project adopts an email templating engine, document the decision in the project's `.email-absolution/config.yml` with a comment explaining why. These decisions are revisited infrequently but have large migration costs.

```yaml
# .email-absolution/config.yml
stack:
  templating: mjml
  # Decision: MJML chosen March 2026 because:
  # - Team is Node.js/TypeScript; no Python stack
  # - 25 email templates; manageable size
  # - Needed responsive layout without hand-writing Outlook tables
  # - SendGrid is ESP; MJML + Handlebars hybrid pattern selected
  # - Revisit if template count exceeds 100 or team moves to React-first
  esp: sendgrid
```

Record what was **not** chosen and why — this prevents re-evaluating the same trade-offs in 18 months without institutional memory.

## Sources

1. **MJML Documentation** — https://documentation.mjml.io/ — Component reference, Node.js API, v5 changelog.
2. **React Email Documentation** — https://react.email/docs/introduction — Rendering, components, integrations.
3. **Maizzle Framework** — https://maizzle.com — Build pipeline, Tailwind integration, starter templates.
4. **SendGrid Dynamic Templates** — https://docs.sendgrid.com/ui/sending-email/how-to-send-an-email-with-dynamic-templates — Handlebars subset documentation.
5. **Postmark Developer Docs** — https://postmarkapp.com/developer/user-guide/send-email-with-api/send-with-templates — Mustache syntax, template validation API.
6. **Klaviyo Developer Docs** — https://developers.klaviyo.com/en/docs/liquid-overview — Liquid implementation.
7. **Handlebars.js Guide** — https://handlebarsjs.com/guide/ — Helper registration, partials, built-in helpers.
8. **LiquidJS** — https://liquidjs.com — JavaScript Liquid port, strictVariables config.
