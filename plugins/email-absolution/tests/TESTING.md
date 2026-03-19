# email-absolution — Testing Guide

This document covers the benchmark test suite structure, how to run tests, and
the historic record of skill performance across plugin versions.

---

## Directory Structure

```
plugins/email-absolution/tests/
├── TESTING.md             ← this file
├── BENCHMARK.md           ← answer key (planted violations + expected rule IDs)
└── templates/
    ├── level-1-obvious.liquid     ★☆☆☆☆☆☆  Klaviyo / Liquid         structural basics
    ├── level-2-moderate.liquid    ★★☆☆☆☆☆  Klaviyo / Liquid         structural + Liquid
    ├── level-3-handlebars.hbs     ★★★☆☆☆☆  SendGrid / Handlebars    structural + Handlebars
    ├── level-4-advanced.liquid    ★★★★☆☆☆  Klaviyo / Liquid         advanced rendering
    ├── level-5-gotchas.hbs        ★★★★★☆☆  SendGrid / Handlebars    subtle structural
    ├── level-6-mjml.mjml          ★★★★★★☆  SendGrid / MJML          MJML compilation
    └── level-7-content.hbs        ★★★★★★★  SendGrid / Handlebars    content, tone, UX copy
```

Each template has a fixed set of deliberately planted violations documented in
`BENCHMARK.md`. The answer key is the source of truth — it specifies the expected
rule ID, severity, and location for every violation.

---

## Template Summaries

### level-1-obvious.liquid (★☆☆☆☆☆)
A stripped-back welcome email with the most common beginner mistakes. Missing
DOCTYPE, no `lang`, relative URLs, CSS `var()`, no `alt`, no unsubscribe, no
VML button, unfiltered Liquid variable, no `role="presentation"`, missing
`charset` meta, and shorthand `padding` on a `<td>`. A passing skill should
catch all 12 with no effort.

### level-2-moderate.liquid (★★☆☆☆☆)
A realistic order confirmation template with structural oversights. The preheader
is present but hidden via a CSS class (not inline styles), meaning it will show as
body text in Gmail. Other violations include `min-height` on a `<td>`, no VML
button, all Liquid variables unfiltered, wrong Klaviyo namespace, no
`role="presentation"`, no physical address, missing `border="0"` on image,
no `height` on image, no `{% else %}` fallback on loop, and wrong unsubscribe
variable namespace. Total: 11 planted.

### level-3-handlebars.hbs (★★★☆☆☆)
A generic transactional email built with Handlebars and SendGrid. The structural
basics are mostly present but several violations require knowledge of
Handlebars-specific risks and email client behaviour: triple-stache XSS on
`{{{body_content}}}`, `border-collapse: collapse` on layout tables, missing VML,
`rgba()` on the CTA, and footer links styled only in the `<style>` block. Plus
venial: `<br><br>` spacer, missing `mso-table-lspace/rspace`, unguarded preheader
variable, and incomplete preheader suppression pattern. Total: 12 planted.

### level-4-advanced.liquid (★★★★☆☆)
A monthly summary email that looks professional but uses fundamentally broken
layout techniques. Two-column layout via CSS `float`, a hero band with inline
`background-image`, an `@font-face` web font, and `rgba()` with alpha on body
text. The VML and MSO setup are correctly present — violations are structural and
rendering-target specific. Plus venial: wrong unsubscribe variable, incomplete
preheader suppression, missing `mso-line-height-rule` on hero paragraph, and
border-radius on non-table elements. Total: 11 planted.

### level-5-gotchas.hbs (★★★★★☆)
A near-production-quality email with subtle, easy-to-miss violations. The
preheader pattern is almost correct but is missing `mso-hide: all`. The data
table has `<th>` elements but no `scope`. The outer table has `cellpadding="16"`.
The inner data table is missing `mso-table-lspace/rspace`. Handlebars variables
have no fallback guards. The main content table has a duplicate `class` attribute
that silently overrides the responsive breakpoint class. The `<body>` inline style
is missing `-webkit-text-size-adjust`. The footer line-height has no MSO rule.
None of these are visually obvious from the source. Total: 11 planted.

### level-6-mjml.mjml (★★★★★★☆)
A professional MJML template with violations that are entirely MJML-specific —
they require knowledge of how MJML compiles and where its abstractions hide bugs.
No `<mj-preview>`, `<mj-button>` without VML output, web font as global
`<mj-attributes>` default, `background-size` ignored by Outlook despite
`background-url`, `<mj-image>` without `fluid-on-mobile`, double-padding from
stacked section+column defaults, `<mj-raw>` structural injection, `css-class`
compiling to non-inline `<style>` block, and unguarded Handlebars variables.
Total: 9 planted.

### level-7-content.hbs (★★★★★★★)
A structurally correct promotional email with deliberate content, tone, and UX
copy violations. The HTML and CSS are clean — violations require the skill to
evaluate copy quality, CTA strength, personalisation, tone of voice, and UX
writing patterns. Tests: preheader duplicates heading, ALL CAPS heading with
excessive punctuation, "Click Here" CTA, "Dear Valued Customer" opening (no
personalisation despite available variable), passive-voice body copy, vague
urgency copy, three competing CTAs with no hierarchy, hostile multi-sentence
unsubscribe block, and non-descriptive image alt text.
Total: 9 planted.

