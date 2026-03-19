# Liquid — Email Doctrine

## Purpose

Rules and gotchas for engineers building transactional email templates with Liquid — Shopify's open-source templating language (Ruby gem: `liquid`; JavaScript port: `liquidjs`). Covers Klaviyo's Liquid implementation, self-hosted LiquidJS pipelines, and the safety properties that make Liquid well-suited to email rendering. Liquid has no filesystem access and cannot execute arbitrary code — it is the safest option for rendering user-influenced templates.

## Rule Catalog

---

**[LIQ-001]** `mortal` — All output variables must use the `default` filter. `{{ first_name }}` renders as empty string when nil.
> Without a default, a missing or nil variable silently produces "Hi ," in the email body. The `default` filter covers both `nil` values and absent keys. Source: Liquid Reference — Filters.
> `detect: regex` — pattern: `\{\{[\s]*[a-zA-Z_][a-zA-Z0-9_.]*[\s]*\}\}` (output tag with no filter pipe)

**[LIQ-002]** `mortal` — Use `{% for %}...{% else %}` to handle empty arrays. The `{% else %}` block renders when the array is nil or empty.
> A `{% for %}` loop with no `{% else %}` leaves recipients with missing order rows, blank sections, or broken table structure when the array is empty. Always provide a fallback row or message.
> `detect: contextual` — check `{% for %}` loops for `{% else %}` fallback blocks

**[LIQ-003]** `mortal` — Use the `escape` filter on user-generated content rendered in HTML attribute positions.
> `<a href="{{ url }}">` is safe only when `url` is a trusted, validated URL. User-controlled `url` values may contain `"` characters that break the attribute, or `javascript:` protocol values. Use `{{ url | escape }}` for string attribute values containing UGC. Source: Liquid Reference — escape filter.
> `detect: contextual` — check if user-input variables in HTML attribute positions use `escape`

**[LIQ-004]** `mortal` — Use `strip_html` before rendering user-generated content into email body text.
> User-provided product names, addresses, and notes may contain HTML tags. In email, unexpected tags break layout and can inject unwanted styles. `{{ product.name | strip_html }}` removes all tags before rendering. Source: Liquid Reference — strip_html filter.
> `detect: contextual` — check if known user-generated content fields pass through `strip_html`

**[LIQ-005]** `mortal` — Never use `{% raw %}` to inject large HTML blocks from user input. It bypasses all filtering.
> `{% raw %}` outputs its content completely unprocessed. A `{% raw %}{{ user.bio }}{% endraw %}` where `user.bio` is user-controlled is an injection risk. `{% raw %}` is for displaying literal Liquid syntax in documentation or code examples only.
> `detect: contextual` — flag `{% raw %}` blocks that contain dynamic variables or user-controlled content

**[LIQ-006]** `venial` — Use the `money` filter (Shopify/Klaviyo) or a registered `money` filter for currency values.
> `${{ price }}` outputs `$9.9` for a `9.90` float. Shopify and Klaviyo provide a `money` filter: `{{ price | money }}` → `$9.90`. For self-hosted LiquidJS, register a custom money filter using `Intl.NumberFormat`. Source: Shopify Liquid Reference — money filter.
> `detect: contextual` — check monetary variables for `money` filter or equivalent

**[LIQ-007]** `venial` — Use the `date` filter with an explicit format string for all date values.
> Raw ISO 8601 strings (`2026-03-18T14:00:00Z`) are unacceptable in email copy. `{{ delivery_date | date: "%B %-d, %Y" }}` → "March 18, 2026". Use `%-d` (not `%d`) to suppress zero-padding on the day in Ruby Liquid. Source: Liquid Reference — date filter.
> `detect: contextual` — check date variables for `date:` filter with format string

**[LIQ-008]** `venial` — Use `{% assign %}` for computed values rather than long inline filter chains.
> A filter chain longer than 3 filters is hard to read and debug: `{{ order.total | times: 1.2 | round: 2 | money }}`. Assign the intermediate result: `{% assign total_with_tax = order.total | times: 1.2 | round: 2 %}` then `{{ total_with_tax | money }}`.
> `detect: contextual` — check output tags for chains of more than 3 filters

