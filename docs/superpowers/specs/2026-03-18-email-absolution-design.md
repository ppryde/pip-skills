# email-absolution — Design Spec

**Date:** 2026-03-18
**Status:** Approved for implementation planning

---

## Overview

`email-absolution` is a Claude Code plugin for engineers building HTML email systems. It provides three skills backed by twelve doctrine files (six core + one tooling overview + five per-language), a two-tier configuration system, and the Witchfinder persona inherited from the `puritan` plugin.

**Plugin name:** `email-absolution`
**Skills:** `elder`, `visitation`, `scribe`
**Doctrines:** 7 (one per research domain)
**Config tiers:** project-level + per-email

---

## Repository Structure

```
plugins/email-absolution/
├── .claude-plugin/plugin.json
├── README.md
├── doctrines/
│   ├── _template.md           # Doctrine authoring template
│   ├── rendering.md           # Distilled from email_rendering_compatibility
│   ├── html-css.md            # Distilled from email_html_css_practices
│   ├── content-ux.md          # Distilled from email_content_copy_ux
│   ├── accessibility.md       # Distilled from email_accessibility_inclusivity
│   ├── deliverability.md      # Distilled from email_deliverability_technical_hygiene
│   ├── gotchas.md             # Distilled from email_gotchas_edge_cases
│   ├── tooling.md             # Framework selection guide and cross-tool rules
│   ├── mjml.md                # MJML-specific rules and gotchas
│   ├── handlebars.md          # Handlebars/Mustache rules and ESP syntax
│   ├── liquid.md              # Liquid rules for Shopify/Klaviyo
│   ├── react-email.md         # React Email rules and Outlook limitations
│   └── maizzle.md             # Maizzle/Tailwind rules and production config
└── skills/
    ├── elder/SKILL.md
    ├── visitation/SKILL.md
    └── scribe/SKILL.md

# In user projects:
.email-absolution/
└── config.yml                 # Project-level config (created by elder)

emails/
├── order-confirmation/
│   ├── email.config.yml       # Per-email config
│   ├── template.hbs
│   └── components/
│       ├── header.hbs
│       └── footer.hbs
├── password-reset/
│   ├── email.config.yml
│   └── template.hbs
```

### plugin.json

```json
{
  "name": "email-absolution",
  "version": "0.1.0",
  "description": "Righteous HTML email construction. Doctrines, visitation, and absolution for the transactional email sanctum.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["email", "html-email", "transactional", "accessibility", "deliverability", "rendering"]
}
```

---

## Doctrines

Each doctrine is a distilled reference file (300–400 lines) extracted from the corresponding research document in `docs/emails/research/`.

### Doctrine format

Email doctrines use a best-practice rule catalog format — numbered, severity-rated rules that visitation checks contextually. The difference from puritan doctrines is the checking mechanism: puritan uses automated code scanning (regex, AST analysis); email-absolution uses Claude's contextual judgment applied against the rules. The catalog structure is the same.

Each email doctrine follows this template:

