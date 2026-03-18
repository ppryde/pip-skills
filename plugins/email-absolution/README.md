# email-absolution

HTML email development under the watchful eye of the Witchfinder.

Twelve doctrines. Three skills. No sinful templates shall pass.

## Skills

- **elder** — Consultation, planning, and routing. Your first port of call.
- **visitation** — Formal inspection of an existing email template against all doctrines.
- **scribe** — Righteous generation of new email templates, correct by construction.

## Usage

```
/email-absolution:elder          # Q&A, planning, config setup
/email-absolution:visitation     # Audit a template
/email-absolution:scribe         # Generate a template
```

## Configuration

On first invocation, `elder` will offer to create `.email-absolution/config.yml` via a setup questionnaire. Individual email templates may have their own `email.config.yml` in their directory. Per-email configs inherit from the project config and only need to specify overrides.

```yaml
# .email-absolution/config.yml (created by elder)
stack:
  esp: sendgrid
  templating: handlebars

template:
  structure: master-components

clients: all

brand:
  primary_colour: "#0066cc"
  font_stack: "Arial, Helvetica, sans-serif"
  max_width: 600

strictness:
  rendering: strict
  html-css: strict
  accessibility: pragmatic
  deliverability: strict
  gotchas: strict
  content-ux: pragmatic
  tooling: aspirational

email_defaults:
  type: transactional
  unsubscribe: false
  tone: transactional
```

## Doctrines

### Core (loaded by all skills)
- **rendering** — Client rendering rules, CSS support matrix, MSO workarounds
- **html-css** — Safe HTML/CSS patterns, table layouts, component examples
- **accessibility** — WCAG 2.1 AA, ARIA support, regulatory requirements
- **deliverability** — SPF/DKIM/DMARC, spam signals, unsubscribe compliance
- **gotchas** — Client bugs, edge cases, production traps
- **content-ux** — Subject lines, CTAs, structure, mobile UX *(elder/visitation only)*

### Tooling (loaded based on stack.templating config)
- **tooling** — Framework selection guide and cross-tool rules
- **mjml** — MJML-specific rules, v4/v5 differences, compiled output concerns
- **handlebars** — Handlebars vs Mustache, ESP syntax differences
- **liquid** — Liquid rules for Shopify/Klaviyo
- **react-email** — React Email components, Outlook limitations
- **maizzle** — Tailwind-based authoring, production build rules

## Persona

All skills speak with the Witchfinder voice. Heresy is found. Absolution is granted. The soul is either clean or it is not.

The Witchfinder persona is fixed at the plugin level and cannot be suppressed via config. The `tone` field in `email_defaults` refers to the email's tone of voice (e.g. `transactional`, `casual`) — not the skill's persona.

## Relationship to `puritan`

`email-absolution` is a sibling plugin. It shares the Witchfinder persona and doctrine/skill/config pattern. It does not share doctrine files, skill invocations, or configuration trees with `puritan`.
