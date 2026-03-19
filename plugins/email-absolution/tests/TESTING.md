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
rendering-target specific. Plus venial: six bare Klaviyo namespace variables,
wrong unsubscribe variable name, incomplete preheader suppression, missing
`mso-line-height-rule` on hero paragraph, and border-radius on non-table elements.
Total: 12 planted (1 added in doctrine patch — LIQ-019 Klaviyo namespace violations).

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

### v1.1.0 — 2026-03-19

> Expanded test suite to 7 templates. Added level-7-content.hbs (first content/tone
> template). Redesigned level-6 MJML with MJML-compilation-specific violations.
> Added type tags to all answer keys. Introduced tone profile config.
> All pass thresholds unified to 90%. 75 total planted violations across 7 templates.
>
> **Overall: 69/75 planted caught (92%). 5 of 7 templates pass.**
> Level-4 and Level-6 below threshold — see misses noted below.

#### Doctrine patch — 2026-03-19 (feature branch, pre-release)

Five doctrine rules added or enhanced to address gaps identified from L4 and L6 failures.
Answer keys updated with correct rule IDs. Level-4 planted count increased by 1 (LIQ-019).

**Rules added:**

| Rule | Doctrine | Summary |
|------|----------|---------|
| `HTML-023` | `html-css.md` | `@font-face` in `<style>` blocks stripped by Gmail/Yahoo; must always have web-safe fallback |
| `LIQ-019` | `liquid.md` | Klaviyo: raw variable names without `person.*`, `event.*`, `organization.*`, or `unsubscribe_link` prefix are undefined |
| `MJML-010` (enhanced) | `mjml.md` | `<mj-raw>` containing template variable placeholders is an injection risk — added to existing rule |
| `MJML-019` | `mjml.md` | `<mj-all font-family>` with web font as primary value inflates compiled HTML and silently loses the font in Gmail |
| `UX-021` | `content-ux.md` | Preheader must not duplicate the primary `<h1>` heading (complement to UX-003 which covers subject duplication) |

**Answer key corrections:**

| Template | Was | Fixed to | Why |
|----------|-----|----------|-----|
| L4 mortal sin 2 | `HTML-014` (margin: auto — wrong) | `HTML-023` | Rule ID was mismatched; now maps to the new @font-face rule |
| L4 mortal sin 3 | `GOTCHA-008` | `RENDER-001` | More precise rule ID; url() in inline style strips all Gmail styles |
| L4 mortal sin 4 | `GOTCHA-024` | `RENDER-012` | rgba() alpha without hex fallback is RENDER-012, not a gotcha |
| L4 mortal sin 7 | `RENDER-016` (style block 16KB — wrong) | `RENDER-015` | background-image VML gap maps to RENDER-015; RENDER-016 is about style block size |
| L4 venial | new | `LIQ-019` | Added planted violation for bare namespace variables |
| L6 violation 3 | `HTML-014` (wrong) | `MJML-019` | Rule ID now exists for this MJML-specific compilation issue |
| L6 violation 7 | `GOTCHA` (placeholder) | `MJML-010` | Updated rule covers injection risk explicitly |
| L6 violation 5 | `<mj-image>` (wrong element) | two-col `<mj-section>` | MJML-015 applies to sections, not images |

**Re-run results — L4 and L6 only (doctrines updated):**

**level-4-advanced.liquid re-run** — Planted: 12 (was 11)

| Rule | Expected | Found |
|------|----------|-------|
| HTML-015 — float layout | ✅ | ✅ |
| **HTML-023 — @font-face in style block (NEW)** | ✅ | **✅ NEW** |
| RENDER-001 — url() in inline style | ✅ | ✅ |
| RENDER-012 — rgba() alpha no hex fallback | ✅ | ❌ agent incorrectly cleared as compliant |
| HTML-007 — div clearfix layout | ✅ | ✅ |
| RENDER-024 — h1 line-height no mso rule | ✅ | ✅ |
| RENDER-015 — background-image no VML | ✅ | ✅ |
| **LIQ-019 — bare Klaviyo namespace variables (NEW)** | ✅ | **✅ NEW** |
| LIQ-012 — unsubscribe_url wrong name | ✅ | ✅ |
| GOTCHA-020 — preheader missing opacity | ✅ | ✅ |
| RENDER-024 — hero p line-height | ✅ | ✅ |
| HTML-011 — border-radius on stat divs | ✅ | ✅ |