```markdown
# [Doctrine Name] — Email Doctrine

## Purpose
One paragraph: what this doctrine covers and why it matters.

## Rule Catalog
Numbered rules with severity. Format:

**[PREFIX-NNN]** `[severity]` — Rule statement.
> Why it matters. Cite source.

Severity levels: `mortal` (must fix before ship) | `venial` (should fix, counsel given) | `counsel` (best practice, aspirational)

Each rule optionally includes a `detect` field specifying how visitation should check it:
- `regex` — deterministic pattern match; visitation runs the check mechanically
- `contextual` — requires judgment; visitation reasons about the template
- `hybrid` — regex catches obvious cases; contextual catches nuanced ones

Example:
**[RENDER-001]** `mortal` — Never use `url()` in inline style attributes.
> Gmail desktop strips the entire style attribute from any element containing a url() function. Source: caniemail.com/features/css-background-image/
> detect: `regex` — pattern: `style="[^"]*url\s*\(`

**[ACCESS-001]** `mortal` — All `<img>` elements must have an `alt` attribute.
> Screen readers announce the filename when alt is absent. Source: WCAG 2.1 SC 1.1.1.
> detect: `regex` — pattern: `<img(?![^>]*\balt=)[^>]*>`

**[GOTCHA-001]** `mortal` — Never use whitespace RGB/RGBA syntax.
> Gmail strips entire CSS rules using `rgb(r g b)` or `rgba(r g b / a)` syntax. Source: hteumeuleu/email-bugs #160.
> detect: `regex` — pattern: `rgba?\(\s*\d+\s+\d+\s+\d+`

**[CONTENT-001]** `venial` — Subject line should be 40–50 characters.
> Longer subjects are clipped on mobile. Source: Campaign Monitor.
> detect: `contextual` — judge subject line length and quality from email.config.yml

## Support Matrix (where applicable)
Tables of client support for specific features. Safe | Partial | Risky columns.

## Patterns & Code Examples
Concrete code showing correct implementation. Labelled CORRECT / INCORRECT.

## Known Afflictions (client-specific bugs)
Named client bugs with symptoms and fixes. Cite hteumeuleu/email-bugs issue numbers where available.

## Sources
Numbered list of authoritative sources with URLs.
```

### Doctrine table

**Core doctrines (always loaded):**

| Doctrine | Source document | Primary content |
|----------|----------------|-----------------|
| `rendering` | email_rendering_compatibility.md | Client rendering rules, CSS support matrix, MSO workarounds |
| `html-css` | email_html_css_practices.md | Safe HTML/CSS patterns, component examples |
| `content-ux` | email_content_copy_ux.md | Subject lines, CTAs, structure, mobile UX |
| `accessibility` | email_accessibility_inclusivity.md | WCAG, ARIA support, regulatory requirements |
| `deliverability` | email_deliverability_technical_hygiene.md | SPF/DKIM/DMARC, spam signals, unsubscribe |
| `gotchas` | email_gotchas_edge_cases.md | Client bugs, edge cases, production traps |

**Tooling doctrines (conditionally loaded):**

| Doctrine | Primary content |
|----------|----------------|
| `tooling` | Framework selection guide, comparison matrix, cross-tool rules, ESP variable syntax reference |
| `mjml` | MJML syntax, v4 vs v5 changes, compiled output concerns, MJML-specific gotchas |
| `handlebars` | Handlebars vs Mustache distinction, SendGrid/Postmark syntax, partials |
| `liquid` | Liquid syntax for Shopify/Klaviyo, filters, loops, conditional logic |
| `react-email` | React Email components, TypeScript usage, Outlook limitations, version history |
| `maizzle` | Tailwind-based authoring, production config, Maizzle-specific gotchas |

**Loading rule:** Skills load `tooling.md` (overview) plus the per-language doctrine matching `stack.templating` in config. If `stack.templating: plain-html` or config is absent, load `tooling.md` only.

### Doctrine loading per skill

| Skill | Core doctrines | Tooling doctrines |
|-------|---------------|-------------------|
| `elder` | All 6 | `tooling` + matching per-language |
| `visitation` | All 6 | `tooling` + matching per-language |
| `scribe` | rendering, html-css, accessibility, deliverability, gotchas | matching per-language only |

`scribe` omits `content-ux` (a planning concern addressed upstream by `elder`) and the `tooling` overview (selection guidance not needed during generation). It loads the per-language doctrine directly — the scribe must know the syntax and gotchas of the configured templating language to generate correct output.

---

## Skills

### Skill frontmatter

Each SKILL.md opens with YAML frontmatter driving auto-selection:

**elder:**
```yaml
---
name: elder
description: >
  Use for all HTML email questions, planning, template review routing, and template generation.
  Triggers on: "email question", "help with email", "elder", "review my email", "build me an email",
  "does X work in Y client", "email setup", "email config", "email absolution".
---
```

**visitation:**
```yaml
---
name: visitation
description: >
  Use to audit an existing HTML email template against all email doctrines.
  Triggers on: "audit this email", "check my template", "visitation", "review this template",
  "is this email correct", "check this email for issues".
---
```

**scribe:**
```yaml
---
name: scribe
description: >
  Use to generate a new HTML email template or component built to doctrine.
  Triggers on: "write an email", "generate a template", "scribe", "build a receipt email",
  "create an email template", "write me an order confirmation".
---
```

---

### `elder` — The Witchfinder General

**Invoked as:** `/email-absolution:elder`

**Responsibilities:**
- Check for `.email-absolution/config.yml` on first invocation; if absent, offer setup questionnaire
- Answer consultation questions directly from loaded doctrines
- Help the user plan email architecture and choose tools
- Route to `visitation` or `scribe` based on user intent (see routing below)

**Routing mechanism:**
The elder does not silently invoke other skills. It explicitly tells the user which skill to invoke next and why — preserving the user's awareness and control. For example:

> "This template requires a visitation. Invoke `/email-absolution:visitation` and present the template for judgment."

For generation requests, the elder completes any planning questions first (email type, required content, tone), then directs to scribe:

> "The covenant is set. Summon the scribe: `/email-absolution:scribe order-confirmation`."

**Decision logic:**

| User intent | Elder action |
|-------------|-------------|
| Question / consultation | Answer directly from doctrines |
| Template pasted | Direct user to invoke `visitation` |
| Template build requested | Ask planning questions, then direct user to invoke `scribe` |
| No config found | Offer setup questionnaire before anything else |

**Setup questionnaire covers (in order):**
1. ESP (sendgrid / mailchimp / postmark / mailgun / ses / sparkpost / other)
2. Templating language (handlebars / liquid / mjml / react-email / maizzle / plain-html)
3. Template structure (master-child / master-components / plain-html)
4. Target clients (all / specific subset)
5. Brand basics (primary colour, font stack, max width)
6. Strictness per doctrine (suggest sensible defaults, allow override)

---

### `visitation` — The Formal Inspection

**Invoked as:** `/email-absolution:visitation`
**Also invoked after:** elder routing

**Input — what visitation accepts:**

| Input | Behaviour |
|-------|-----------|
| Inline pasted HTML | Audits the pasted content directly |
| File path (e.g. `emails/order-confirmation/template.hbs`) | Reads and audits that file |
| Directory path (e.g. `emails/order-confirmation/`) | Audits all template files in that directory |
| No argument | Asks user to provide a template or path before proceeding |

**Responsibilities:**
- Load all 7 doctrines
- Load `.email-absolution/config.yml` (if absent, proceed with defaults and note the absence)
- Load `email.config.yml` for the specific template if path provided (if absent, note it and proceed)
- Systematically audit against each doctrine
- Issue a structured verdict respecting `strictness` config

**Strictness levels in email context:**

| Level | Meaning |
|-------|---------|
| `strict` | All violations are mortal sins — must be resolved before the template ships |
| `pragmatic` | Partial support or minor issues become venial sins — counsel given, not blocking |
| `aspirational` | All violations are venial sins — guidance only, none blocking |

**Output structure:**
```
The Verdict — [template name or "unnamed template"]
====================================================
Heresies found: N (M mortal, K venial)
Doctrines applied: rendering, html-css, accessibility, deliverability, gotchas, content-ux, tooling

Mortal sins (must be resolved):
  [RENDER-001] ...
  [GOTCHA-007] ...

Venial sins (counsel from the elders):
  [ACCESS-003] ...

Found righteous:
  Deliverability — SPF, DKIM, DMARC headers correctly configured
  ...

The soul is [clean | not yet clean].
```

---

### `scribe` — The Righteous Builder

**Invoked as:** `/email-absolution:scribe [email-name]`
**Also invoked after:** elder planning questionnaire

**Responsibilities:**
- Load rendering + html-css + accessibility + deliverability + gotchas doctrines
- Load `.email-absolution/config.yml` for project stack and brand
- If `emails/<name>/email.config.yml` exists, load it; if not, ask questions and create it
- Generate HTML correct by construction per the loaded doctrines and config
- Output follows the configured template structure and templating language

**Generated output always includes:**
- Table-based layout with ghost table columns
- VML fallbacks for Outlook 2007–2019
- Inlined critical styles
- Correct preheader hiding pattern (`display:none; visibility:hidden; opacity:0; mso-hide:all`)
- Accessible alt text, `role="presentation"` on layout tables, heading hierarchy
- List-Unsubscribe headers where `unsubscribe: true` in email config
- Templating language variables matching configured ESP syntax

---

## Configuration

### Tier 1 — Project config

**Path:** `.email-absolution/config.yml`
**Created by:** elder setup questionnaire, or manually

The project config serves two roles:
1. **Project-wide settings** — stack, brand, clients, strictness
2. **Default values for per-email configs** — any field that can appear in `email.config.yml` can also be set here as a project-wide default. Per-email configs only need to specify overrides. Skills resolve values by merging: per-email fields take precedence; absent fields fall back to project defaults; absent project defaults fall back to built-in skill defaults.

```yaml
stack:
  esp: sendgrid              # sendgrid | mailchimp | postmark | mailgun | ses | sparkpost | other
  templating: handlebars     # handlebars | liquid | mjml | react-email | maizzle | plain-html

template:
  structure: master-components  # master-child | master-components | plain-html

clients: all                 # all | [gmail, outlook-2019, outlook-365, apple-mail, ...]

brand:
  primary_colour: "#0066cc"
  font_stack: "Arial, Helvetica, sans-serif"
  max_width: 600

strictness:
  rendering: strict          # strict | pragmatic | aspirational
  html-css: strict
  accessibility: pragmatic
  deliverability: strict
  gotchas: strict
  content-ux: pragmatic
  tooling: aspirational    # Applies to tooling.md overview AND the per-language doctrine
  # Default for absent keys: pragmatic

# Per-email defaults (inherited by all email.config.yml files unless overridden)
email_defaults:
  type: transactional
  unsubscribe: false
  tracking:
    links: true
    pixels: false            # Apple MPP makes open pixels unreliable
    utm_medium: transactional
  from:
    name: "{{brand_name}}"
    address: "hello@{{domain}}"
  reply_to: "support@{{domain}}"
  tone: transactional        # formal | casual | friendly | transactional
```

### Tier 2 — Per-email config

**Path:** `emails/<name>/email.config.yml`
**Created by:** scribe on first generation, or manually

Per-email configs only need to specify values that differ from project defaults. All fields are optional if a project default exists.

```yaml
name: order-confirmation
# type, unsubscribe, tracking.pixels inherit from project email_defaults

subject: "Your order #{{order_id}} is confirmed"
preheader: "Arriving by {{delivery_date}}"

from:
  name: "{{brand_name}} Orders"  # overrides project default from name
  address: "orders@{{domain}}"   # overrides project default from address

tracking:
  utm_campaign: order-confirmation  # adds to inherited tracking defaults

# tone_override: null  — inherits project email_defaults.tone
# unsubscribe: false   — inherits project email_defaults.unsubscribe
```

**Merge precedence (highest to lowest):**
1. Per-email `email.config.yml` fields
2. Project `email_defaults` in `.email-absolution/config.yml`
3. Built-in skill defaults

Fields are additive — more will be added as the plugin matures.

---

## Error Handling

| Situation | Skill | Behaviour |
|-----------|-------|-----------|
| `.email-absolution/config.yml` not found when `visitation` invoked directly | visitation | Proceed with sensible defaults; note the absence at top of verdict |
| `.email-absolution/config.yml` not found when `scribe` invoked directly | scribe | Ask the 6 setup questions inline before generating; do not require the file to exist |
| `email.config.yml` not found when `visitation` runs against a file path | visitation | Proceed; note that per-email config was absent and some checks (e.g. unsubscribe requirement) were assumed |
| Doctrine file missing from plugin | Any | Warn that doctrine `<name>` could not be loaded; continue with available doctrines; do not fail silently |
| No argument provided to `visitation` | visitation | Ask user to provide a template, file path, or directory |
| No argument provided to `scribe` | scribe | Ask what type of email to generate before proceeding |

---

## Persona

All three skills speak with the Witchfinder voice, inherited from `puritan`.

### Vocabulary

| Neutral | Witchfinder |
|---------|-------------|
| Issue / violation | Heresy |
| Critical violation | Mortal sin |
| Minor issue | Venial sin |
| Passes audit | Found righteous |
| Fails audit | Found wanting |
| Fix / resolve | Absolution |
| Review / audit | Visitation |
| Generated template | The writ |
| Email client bug | Known affliction |
| Gotcha / trap | Snare of the deceiver |
| Recommendation | Counsel from the elders |
| Summary report | The verdict |
| Template is clean | The soul is clean |
| Doctrine file content | The scripture |

### Guardrail

The persona is flavour, not a barrier to technical clarity. Every verdict must be technically precise and actionable. The Witchfinder is dramatic, not obscure.

---

## Invocation Examples

```
/email-absolution:elder
→ Checks for config; if absent: "I have not seen your configuration, seeker. Let us remedy that..."

/email-absolution:elder does flex work in Gmail?
→ Answers directly from rendering + gotchas doctrines

/email-absolution:visitation emails/order-confirmation/template.hbs
→ Full audit of that file, structured verdict

/email-absolution:visitation [pasted HTML]
→ Audits inline content

/email-absolution:scribe order-confirmation
→ Reads project config, creates email.config.yml via questionnaire, generates template
```

---

## Relationship to `puritan`

`email-absolution` is a sibling plugin, not a child. It shares:
- The Witchfinder persona and vocabulary
- The doctrine/skill/config pattern
- The `strictness` config model

It does not share:
- Doctrine files (email doctrines are separate from architecture doctrines)
- Skill invocation (fully namespaced, no collision)
- The `.architecture/config.yml` (separate config tree)
- Doctrine format (email doctrines are reference material, not violation catalogs)

---

## Out of Scope (v1)

- CI/CD integration (pre-push hooks) — defer to v2
- Automated rendering screenshot testing — out of scope for a skills plugin
- ESP API integration (send test emails) — out of scope
- Per-email strictness overrides — defer to v2
