# React Email — Email Doctrine

## Purpose

Rules and gotchas for engineers building email templates with React Email — the Resend-maintained React/TypeScript email component library (`react-email@5.2.10`, March 2026). React Email renders React components to HTML strings server-side. It does not abstract cross-client layout like MJML — engineers remain responsible for email-safe CSS. Its primary advantage over text-based templating is TypeScript compile-time checking of email data shapes.

## Rule Catalog

---

**[REMAIL-001]** `transactional: mortal | marketing: mortal` — Render components server-side only — never in the browser.
> React Email `render()` produces static HTML strings. Components have no runtime DOM interaction, event handlers, or client state. They must be invoked from Node.js server context (API route, serverless function, background job queue) — not from a browser bundle. Importing email components into client-side React bundles increases bundle size and produces no useful output. Source: React Email documentation.
> `detect: contextual` — check that `render()` / `renderAsync()` calls are in server-side code only

**[REMAIL-002]** `transactional: mortal | marketing: mortal` — All required props must have TypeScript defaults or explicit runtime guards.
> Missing required data at send time produces garbled output or rendering errors. TypeScript non-optional props (`firstName: string`, not `firstName?: string`) cause build failures when callers omit them — this is the correct behaviour. Optional props must have defaults: `firstName = 'Valued Customer'`.
> `detect: contextual` — check component prop interfaces; flag optional props without default values

**[REMAIL-003]** `transactional: mortal | marketing: mortal` — Use `<Preview>` for the preheader — do not manually code the hidden preheader div.
> `<Preview>Your order has shipped.</Preview>` generates the correct multi-property hidden div. Manual preheader divs routinely omit `mso-hide:all` or use `display:none` alone, which is insufficient in Outlook preview panes (see GOTCHA-028). Source: React Email documentation.
> `detect: contextual` — check if template has `<Preview>` component; flag hand-coded hidden preheader divs

**[REMAIL-004]** `transactional: mortal | marketing: mortal` — Pass the output of `render()` to the ESP — do not use `ReactDOM.renderToString()`.
> `render()` from `@react-email/components` applies email-specific HTML transformations beyond what `ReactDOM.renderToString()` produces: proper DOCTYPE, attribute serialisation, and email-client compatibility patches. Using `ReactDOM.renderToString()` directly produces subtly wrong HTML.
> `detect: contextual` — check that send path uses `render()` or `renderAsync()` from `@react-email/components`

**[REMAIL-005]** `transactional: mortal | marketing: mortal` — Do not use React hooks in email components.
> `useEffect`, `useState`, `useRef`, `useContext`, `useReducer`, and any other hook require a browser runtime. Email components are pure rendering functions executed in a Node.js SSR context. Hooks throw at render time. Source: React Email FAQ.
> `detect: regex` — pattern: `\buse(?:Effect|State|Ref|Context|Reducer|Callback|Memo|LayoutEffect)\b`

**[REMAIL-006]** `transactional: mortal | marketing: mortal` — Do not use CSS Modules, styled-components, emotion, or any CSS-in-JS that requires a browser runtime or webpack/vite loader.
> Email components render to static HTML strings. CSS Modules generate class names that reference a stylesheet — there is no stylesheet in an email. Styled-components and emotion require the CSS to be injected into the DOM at runtime. Only inline `style` objects and `@react-email/tailwind` utility classes generate CSS in the HTML string. Source: React Email documentation.
> `detect: contextual` — check email component files for CSS module imports or styled-components/emotion usage

**[REMAIL-007]** `transactional: mortal | marketing: mortal` — Pin `@react-email/components` to an exact version.
> React Email has a frequent patch cadence. Output changes between versions affect rendered HTML. Use `"0.0.31"` not `"^0.0.31"`.
> `detect: contextual` — check package.json for caret/tilde on `@react-email/components` and related packages