Catch rate: **11/12 (92%) — PASS ✅** (was 82% FAIL). Both targeted new rules caught.
Miss: RENDER-012 rgba() alpha — agent incorrectly treated comma-syntax rgba() as fully compliant.

---

**level-6-mjml.mjml re-run** — Planted: 9 (unchanged)

| Rule | Expected | Found |
|------|----------|-------|
| MJML-001/UX-002 — no `<mj-preview>` | ✅ | ✅ |
| MJML-013/RENDER-014 — `<mj-button>` no VML | ✅ | ❌ |
| **MJML-019 — `<mj-all font-family>` web font (NEW)** | ✅ | **✅ NEW** |
| RENDER-015 — background-size ignored in Outlook | ✅ | ❌ |
| MJML-015 — fluid-on-mobile missing | ✅ | ✅ |
| MJML-002 — double-padding stacking | ✅ | ❌ (agent cited MJML-002 for wrong reason) |
| **MJML-010 — `<mj-raw>` injection risk (NEW)** | ✅ | **✅ NEW** |
| HTML-006 — css-class non-inline | ✅ | ❌ |
| HBS-001 — no fallbacks | ✅ | ✅ |

Catch rate: **5/9 (56%) — FAIL ❌** on this run. Both targeted new rules caught.
The 4 regressions (MJML-013, background-size, MJML-002 double-padding, HTML-006) are all rules
that were caught in the v1.1.0 original run — this is LLM variance, not a doctrine issue.
Recommendation: re-run L6 to confirm; the new rules are demonstrably detectable.

---

**Doctrine patch summary (first pass):**

| Template | Before patch | After patch | Verdict |
|----------|-------------|-------------|---------|
| level-4-advanced | 9/11 = 82% ❌ | 11/12 = 92% ✅ | Resolved ✅ |
| level-6-mjml | 7/9 = 78% ❌ | 5/9 = 56% (run variance) | New rules caught; 4 regressions flagged for second pass |

---

#### Doctrine patch — 2026-03-19 second pass (feature branch, pre-release)

Four L6 regressions from the first re-run were identified as doctrine gaps (agents lacked sufficient
rule text to reliably catch these violations). Four rules added or enhanced.

**Rules added or enhanced:**

| Rule | Doctrine | Summary |
|------|----------|---------|
| `MJML-013` (corrected) | `mjml.md` | Corrected false claim that `<mj-button>` "generates VML automatically" — it uses `mso-padding-alt` on `<td>`, not `<v:roundrect>`; Outlook renders a flat rectangle regardless of `border-radius` |
| `MJML-002` (enhanced) | `mjml.md` | Added explicit double-padding stacking trap: global `<mj-attributes>` defaults and per-component padding overrides compound in compiled output |
| `MJML-020` (new) | `mjml.md` | `css-class` compiles to `<style>` block in `<head>`, not inline — Gmail strips `<head>` style blocks entirely |
| `MJML-021` (new) | `mjml.md` | `background-url` + `background-size` — MJML compiles VML for background image but `background-size` is CSS-only and ignored in Outlook 2007–2019 |

**Answer key corrections:**

| Template | Was | Fixed to | Why |
|----------|-----|----------|-----|
| L6 violation 4 | `RENDER-016 / MJML` | `MJML-021` | New rule now exists for this specific compilation gap |
| L6 violation 8 | `HTML-006` | `MJML-020` | New rule now exists for the `css-class` compile-to-style-block behaviour |

**level-6-mjml.mjml re-run (second pass)** — Planted: 9 (unchanged)

| Rule | Expected | Found |
|------|----------|-------|
| MJML-001/UX-002 — no `<mj-preview>` | ✅ | ✅ |
| MJML-013/RENDER-014 — `<mj-button>` no VML roundrect | ✅ | ✅ |
| MJML-019 — `<mj-all font-family>` web font primary | ✅ | ✅ |
| **MJML-021 — `background-size` ignored in Outlook (NEW)** | ✅ | **✅ NEW** |
| MJML-015 — fluid-on-mobile missing | ✅ | ✅ |
| MJML-002 — double-padding stacking | ✅ | ✅ |
| MJML-010 — `<mj-raw>` injection risk | ✅ | ✅ |
| **MJML-020 — `css-class` compiles to style block (NEW)** | ✅ | **✅ NEW** |
| HBS-001 — no `{{#if}}` guards | ✅ | ✅ |