---

## How to Run Tests

### Manual run (recommended for detailed analysis)

Invoke the elder skill against each template individually. Provide the stack
config inline since the test templates have no accompanying `config.yml`:

```
/email-absolution:elder plugins/email-absolution/tests/templates/level-1-obvious.liquid doc
```

With stack config:
```yaml
stack:
  esp: klaviyo
  templating: liquid
  rendering_targets:
    - outlook-2019
    - gmail
    - apple-mail
```

For Handlebars templates:
```yaml
stack:
  esp: sendgrid
  templating: handlebars
  rendering_targets:
    - outlook-2019
    - gmail
    - apple-mail
```

For MJML template:
```yaml
stack:
  esp: sendgrid
  templating: mjml
  rendering_targets:
    - outlook-2019
    - gmail
    - apple-mail
```

For the content/tone template (same stack as level-3):
```yaml
stack:
  esp: sendgrid
  templating: handlebars
  rendering_targets:
    - outlook-2019
    - gmail
    - apple-mail
```

Append `doc` to get a markdown report saved to `docs/emails/audits/`.

### Scoring a run

After running the skill against a template, score the output against `BENCHMARK.md`:

1. **Catch rate** — count planted violations found ÷ total planted × 100
2. **False positives** — count violations reported that are not in the answer key
3. **Rule ID accuracy** — for each caught violation, was the correct rule ID cited?
4. **Severity accuracy** — was mortal/venial/counsel assigned correctly?