**[REMAIL-008]** `transactional: venial | marketing: venial` — Type all email component props with explicit TypeScript interfaces.
> `any` prop types defeat the primary advantage of React Email. When `order.items` is typed as `OrderItem[]` (with your application's shared type), renaming a field in `OrderItem` fails the TypeScript build immediately — not a production send.
> `detect: regex` — pattern: `:\s*any\b` in email component prop interfaces

**[REMAIL-009]** `transactional: venial | marketing: venial` — Use `<Img>` from `@react-email/components` — not bare `<img>`.
> `<Img>` applies email-safe defaults: `display: block`, `border: 0`, `max-width: 100%`. These defaults prevent the 4px gap-below-image bug (see RENDER-002) and image overflow in mobile clients.
> `detect: regex` — pattern: `<img\s` (lowercase `img` element — not the React Email component)

**[REMAIL-010]** `transactional: venial | marketing: venial` — Use `<Link>` from `@react-email/components` for hyperlinks — not bare `<a>`.
> `<Link>` applies email-safe inline style defaults including `text-decoration: none` overrides and properly serialises the `href` attribute for email clients.
> `detect: regex` — pattern: `<a\s+(?:href|style)=` outside of MSO conditional comment blocks

**[REMAIL-011]** `transactional: venial | marketing: venial` — Use `<Button>` for CTAs and verify the rendered output includes VML for Outlook targets.
> React Email's `<Button>` renders an `<a>` with inline styles. Check whether the compiled output from your React Email version includes the VML bulletproof button pattern for Outlook 2007–2019. If it does not, manually wrap with MSO conditional VML (see RENDER-014).
> `detect: contextual` — check compiled HTML output for VML when `<Button>` is used with Outlook as a target client

**[REMAIL-012]** `transactional: venial | marketing: venial` — All `href` values in `<Link>` and `<Button>` must be absolute HTTPS URLs.
> React Email does not validate URLs. Relative `href` values (e.g. `href="/track/TOKEN"`) fail in all email clients — there is no base URL in email (see GOTCHA-025).
> `detect: contextual` — check `href` prop values for relative URL patterns

**[REMAIL-013]** `transactional: venial | marketing: venial` — Generate a plain-text version alongside the HTML. React Email does not do this automatically.
> `render()` returns HTML only. The plain-text MIME part is required for DELIV-007 compliance and is read by spam filters. Use the `html-to-text` npm package or maintain a parallel plain-text template. Source: Postmark deliverability guide.
> `detect: contextual` — check send path for plain-text generation alongside the HTML render

**[REMAIL-014]** `transactional: venial | marketing: venial` — Use `<Container>` as the email wrapper — not a bare `<div>` with inline style.
> `<Container>` generates a table-based centered wrapper compatible with Outlook 2007–2019. A `<div style={{maxWidth: '600px', margin: '0 auto'}}>` does not centre in Outlook Windows — it requires the table approach. Source: React Email documentation.
> `detect: contextual` — check outer layout structure uses `<Container>` not bare `<div>`

**[REMAIL-015]** `transactional: venial | marketing: venial` — Use `renderAsync()` for components that contain async data fetching.
> `render()` is synchronous. If a component calls `await fetch(...)` or resolves a database query during rendering, use `renderAsync()`. Calling `render()` on an async component silently produces incomplete output without an error.
> `detect: contextual` — check for async component functions used with synchronous `render()`

**[REMAIL-016]** `transactional: counsel | marketing: counsel` — Use the development preview server (`@react-email/preview-server`) for visual development.
> The preview server renders all `.tsx` email templates in a specified directory with hot reload and a browser preview. It is significantly faster than the send-and-receive testing loop for visual iteration.
> `detect: contextual` — advisory

**[REMAIL-017]** `transactional: counsel | marketing: counsel` — Use `<Hr>` for visual dividers — not `<div>` borders or background-colour `<tr>` rows.
> `<Hr>` from `@react-email/components` renders a `<hr>` with email-safe inline styles that display consistently across Outlook and modern clients.
> `detect: contextual` — advisory

**[REMAIL-018]** `transactional: counsel | marketing: counsel` — Share TypeScript type definitions between application models and email component props where possible.
> The primary advantage of React Email over text templating systems is this integration. If `Order`, `LineItem`, and `User` types are shared, data-shape mismatches surface as build errors. Maintain the shared import rather than duplicating type definitions in the email package.
> `detect: contextual` — advisory; check if email components import shared types from the application domain layer

---

## Patterns & Code Examples

### Full component with typed props, Preview, Container, Button

```tsx
import {
  Html, Head, Preview, Body, Container, Section,
  Heading, Text, Hr, Button, Img
} from '@react-email/components';

interface OrderItem {
  name: string;
  quantity: number;
  unitPrice: number;
}

interface OrderConfirmationProps {
  firstName?: string;
  orderId: string;
  orderItems: OrderItem[];
  orderTotal: number;
  trackingUrl: string;
  estimatedDelivery: string;
}

export default function OrderConfirmation({
  firstName = 'Valued Customer',
  orderId,
  orderItems,
  orderTotal,
  trackingUrl,
  estimatedDelivery,
}: OrderConfirmationProps) {
  return (
    <Html lang="en">
      <Head />
      <Preview>Your order {orderId} is confirmed — arriving {estimatedDelivery}.</Preview>
      <Body style={{ backgroundColor: '#f4f4f4', fontFamily: 'Arial, sans-serif', margin: 0 }}>
        <Container style={{ maxWidth: '600px', margin: '0 auto', backgroundColor: '#ffffff', padding: '0' }}>
          <Section style={{ padding: '32px 24px 0' }}>
            <Heading as="h1" style={{ fontSize: '22px', color: '#333333', margin: '0 0 16px' }}>
              Order confirmed
            </Heading>
            <Text style={{ fontSize: '14px', lineHeight: '1.5', color: '#333333' }}>
              Hi {firstName}, your order <strong>{orderId}</strong> is confirmed.
            </Text>
            <Text style={{ fontSize: '14px', color: '#333333' }}>
              Estimated delivery: <strong>{estimatedDelivery}</strong>
            </Text>
          </Section>

          <Section style={{ padding: '16px 24px' }}>
            {orderItems.map((item, i) => (
              <Text key={i} style={{ fontSize: '14px', color: '#333333', margin: '0 0 8px' }}>
                {item.name} × {item.quantity} — £{item.unitPrice.toFixed(2)}
              </Text>
            ))}
            <Hr style={{ borderColor: '#e5e5e5', margin: '16px 0' }} />
            <Text style={{ fontSize: '16px', fontWeight: 'bold', color: '#333333' }}>
              Total: £{orderTotal.toFixed(2)}
            </Text>
          </Section>

          <Section style={{ padding: '0 24px 32px', textAlign: 'center' }}>
            <Button href={trackingUrl}
                    style={{ backgroundColor: '#0066cc', color: '#ffffff',
                             padding: '12px 24px', borderRadius: '4px',
                             fontSize: '16px', fontWeight: 'bold',
                             textDecoration: 'none', display: 'inline-block' }}>
              Track Your Order
            </Button>
          </Section>
        </Container>
      </Body>
    </Html>
  );
}
```

### render() + send via Resend

```typescript
import { render } from '@react-email/components';
import { Resend } from 'resend';
import OrderConfirmation from './emails/order-confirmation';
import { htmlToText } from 'html-to-text';

const resend = new Resend(process.env.RESEND_API_KEY);

async function sendOrderConfirmation(user: User, order: Order) {
  const html = await render(
    <OrderConfirmation
      firstName={user.firstName}
      orderId={order.id}
      orderItems={order.items}
      orderTotal={order.total}
      trackingUrl={`https://track.acme.com/${order.id}`}
      estimatedDelivery={formatDate(order.estimatedDelivery)}
    />
  );

  // Generate plain text from HTML for MIME compliance
  const text = htmlToText(html, { wordwrap: 80 });

  await resend.emails.send({
    from: 'Acme <hello@acme.com>',
    to: user.email,
    subject: `Your order #${order.id} is confirmed`,
    html,
    text,
  });
}
```

### @react-email/tailwind with Tailwind wrapper

```tsx
import { Tailwind } from '@react-email/tailwind';
import { Html, Body, Container, Text, Button } from '@react-email/components';