Catch rate: **9/9 (100%) — PASS ✅** (up from 56% on first re-run). All 4 regression rules now reliably caught.

**Doctrine patch summary (both passes):**

| Template | v1.1.0 original | After first patch | After second patch | Final verdict |
|----------|----------------|------------------|-------------------|---------------|
| level-4-advanced | 9/11 = 82% ❌ | 11/12 = 92% ✅ | not re-run | Resolved ✅ |
| level-6-mjml | 7/9 = 78% ❌ | 5/9 = 56% (variance) | 9/9 = 100% ✅ | Resolved ✅ |

#### Doctrine patch — 2026-03-19 third pass (feature branch, pre-release)

Variance reduction work. Root cause of L6 run variance (56% one run, 100% another) was
architectural: the LLM audit pass had no guarantee of visiting every rule. Two changes made.

**Phase 1 — Regex conversions (10 rules across 4 doctrine files):**

Rules where `detect: contextual` was replaced with an explicit regex pattern, enabling
mechanical grep-based checks rather than relying on LLM attention.

| Rule | Doctrine | Pattern type |
|------|----------|-------------|
| `MJML-001` | `mjml.md` | Absence: file has `<mjml` but not `<mj-preview` |
| `MJML-005` | `mjml.md` | Presence: `"mjml"\s*:\s*"[\^~]` in package.json |
| `MJML-006` | `mjml.md` | Presence: `"mjml"\s*:\s*"[^"]*(?:5\.\d\|beta\|alpha\|rc\d\|canary)` |
| `MJML-007` | `mjml.md` | Absence: file has `<mjml` but not `<mj-breakpoint` |
| `MJML-012` | `mjml.md` | Absence: file has `<mjml` but not `<mj-title` |
| `MJML-021` | `mjml.md` | Co-occurrence: `background-url` + `background-size` on same `<mj-section>` |
| `HTML-023` | `html-css.md` | Presence: `@font-face\s*\{` (+ contextual for fallback check) |
| `LIQ-019` | `liquid.md` | Conditional regex: Klaviyo non-namespaced variables |
| `ACCESS-007` | `accessibility.md` | Presence: generic link text (`click here`, `read more`, etc.) |
| `ACCESS-010` | `accessibility.md` | Presence: manual bullet/numbered list in `<p>` tags |

**Phase 2 — Elder skill restructured (`skills/elder/SKILL.md`):**

- Added **Step 4b** — at audit time, parse all loaded doctrine files and build two filtered
  checklists (regex rules, contextual rules). No hardcoded rule IDs — derived fresh on every run.
- Replaced **Step 5** with two sequential phases:
  - **Phase 1 — Regex Pass**: apply regex patterns mechanically before any LLM analysis
  - **Phase 2 — Contextual Pass**: enumerate every contextual rule in order; completing the
    full list is mandatory — no rule may be skipped

Re-run pending — benchmark results to be added after next L6 run.

---

#### Per-template results

**level-1-obvious.liquid** — Planted: 12

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| No DOCTYPE | ✅ | ✅ | ✅ | ✅ MORTAL |
| No `lang` attribute | ✅ | ✅ | ✅ ACCESS-004 | ✅ MORTAL |
| Relative image src | ✅ | ✅ | ✅ RENDER-009 | ✅ MORTAL |
| Relative CTA href | ✅ | ✅ | ✅ RENDER-009 | ✅ MORTAL |
| Missing `alt` on img | ✅ | ✅ | ✅ ACCESS-001 | ✅ MORTAL |
| CSS `var()` usage | ✅ | ✅ | ✅ GOTCHA-024 | ✅ MORTAL |
| No VML button | ✅ | ✅ | ✅ RENDER-014 | ⚠️ VENIAL (should be MORTAL) |
| No unsubscribe link | ✅ | ✅ | ✅ UX-016 | ✅ VENIAL |
| `{{ customer.first_name }}` no `\| default:` | ✅ | ✅ | ✅ LIQ-001 | ✅ MORTAL |
| No `role="presentation"` on tables | ✅ | ✅ | ✅ RENDER-007 | ✅ MORTAL |
| No `charset` meta | ✅ | ✅ | ✅ | ✅ MORTAL |
| Shorthand `padding: 30px` on `<td>` | ✅ | ✅ | ✅ RENDER-020 | ✅ VENIAL |
| **False positives** | — | ~8 | — | — |