**[LIQ-009]** `venial` — Use whitespace control `{%-` and `-%}` on logic tags inside table structures.
> In Outlook Windows (Word engine), whitespace text nodes between `<tr>` elements cause layout gaps. `{% for item in items %}` on its own line emits a newline into the compiled output. Use `{%- for item in items -%}` to strip surrounding whitespace in table contexts. Source: Liquid Reference — whitespace control.
> `detect: contextual` — check `{% for %}`, `{% if %}`, `{% endif %}`, `{% endfor %}` inside `<table>` / `<tr>` structures for whitespace control modifiers

**[LIQ-010]** `venial` — Use `forloop.first` and `forloop.last` for row separators and conditional borders — they are available in all Liquid implementations.
> `{% if forloop.first %}` and `{% if forloop.last %}` are standard Liquid loop variables. They are more readable than `{% if forloop.index == 1 %}` and work consistently across Ruby Liquid, LiquidJS, and Klaviyo.
> `detect: contextual` — advisory; prefer `forloop.first`/`forloop.last` over index comparisons

**[LIQ-011]** `venial` — In LiquidJS (Node.js), configure `strictVariables: false` in production to prevent rendering errors from incomplete recipient data.
> `strictVariables: true` throws when a variable is referenced but not in context. For email, where recipient profile data may be incomplete (missing fields for new users), strict mode causes send failures rather than graceful fallbacks. Use `default` filters defensively and allow `strictVariables: false`. Source: LiquidJS Configuration documentation.
> `detect: contextual` — check LiquidJS Environment configuration for `strictVariables` setting

**[LIQ-012]** `venial` — In Klaviyo, use `{{ person.first_name }}` for profile properties and `{{ event.extra.property }}` for event properties.
> Klaviyo's Liquid context exposes two namespaced objects: `person` (profile properties) and `event` (event payload). Raw `{{ first_name }}` is undefined in Klaviyo's context. Source: Klaviyo Developer Docs — Liquid Overview.
> `detect: contextual` — if `stack.esp` is "klaviyo", check that variables use `person.` or `event.extra.` accessors

**[LIQ-013]** `venial` — Use `| truncate: 90, ""` without trailing ellipsis when building preheader text.
> The default `truncate` appends `"..."` — `{{ preheader | truncate: 90 }}` produces `"..."`-terminated text in the inbox preview. `| truncate: 90, ""` truncates cleanly. Source: Liquid Reference — truncate filter.
> `detect: contextual` — check if `truncate` filter on preheader values uses the empty-suffix variant

