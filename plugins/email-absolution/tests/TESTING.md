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
    ├── level-1-obvious.liquid     ★☆☆☆☆  Klaviyo / Liquid
    ├── level-2-moderate.liquid    ★★☆☆☆  Klaviyo / Liquid
    ├── level-3-handlebars.hbs     ★★★☆☆  SendGrid / Handlebars
    ├── level-4-advanced.liquid    ★★★★☆  Klaviyo / Liquid
    └── level-5-gotchas.hbs        ★★★★★  SendGrid / Handlebars
```

Each template has a fixed set of deliberately planted violations documented in
`BENCHMARK.md`. The answer key is the source of truth — it specifies the expected
rule ID, severity, and location for every violation.

---

## Template Summaries

### level-1-obvious.liquid (★☆☆☆☆)
A stripped-back welcome email with the most common beginner mistakes. Missing
DOCTYPE, no `lang`, relative URLs, CSS `var()`, no `alt`, no unsubscribe, no
VML button. A passing skill should catch all 8 with no effort.

### level-2-moderate.liquid (★★☆☆☆)
A realistic order confirmation template with structural oversights. The preheader
is present but hidden via a CSS class (not inline styles), meaning it will show as
body text in Gmail. Other violations include `min-height` on a `<td>`, no VML
button, all Liquid variables unfiltered, wrong Klaviyo namespace, no
`role="presentation"`, and no physical address.

### level-3-handlebars.hbs (★★★☆☆)
A generic transactional email built with Handlebars and SendGrid. The structural
basics are mostly present but several violations require knowledge of
Handlebars-specific risks and email client behaviour: triple-stache XSS on
`{{{body_content}}}`, `border-collapse: collapse` on layout tables, missing VML,
`rgba()` on the CTA, and footer links styled only in the `<style>` block.

### level-4-advanced.liquid (★★★★☆)
A monthly summary email that looks professional but uses fundamentally broken
layout techniques. Two-column layout via CSS `float`, a hero band with inline
`background-image`, an `@font-face` web font, and `rgba()` with alpha on body
text. The VML and MSO setup are correctly present — violations are structural and
rendering-target specific.

### level-5-gotchas.hbs (★★★★★)
A near-production-quality email with subtle, easy-to-miss violations. The
preheader pattern is almost correct but is missing `mso-hide: all`. The data
table has `<th>` elements but no `scope`. The outer table has `cellpadding="16"`.
The inner data table is missing `mso-table-lspace/rspace`. Handlebars variables
have no fallback guards. None of these are visually obvious from the source.

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

Append `doc` to get a markdown report saved to `docs/emails/audits/`.

### Scoring a run

After running the skill against a template, score the output against `BENCHMARK.md`:

1. **Catch rate** — count planted violations found ÷ total planted × 100
2. **False positives** — count violations reported that are not in the answer key
3. **Rule ID accuracy** — for each caught violation, was the correct rule ID cited?
4. **Severity accuracy** — was mortal/venial/counsel assigned correctly?

Record results in the [Benchmark History](#benchmark-history) section below.

### Minimum passing thresholds

| Template level | Minimum catch rate | Max false positives |
|---------------|-------------------|---------------------|
| Level 1 | 100% | 3 |
| Level 2 | 90% | 3 |
| Level 3 | 85% | 4 |
| Level 4 | 75% | 4 |
| Level 5 | 65% | 5 |

---

## Benchmark History

One entry per plugin version. When changes are made to doctrines or skills,
run all five templates and record results here before merging. Compare against
the previous version to confirm no regressions.

---

### v1.0.0 — 2026-03-19

> Initial versioned release. 12 doctrines, 3 skills, doc output mode.
> Baseline scores pending — run the five templates and record below.

#### Per-template results

**level-1-obvious.liquid** — Planted: 8

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
| **False positives** | — | — | — | — |

Catch rate: —/8 (—%) &nbsp; False positives: —

---

**level-2-moderate.liquid** — Planted: 7

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Preheader hidden via CSS class (not inline) | ✅ | — | — | — |
| `min-height` on `<td>` | ✅ | — | — | — |
| No VML button | ✅ | — | — | — |
| All Liquid vars unfiltered | ✅ | — | — | — |
| Wrong Klaviyo namespace | ✅ | — | — | — |
| No `role="presentation"` | ✅ | — | — | — |
| No physical address | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/7 (—%) &nbsp; False positives: —

---

**level-3-handlebars.hbs** — Planted: 8

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
| **False positives** | — | — | — | — |

Catch rate: —/8 (—%) &nbsp; False positives: —

---

**level-4-advanced.liquid** — Planted: 7

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| `float` layout | ✅ | — | — | — |
| `@font-face` without safe fallback | ✅ | — | — | — |
| `background-image` in inline style | ✅ | — | — | — |
| `rgba()` with alpha on text | ✅ | — | — | — |
| `<div>` based two-column layout | ✅ | — | — | — |
| `line-height` without `mso-line-height-rule: exactly` on h1 | ✅ | — | — | — |
| `background-size` in inline style | ✅ | — | — | — |
| **False positives** | — | — | — | — |

Catch rate: —/7 (—%) &nbsp; False positives: —

---

**level-5-gotchas.hbs** — Planted: 8

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
| **False positives** | — | — | — | — |

Catch rate: —/8 (—%) &nbsp; False positives: —

---

#### v1.0.0 Summary

| Template | Planted | Caught | Catch rate | False positives | Meets threshold |
|----------|---------|--------|------------|-----------------|-----------------|
| level-1-obvious | 8 | — | —% | — | — |
| level-2-moderate | 7 | — | —% | — | — |
| level-3-handlebars | 8 | — | —% | — | — |
| level-4-advanced | 7 | — | —% | — | — |
| level-5-gotchas | 8 | — | —% | — | — |
| **Total** | **38** | **—** | **—%** | **—** | **—** |

---

## Adding a New Version Entry

When doctrines or skills are updated, add a new version block **above** the
previous one (newest first). Copy the v1.0.0 template, update the version and
date, and fill in results after running all five templates.

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