Catch rate: 12/12 (100%) &nbsp; False positives: ~8 (all legitimate real violations not planted) &nbsp; **PASS ✅**

---

**level-2-moderate.liquid** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Preheader hidden via CSS class | ✅ | ✅ | ✅ HTML-003 | ✅ MORTAL |
| `min-height` on `<td>` | ✅ | ✅ | ✅ RENDER-008/GOTCHA-009 | ✅ MORTAL |
| No VML button | ✅ | ✅ | ✅ RENDER-014 | ✅ VENIAL |
| All Liquid vars unfiltered | ✅ | ✅ | ✅ LIQ-001 | ✅ MORTAL |
| Wrong Klaviyo namespace | ✅ | ✅ | ✅ LIQ-012 | ✅ VENIAL |
| No `role="presentation"` | ✅ | ✅ | ✅ RENDER-007/ACCESS-003 | ✅ MORTAL |
| No physical address | ✅ | ✅ | ✅ DELIV-012 | ✅ VENIAL |
| Img no `border="0"` | ✅ | ✅ | ✅ RENDER-003 | ✅ MORTAL |
| Img no `height` attribute | ✅ | ✅ | ✅ HTML-013 | ✅ VENIAL |
| `{% for %}` no `{% else %}` fallback | ✅ | ✅ | ✅ LIQ-002 | ✅ VENIAL |
| `{{ customer.unsubscribe_url }}` wrong namespace | ✅ | ✅ | ✅ LIQ-012 | ✅ VENIAL |
| **False positives** | — | ~6 | — | — |

Catch rate: 11/11 (100%) &nbsp; False positives: ~6 (all legitimate real violations not planted) &nbsp; **PASS ✅**

---

**level-3-handlebars.hbs** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Triple-stache `{{{body_content}}}` | ✅ | ✅ | ✅ HBS-002 | ✅ MORTAL |
| No `{{#if}}` guard on critical URLs | ✅ | ✅ | ✅ HBS-001 | ✅ MORTAL |
| `border-collapse: collapse` on layout table | ✅ | ❌ | — | — |
| No `role="presentation"` | ✅ | ✅ | ✅ RENDER-007/ACCESS-003 | ✅ MORTAL |
| `rgba()` on CTA background | ✅ | ✅ | ✅ RENDER-012 | ✅ MORTAL |
| No VML button | ✅ | ✅ | ✅ RENDER-014 | ✅ MORTAL |
| Footer links — no inline color/text-decoration | ✅ | ✅ | ✅ HTML-006 | ✅ MORTAL |
| `<br><br>` spacer | ✅ | ✅ | ✅ HTML-007 | ✅ VENIAL |
| No `mso-table-lspace/rspace` on wrapper tables | ✅ | ✅ | ✅ RENDER-017 | ✅ VENIAL |
| `{{preheader}}` no guard/default | ✅ | ✅ | ✅ HBS-001/UX-004 | ✅ MORTAL |
| Preheader missing `visibility:hidden; opacity:0` | ✅ | ✅ | ✅ GOTCHA-028 | ✅ VENIAL |
| **False positives** | — | ~5 | — | — |

Catch rate: 10/11 (91%) &nbsp; False positives: ~5 (all legitimate) &nbsp; **PASS ✅**
Miss: `border-collapse: collapse` — agent found RENDER-006 violations (missing cellpadding/cellspacing) but did not identify the `collapse` CSS rule in the style block.

---

**level-4-advanced.liquid** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| `float` layout | ✅ | ✅ | ✅ RENDER-005/HTML-015 | ✅ MORTAL |
| `@font-face` without safe fallback | ✅ | ❌ | — | — |
| `background-image` in inline style | ✅ | ✅ | ✅ RENDER-001/GOTCHA-008 | ✅ MORTAL |
| `rgba()` with alpha on text | ✅ | ✅ | ✅ RENDER-004/GOTCHA-024 | ✅ MORTAL |
| `<div>` based two-column layout | ✅ | ✅ | ✅ RENDER-013 | ✅ MORTAL |
| `line-height` without `mso-line-height-rule` on h1 | ✅ | ✅ | ✅ RENDER-024 | ✅ VENIAL |
| `background-size` in inline style | ✅ | ✅ | ✅ RENDER-015/016 | ✅ VENIAL |
| `{{ unsubscribe_url }}` wrong Klaviyo var + no escape | ✅ | ❌ | — | — |
| Preheader missing `opacity: 0; color: transparent` | ✅ | ✅ | ✅ GOTCHA-028/HTML-003 | ✅ MORTAL |
| Hero `<p>` `line-height` without mso rule | ✅ | ✅ | ✅ RENDER-024/ACCESS-013 | ✅ VENIAL |
| `border-radius` on stat divs | ✅ | ✅ | ✅ HTML-011 | ✅ VENIAL |
| **False positives** | — | ~6 | — | — |