**[LIQ-014]** `venial` — Prefer `{% render %}` over `{% include %}` for shared partials in Shopify Liquid 5+.
> `{% include %}` is deprecated in Shopify Liquid 5+. `{% render %}` has strict scope isolation (the rendered partial cannot access the parent template's variables unless explicitly passed). Klaviyo does not support either — use `{% capture %}` for component-like patterns instead.
> `detect: contextual` — check if Shopify Liquid 5+ templates use deprecated `{% include %}`

**[LIQ-015]** `counsel` — Use `{% capture %}` blocks to build complex strings before rendering, rather than constructing them inline.
> `{% capture full_name %}{{ first_name }} {{ last_name }}{% endcapture %}` makes the constructed string available as `{{ full_name }}` without repeating the construction logic.
> `detect: contextual` — advisory

**[LIQ-016]** `counsel` — The `cycle` tag generates alternating values across loop iterations — use it for alternating row background colours.
> `{% cycle "#f4f4f4", "#ffffff" %}` outputs the values in rotation with each call. Cleaner than `{% if forloop.index | modulo: 2 == 0 %}` comparisons.
> `detect: contextual` — advisory

**[LIQ-017]** `counsel` — Use `{% comment %}` for template documentation. Comment content is stripped from the rendered output.
> `{% comment %}This loop handles empty orders — see DELIV-007{% endcomment %}` documents intent without affecting email output or size.
> `detect: contextual` — advisory

**[LIQ-018]** `mortal` — Test Liquid templates with explicitly `nil` values for all optional variables — not just with missing keys.
> In Liquid, `nil` and a missing key produce identical output (empty string, `default` filter fires). However, in Klaviyo, `nil` vs absent profile property may have different send-path semantics. Test both: `{ first_name: nil }` and `{}` with no `first_name` key.
> `detect: contextual` — advisory; ensure test fixtures include both nil values and absent keys

**[LIQ-019]** `venial` — In Klaviyo, do not use raw variable names without an approved namespace prefix.
> Klaviyo's Liquid context exposes only four top-level namespaces: `person` (profile properties), `event` (event payload — dynamic content accessed via `event.extra.*`), `organization` (account-level properties), and `unsubscribe_link`. Variable names like `{{ first_name }}`, `{{ email }}`, `{{ order_id }}`, `{{ customer.name }}`, or `{{ stats.revenue }}` are ALL undefined in Klaviyo and silently render as empty string. `{{ first_name }}` is correct in plain LiquidJS; `{{ customer.* }}` is correct in Shopify — neither works in Klaviyo. Source: Klaviyo Developer Docs — Liquid Overview.
> `detect: contextual` — if `stack.esp` is "klaviyo", flag any `{{ variable }}` output tag whose root name is not `person`, `event`, `organization`, or `unsubscribe_link`

---

## Patterns & Code Examples

### Complete order loop with filters and empty fallback

```liquid
{% if order.items.size > 0 %}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <thead>
    <tr>
      <th style="text-align: left; padding: 8px; font-family: Arial, sans-serif; font-size: 13px; font-weight: bold;">Item</th>
      <th style="text-align: right; padding: 8px; font-family: Arial, sans-serif; font-size: 13px; font-weight: bold;">Qty</th>
      <th style="text-align: right; padding: 8px; font-family: Arial, sans-serif; font-size: 13px; font-weight: bold;">Price</th>
    </tr>
  </thead>
  <tbody>
    {%- for item in order.items -%}
    <tr style="background-color: {% cycle '#ffffff', '#f9f9f9' %};">
      <td style="padding: 8px; font-family: Arial, sans-serif; font-size: 14px;">{{ item.name | strip_html | default: "Unknown item" }}</td>
      <td style="text-align: right; padding: 8px; font-family: Arial, sans-serif;">{{ item.quantity | default: 1 }}</td>
      <td style="text-align: right; padding: 8px; font-family: Arial, sans-serif;">{{ item.unit_price | money }}</td>
    </tr>
    {%- endfor -%}
    <tr>
      <td colspan="2" style="text-align: right; padding: 8px; font-family: Arial, sans-serif; font-weight: bold;">Total</td>
      <td style="text-align: right; padding: 8px; font-family: Arial, sans-serif; font-weight: bold;">{{ order.total | money }}</td>
    </tr>
  </tbody>
</table>
{% else %}
<p style="font-family: Arial, sans-serif; font-size: 14px; color: #666666;">
  No items found for this order. Please contact
  <a href="mailto:support@acme.com" style="color: #0066cc;">support@acme.com</a>.
</p>
{% endif %}
```

### Klaviyo property accessors

```liquid
{# Klaviyo: person (profile) and event properties #}
Hi {{ person.first_name | default: "Valued Customer" | capitalize }},

Your order {{ event.extra.order_id | default: "" }} has shipped.

{# Delivery date from event payload #}
{% if event.extra.delivery_date %}
Estimated delivery: {{ event.extra.delivery_date | date: "%B %-d, %Y" }}
{% endif %}

{# VIP segment-specific content #}
{% if person.properties.vip_tier == "gold" %}
<p>As a Gold member, your order is being expedited.</p>
{% endif %}

{{ organization.name }}
<a href="{{ unsubscribe_link }}">Unsubscribe</a>
```

### Whitespace control in table row context

```liquid
{# Without whitespace control: newlines between <tr> tags cause gaps in Outlook #}
<tbody>
  {% for item in items %}
  <tr>...</tr>
  {% endfor %}
</tbody>

{# With whitespace control: no newlines between table rows #}
<tbody>
  {%- for item in items -%}
  <tr>...</tr>
  {%- endfor -%}
</tbody>
```

### LiquidJS Node.js configuration

```javascript
const { Liquid } = require('liquidjs');

const engine = new Liquid({
  // Do not throw on undefined variables — use default filters defensively
  strictVariables: false,
  // Do not throw on unknown filters — use only registered filters
  strictFilters: true,
  // Trim whitespace around block tags
  trimTagRight: true,
  trimTagLeft: true,
});

// Register custom money filter
engine.registerFilter('money', (amount, currency = 'GBP', locale = 'en-GB') => {
  if (amount == null || isNaN(amount)) return '—';
  return new Intl.NumberFormat(locale, {
    style: 'currency', currency, minimumFractionDigits: 2
  }).format(amount);
});

const html = await engine.renderFile('order-confirmation.liquid', {
  first_name: user.firstName,
  order: order,
});
```

## Support Matrix

| Feature | Ruby Liquid | LiquidJS | Klaviyo Liquid | Shopify Liquid |
|---------|:---:|:---:|:---:|:---:|
| `{{ variable }}` | ✅ | ✅ | ✅ | ✅ |
| `default` filter | ✅ | ✅ | ✅ | ✅ |
| `{% for %}...{% else %}` | ✅ | ✅ | ✅ | ✅ |
| `forloop.first/last` | ✅ | ✅ | ✅ | ✅ |
| `{% render %}` | ✅ | ✅ | ❌ | ✅ (v5+) |
| `{% include %}` | ✅ | ✅ | ❌ | Deprecated |
| `money` filter | ❌ (register) | ❌ (register) | ✅ | ✅ |
| `person.` namespace | ❌ | ❌ | ✅ | ❌ |
| `event.extra.` namespace | ❌ | ❌ | ✅ | ❌ |
| Custom filters | ✅ | ✅ | ❌ | ❌ |
| Whitespace control `{%-` | ✅ | ✅ | ✅ | ✅ |

### forloop.first / forloop.last row separator pattern

```liquid
{# Use forloop.last to avoid a bottom border on the final row #}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  {%- for item in order.items -%}
  <tr style="border-bottom: {% unless forloop.last %}1px solid #e5e5e5{% else %}none{% endunless %};">
    <td style="padding: 12px 8px; font-family: Arial, sans-serif; font-size: 14px;">
      {{ item.name | default: "Item" | strip_html }}
    </td>
    <td style="padding: 12px 8px; text-align: right; font-family: Arial, sans-serif;">
      {{ item.unit_price | money }}
    </td>
  </tr>
  {%- endfor -%}
  <tr>
    <td style="padding: 12px 8px; font-family: Arial, sans-serif; font-weight: bold;">
      Total
    </td>
    <td style="padding: 12px 8px; text-align: right; font-family: Arial, sans-serif; font-weight: bold;">
      {{ order.total | money }}
    </td>
  </tr>
</table>
```

### assign and capture for computed values

```liquid
{# Build full name and greeting before rendering #}
{% assign full_name = first_name | append: " " | append: last_name | strip %}
{% assign greeting = "Hi " | append: full_name | default: "Hi Valued Customer" %}

{# Build a multi-part text block #}
{% capture order_summary %}
Order #{{ order.id }} — {{ order.items.size }} item{% if order.items.size != 1 %}s{% endif %} — {{ order.total | money }}
{% endcapture %}

<p style="font-family: Arial, sans-serif; font-size: 14px;">{{ greeting }},</p>
<p style="font-family: Arial, sans-serif; font-size: 14px;">{{ order_summary | strip }}</p>
```

## Known Afflictions

**Klaviyo `money` filter locale** — Klaviyo's built-in `money` filter formats currency based on the account's default locale, not the recipient's locale. If the account is set to USD but a recipient is in the EU, `{{ price | money }}` outputs `$24.99` rather than `€24.99`. Use conditional blocks to handle multi-currency outputs explicitly.
Affects: Klaviyo. Source: Klaviyo Liquid documentation.

**LiquidJS `trim` vs Ruby Liquid whitespace control** — LiquidJS supports `{%-` and `-%}` whitespace control, but the `trimTagRight` / `trimTagLeft` configuration options trim *all* block tags globally. Using global trimming can remove intentional whitespace in non-table contexts. Prefer explicit `{%-` and `-%}` markers over global trimming.
Affects: LiquidJS. Source: LiquidJS configuration documentation.

**`strip_html` does not sanitise CSS** — `{{ body | strip_html }}` removes HTML tags but not `style=` attributes or CSS class names embedded in the content before tag removal. User-controlled content that uses inline styles before `strip_html` will have the tags removed but the style attribute text may survive as plain text fragments. Use a proper HTML sanitiser library for user-generated HTML.
Affects: All Liquid implementations. Source: Liquid Reference — strip_html.

## Sources

1. **Liquid Reference** — https://shopify.github.io/liquid/ — Filters, tags, iteration, whitespace control.
2. **LiquidJS Documentation** — https://liquidjs.com/tutorials/options.html — Configuration, custom filters, strictVariables.
3. **Klaviyo Developer Docs** — https://developers.klaviyo.com/en/docs/liquid-overview — Person/event namespaces, available filters.
4. **Shopify Liquid 5 Migration** — https://shopify.dev/docs/api/liquid — render vs include deprecation.