Record results in the [Benchmark History](#benchmark-history) section below.

### Minimum passing thresholds

All templates require a minimum 90% catch rate. Level 7 (content/tone) has a
higher false-positive tolerance because content judgements involve interpretation.

| Template level | Minimum catch rate | Max false positives |
|---------------|-------------------|---------------------|
| Level 1 | 90% | 3 |
| Level 2 | 90% | 3 |
| Level 3 | 90% | 4 |
| Level 4 | 90% | 4 |
| Level 5 | 90% | 4 |
| Level 6 | 90% | 4 |
| Level 7 | 90% | 6 |

---

## Benchmark History

One entry per plugin version. When changes are made to doctrines or skills,
run all six templates and record results here before merging. Compare against
the previous version to confirm no regressions.

---

### v1.2.0 — 2026-03-19

> Added level-7-content.hbs — first template focused on copy quality, tone of
> voice, and UX writing rather than rendering or structure. Redesigned level-6
> MJML template with violations specific to MJML compilation behaviour (removed
> generic HTML violations; added mj-button VML gap, fluid-on-mobile, double-padding,
> mj-raw injection, mj-attributes web font, background-size compile gap).
> All pass thresholds unified to 90%. Total planted: 76 across 7 templates.
> Baseline scores pending — run all seven templates and record below.

#### Per-template results

**level-1-obvious.liquid** — Planted: 12

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| No DOCTYPE | ✅ | — | — | — |
| No `lang` attribute | ✅ | — | — | — |
| Relative image src | ✅ | — | — | — |
| Relative CTA href | ✅ | — | — | — |
| Missing `alt` on img | ✅ | — | — | — |
| CSS `var()` usage | ✅ | — | — | — |
| No VML button | ✅ | — | — | — |
| No unsubscribe link | ✅ | — | — | — |
| `{{ customer.first_name }}` no `\| default:` | ✅ | — | — | — |
| No `role="presentation"` on tables | ✅ | — | — | — |
| No `charset` meta | ✅ | — | — | — |
| Shorthand `padding: 30px` on `<td>` | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/12 (—%) &nbsp; False positives: —

---

**level-2-moderate.liquid** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Preheader hidden via CSS class | ✅ | — | — | — |
| `min-height` on `<td>` | ✅ | — | — | — |
| No VML button | ✅ | — | — | — |
| All Liquid vars unfiltered | ✅ | — | — | — |
| Wrong Klaviyo namespace | ✅ | — | — | — |
| No `role="presentation"` | ✅ | — | — | — |
| No physical address | ✅ | — | — | — |
| Img no `border="0"` | ✅ | — | — | — |
| Img no `height` attribute | ✅ | — | — | — |
| `{% for %}` no `{% else %}` fallback | ✅ | — | — | — |
| `{{ customer.unsubscribe_url }}` wrong namespace | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/11 (—%) &nbsp; False positives: —

---

**level-3-handlebars.hbs** — Planted: 12

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Triple-stache `{{{body_content}}}` | ✅ | — | — | — |
| No `{{#if}}` guard on critical URLs | ✅ | — | — | — |
| `border-collapse: collapse` on layout table | ✅ | — | — | — |
| No `role="presentation"` | ✅ | — | — | — |
| `rgba()` on CTA background | ✅ | — | — | — |
| No VML button | ✅ | — | — | — |
| Footer links — no inline color/text-decoration | ✅ | — | — | — |
| `<br><br>` spacer | ✅ | — | — | — |
| No `mso-table-lspace/rspace` on wrapper tables | ✅ | — | — | — |
| `{{preheader}}` no guard/default | ✅ | — | — | — |
| Preheader missing `visibility:hidden; opacity:0` | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/11 (—%) &nbsp; False positives: —

---

**level-4-advanced.liquid** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| `float` layout | ✅ | — | — | — |
| `@font-face` without safe fallback | ✅ | — | — | — |
| `background-image` in inline style | ✅ | — | — | — |
| `rgba()` with alpha on text | ✅ | — | — | — |
| `<div>` based two-column layout | ✅ | — | — | — |
| `line-height` without `mso-line-height-rule` on h1 | ✅ | — | — | — |
| `background-size` in inline style | ✅ | — | — | — |
| `{{ unsubscribe_url }}` wrong Klaviyo var + no escape | ✅ | — | — | — |
| Preheader missing `opacity: 0; color: transparent` | ✅ | — | — | — |
| Hero `<p>` `line-height` without mso rule | ✅ | — | — | — |
| `border-radius` on stat divs | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/11 (—%) &nbsp; False positives: —

---

**level-5-gotchas.hbs** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| `cellpadding="16"` on layout table | ✅ | — | — | — |
| `<th>` without `scope` attribute | ✅ | — | — | — |
| Variables with no `{{#if}}` fallback | ✅ | — | — | — |
| Preheader missing `mso-hide: all` | ✅ | — | — | — |
| No `bgcolor` on main content table | ✅ | — | — | — |
| `<h1>` margins not fully reset | ✅ | — | — | — |
| `{{#each}}` with no `{{else}}` fallback | ✅ | — | — | — |
| `mso-table-lspace/rspace` absent on inner table | ✅ | — | — | — |
| Duplicate `class` attribute on main content table | ✅ | — | — | — |
| `<body>` inline missing `-webkit-text-size-adjust` | ✅ | — | — | — |
| Footer `<td>` `line-height` without mso rule | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/11 (—%) &nbsp; False positives: —

---

**level-6-mjml.mjml** — Planted: 9

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| No `<mj-preview>` preheader | ✅ | — | — | — |
| `<mj-button>` no VML output | ✅ | — | — | — |
| Web font as `mj-attributes` global default | ✅ | — | — | — |
| `background-size` ignored by Outlook despite `background-url` | ✅ | — | — | — |
| `<mj-image>` no `fluid-on-mobile` | ✅ | — | — | — |
| Double-padding from section + column stacking | ✅ | — | — | — |
| `<mj-raw>` structural injection risk | ✅ | — | — | — |
| `css-class` compiles to non-inline style block | ✅ | — | — | — |
| No `{{#if}}` guards on any Handlebars variables | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/9 (—%) &nbsp; False positives: —

---

**level-7-content.hbs** — Planted: 9

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Preheader duplicates h1 heading | ✅ | — | — | — |
| ALL CAPS heading with `!!!` | ✅ | — | — | — |
| `Click Here` CTA — no context | ✅ | — | — | — |
| `Dear Valued Customer` — no personalisation | ✅ | — | — | — |
| Passive voice throughout body copy | ✅ | — | — | — |
| Vague urgency — no specific date/time | ✅ | — | — | — |
| Three competing CTAs, no hierarchy | ✅ | — | — | — |
| Long legalistic unsubscribe block | ✅ | — | — | — |
| `alt="promotional image"` — non-descriptive | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/9 (—%) &nbsp; False positives: —

---

#### v1.2.0 Summary

| Template | Planted | Caught | Catch rate | False positives | Meets threshold |
|----------|---------|--------|------------|-----------------|-----------------||
| level-1-obvious | 12 | — | —% | — | — |
| level-2-moderate | 11 | — | —% | — | — |
| level-3-handlebars | 12 | — | —% | — | — |
| level-4-advanced | 11 | — | —% | — | — |
| level-5-gotchas | 11 | — | —% | — | — |
| level-6-mjml | 9 | — | —% | — | — |
| level-7-content | 9 | — | —% | — | — |
| **Total** | **75** | **—** | **—%** | **—** | **—** |

---

### v1.1.0 — 2026-03-19

> Expanded test suite to 6 templates. Added 3–4 additional violations per
> template (total planted: 67 across 6 templates, up from 38 across 5).
> Added MJML level-6 template. Revised pass thresholds upward.
> Baseline scores not recorded before version increment — see v1.2.0 for
> first scored run.

### v1.0.0 — 2026-03-19

> Initial versioned release. 12 doctrines, 3 skills, doc output mode.
> Benchmark scores were not recorded before version increment — see v1.1.0 for
> first scored run.

---

## Adding a New Version Entry

When doctrines or skills are updated, add a new version block **above** the
previous one (newest first). Copy the v1.1.0 template, update the version and
date, and fill in results after running all six templates.

```markdown
### vX.Y.Z — YYYY-MM-DD

> Summary of what changed in this version.

#### Per-template results
...

#### vX.Y.Z Summary
...
```

Keep all previous version entries intact below the new one. This provides a
complete historic record and makes regressions immediately visible.