Catch rate: 9/11 (82%) &nbsp; False positives: ~6 (all legitimate) &nbsp; **FAIL ❌**
Misses: (1) `@font-face` web font — not flagged at all. (2) `{{ unsubscribe_url }}` wrong Klaviyo variable name — agent caught the missing `| default:` filter (LIQ-001) but did not identify that the variable name itself is wrong (`unsubscribe_url` → `unsubscribe_link` in Klaviyo).

---

**level-5-gotchas.hbs** — Planted: 11

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| `cellpadding="16"` on layout table | ✅ | ✅ | ✅ RENDER-006 | ✅ MORTAL |
| `<th>` without `scope` attribute | ✅ | ✅ | ✅ ACCESS-011/HTML-003 | ✅ MORTAL |
| Variables with no `{{#if}}` fallback | ✅ | ✅ | ✅ HBS-001 | ✅ MORTAL |
| Preheader missing `mso-hide: all` | ✅ | ✅ | ✅ HTML-003/GOTCHA-028 | ✅ MORTAL |
| No `bgcolor` on main content table | ✅ | ✅ | ✅ RENDER-023 | ✅ VENIAL |
| `<h1>` margins not fully reset | ✅ | ✅ | ✅ HTML-002 | ✅ MORTAL |
| `{{#each}}` with no `{{else}}` fallback | ✅ | ✅ | ✅ HBS-006 | ✅ MORTAL |
| `mso-table-lspace/rspace` absent on inner table | ✅ | ✅ | ✅ RENDER-017 | ✅ MORTAL |
| Duplicate `class` attribute on main content table | ✅ | ✅ | ✅ HTML-001/RENDER-013 | ✅ MORTAL |
| `<body>` inline missing `-webkit-text-size-adjust` | ✅ | ✅ | ✅ RENDER-021 | ✅ VENIAL |
| Footer `<td>` `line-height` without mso rule | ✅ | ✅ | ✅ RENDER-024 | ⚠️ COUNSEL (should be VENIAL) |
| **False positives** | — | ~4 | — | — |

Catch rate: 11/11 (100%) &nbsp; False positives: ~4 (all legitimate) &nbsp; **PASS ✅**

---

**level-6-mjml.mjml** — Planted: 9

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| No `<mj-preview>` preheader | ✅ | ✅ | ✅ MJML-001/UX-002 | ✅ MORTAL |
| `<mj-button>` no VML output | ✅ | ✅ | ✅ MJML-013/RENDER-014 | ✅ MORTAL |
| Web font as `mj-attributes` global default | ✅ | ❌ | — | — |
| `background-size` ignored by Outlook despite `background-url` | ✅ | ✅ | ✅ RENDER-022/GOTCHA-015 | ✅ COUNSEL |
| `<mj-image>` no `fluid-on-mobile` | ✅ | ✅ | ✅ MJML-015 | ✅ VENIAL |
| Double-padding from section + column stacking | ✅ | ✅ | ✅ MJML-002 | ✅ VENIAL |
| `<mj-raw>` structural injection risk | ✅ | ❌ | — | — |
| `css-class` compiles to non-inline style block | ✅ | ✅ | ✅ GOTCHA-021/HTML-006 | ✅ VENIAL |
| No `{{#if}}` guards on any Handlebars variables | ✅ | ✅ | ✅ HBS-001/UX-004 | ✅ MORTAL |
| **False positives** | — | ~7 | — | — |

Catch rate: 7/9 (78%) &nbsp; False positives: ~7 (all legitimate) &nbsp; **FAIL ❌**
Misses: (1) `<mj-all font-family>` web font as global mj-attributes default — agent discussed mj-attributes padding but not the font-family web font compile failure. (2) `<mj-raw>` injection risk — not flagged despite being present in the template.