export default function Email() {
  return (
    <Html>
      <Tailwind>
        {/* Tailwind classes work ONLY inside <Tailwind> wrapper */}
        <Body className="bg-gray-100">
          <Container className="max-w-[600px] mx-auto bg-white">
            <Text className="text-base text-gray-800 px-6 py-4">
              Your order has been confirmed.
            </Text>
            {/* NOTE: Do NOT use flex/grid classes — not email-safe */}
            <Button href="https://example.com/track"
                    className="bg-blue-600 text-white px-6 py-3 rounded font-bold">
              Track Order
            </Button>
          </Container>
        </Body>
      </Tailwind>
    </Html>
  );
}
```

## Support Matrix

| Feature | Outlook 2007–19 | Outlook new | Gmail webmail | Apple Mail | Yahoo Mail |
|---------|:---:|:---:|:---:|:---:|:---:|
| Inline `style` objects | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tailwind via `@react-email/tailwind` | Partial | ✅ | ✅ | ✅ | Partial |
| `<Container>` (table centering) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `<Button>` VML fallback | ✅* | N/A | N/A | N/A | N/A |
| `<Preview>` preheader | ✅ | ✅ | ✅ | ✅ | ✅ |
| `<Img>` display:block | ✅ | ✅ | ✅ | ✅ | ✅ |

\* Verify current React Email version generates VML — this has changed across releases.

## Known Afflictions

**React Email `<Button>` VML coverage varies by version** — Whether `<Button>` generates the VML bulletproof button pattern for Outlook 2007–2019 has changed across React Email releases. Always compile and inspect the output HTML for `<v:roundrect>` when targeting legacy Outlook. If absent, wrap with manual VML conditional comments.
Affects: All React Email versions; check per-release. Source: React Email GitHub — Button component.

**`@react-email/tailwind` does not restrict email-unsafe classes** — Tailwind classes for `flex`, `grid`, and CSS custom properties are valid Tailwind utilities but are not email-safe. `@react-email/tailwind` does not filter them out. Using `flex` for structural layout silently fails in Gmail app and Outlook Windows.
Affects: Teams using Tailwind with React Email. Source: caniemail.com.

**render() is synchronous — async components silently truncate** — `render()` does not await async component functions. A component that calls `await` inside its render function produces incomplete output (the async parts are silently omitted). Always use `renderAsync()` for async components. Source: React Email documentation.
Affects: All React Email versions.

## Sources

1. **React Email Documentation** — https://react.email/docs/introduction — Components, render API, preview server.
2. **React Email GitHub** — https://github.com/resend/react-email — Releases, component implementation.
3. **Resend API** — https://resend.com/docs/api-reference/emails/send-email — Email send integration.
4. **html-to-text** — https://www.npmjs.com/package/html-to-text — Plain text generation from HTML.
5. **caniemail.com** — https://www.caniemail.com — Email client CSS support data.