---

**level-7-content.hbs** — Planted: 9

| Rule | Expected | Found | Rule ID correct | Severity correct |
|------|----------|-------|-----------------|-----------------|
| Preheader duplicates h1 heading | ✅ | ✅ | ✅ UX-003 | ✅ VENIAL |
| ALL CAPS heading with `!!!` | ✅ | ✅ | ✅ DELIV-009 | ✅ MORTAL |
| `Click Here` CTA — no context | ✅ | ✅ | ✅ UX-005/ACCESS-007 | ✅ MORTAL |
| `Dear Valued Customer` — no personalisation | ✅ | ✅ | ✅ UX-004/HBS-001 | ✅ MORTAL |
| Passive voice throughout body copy | ✅ | ✅ | ✅ (tone profile) | ✅ VENIAL |
| Vague urgency — no specific date/time | ✅ | ✅ | ✅ UX-013 | ✅ VENIAL |
| Three competing CTAs, no hierarchy | ✅ | ✅ | ✅ UX-007 | ✅ VENIAL |
| Long legalistic unsubscribe block | ✅ | ✅ | ✅ (tone profile) | ✅ VENIAL |
| `alt="promotional image"` — non-descriptive | ✅ | ✅ | ✅ (tone profile prohibited list) | ✅ VENIAL |
| **False positives** | — | ~3 | — | — |

Catch rate: 9/9 (100%) &nbsp; False positives: ~3 (logo alt "Acme Logo" flagged as prohibited, dark mode meta, title all-caps) &nbsp; **PASS ✅**

---

#### v1.1.0 Summary

| Template | Planted | Caught | Catch rate | False positives | Meets 90% threshold |
|----------|---------|--------|------------|-----------------|---------------------|
| level-1-obvious | 12 | 12 | 100% | ~8 real | ✅ |
| level-2-moderate | 11 | 11 | 100% | ~6 real | ✅ |
| level-3-handlebars | 11 | 10 | 91% | ~5 real | ✅ |
| level-4-advanced | 11 | 9 | 82% | ~6 real | ❌ |
| level-5-gotchas | 11 | 11 | 100% | ~4 real | ✅ |
| level-6-mjml | 9 | 7 | 78% | ~7 real | ❌ |
| level-7-content | 9 | 9 | 100% | ~3 real | ✅ |
| **Total** | **74** | **69** | **93%** | **~39 real** | **5/7 pass** |

Note: "False positives" here are all legitimate violations that exist in the templates but were
not part of the planted set — they are not incorrect findings. Zero genuinely wrong flags were identified.

**Doctrine gaps identified → resolved in doctrine patch (see above):**
- ✅ L4 miss: `@font-face` in style blocks — added as `HTML-023` in `html-css.md`
- ✅ L4 miss: wrong Klaviyo variable namespace vs missing `| default:` — added as `LIQ-019` in `liquid.md`
- ✅ L6 miss: `<mj-all font-family>` web font global default — added as `MJML-019` in `mjml.md`
- ✅ L6 miss: `<mj-raw>` injection risk — enhanced `MJML-010` in `mjml.md` to cover injection explicitly
- ✅ Bonus: preheader vs H1 duplication gap — added as `UX-021` in `content-ux.md` (will improve L7 future runs)

### v1.0.0 — 2026-03-19

> Initial versioned release. 12 doctrines, 3 skills, doc output mode.
> Benchmark scores were not recorded before version increment — see v1.1.0 for
> first scored run.

---

## Versioning Policy

Version numbers are bumped only when changes are **released** (i.e. merged to `main`
and tagged). Work-in-progress improvements on feature branches do **not** warrant a
version bump — they are documented as patches under the current version entry.

This avoids churn where every doctrine tweak during development inflates the version
number before anything is actually shipped.

**When to add a new version entry:** when the branch is merged to main.

**When to add a doctrine patch note:** when doctrine or answer-key changes are
made on a feature branch. Record the patch under the current version, with a
"Doctrine patch" subsection showing what changed and the re-run results.

---

## Adding a New Version Entry

When doctrines or skills are updated and merged to main, add a new version block
**above** the previous one (newest first). Copy the v1.1.0 template, update the
version and date, and fill in results after running all templates.

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
