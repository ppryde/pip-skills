# email-absolution Skills — Writing-Skills TDD Benchmark

**Date:** 2026-03-18
**Branch:** email-skills
**Method:** superpowers:writing-skills RED-GREEN-REFACTOR cycle
**Skills tested:** `elder`, `scribe` (visitation not directly tested — structurally identical to elder)
**Test prompt:** Password reset email (Klaviyo / Liquid / Outlook 2019 + Gmail + Apple Mail)
**Audit subject:** Deliberately flawed order confirmation template (17 known violations seeded)

---

## RED Phase — Baseline Behaviour (no skill)

### Scribe baseline

Two separate runs. Consistent failures across both:

| Category | Baseline behaviour |
|---|---|
| Preheader | ❌ Absent both times — clients showed first body text as preview |
| CSS padding | ❌ Shorthand everywhere (`padding: 40px 16px`, `padding: 48px 48px 40px`) |
| Default filters | ❌ Missing on `reset_url`, `expiry_hours`, `unsubscribe_url` — only strings guarded |
| Layout elements | ❌ `<div>` used for security notice, divider, button wrapper |
| Inline styles | ❌ Styles only in `<style>` block — not duplicated inline (Gmail strips `<style>`) |
| Klaviyo namespace | ❌ Generic `organization.*` variables — undefined in Klaviyo context |
| Assumptions declared | ❌ None |
| Variables table | ❌ None |
| Test checklist | ❌ None |
| VML button | ✅ Known pattern — both runs included it |
| `role="presentation"` | ✅ Applied on main tables |
| `lang="en"` | ✅ Present |

**Consistent failure pattern:** CSS shorthand and missing preheader were the two most reliable failures. Every baseline run missed them.

### Elder baseline

| Category | Baseline behaviour |
|---|---|
| Total findings | 16 issues |
| Severity vocabulary | Critical / Significant / Moderate / Low |
| Rule IDs | ❌ None |
| Witchfinder voice | ❌ Generic technical prose |
| Verdict format | ❌ Numbered list, no structured sections |
| Preheader | ❌ Classified as **Low priority** (#16 of 16) |
| Unsubscribe link | ❌ Missed entirely |
| Physical address | ❌ Missed entirely |
| Klaviyo namespace errors | ❌ Missed entirely |
| Default filters (all vars) | ❌ Only `item.price` flagged — 4 other output tags missed |
| `role="presentation"` | ❌ Missed |
| `display:none`/`mso-hide:all` | ❌ Misframed as "Gmail strips `<style>`" |
| `<p>` margin:0 | ❌ Missed |
| Whitespace control in loops | ❌ Missed |

**Biggest framing failure:** The preheader was the last item, marked low priority. The skill correctly reclassifies it as a mortal sin — this is the starkest signal of the skill's value.

---

## GREEN Phase — With-Skill Behaviour

### Scribe with skill

| Criterion | Result |
|---|---|
| Preheader | ✅ First element in `<body>`, with `&zwnj;` bleed prevention |
| CSS padding | ✅ Longhand throughout (`padding-top`, `padding-right`, etc.) |
| Default filters | ✅ All output tags: `\| default: '#' \| escape` on URLs, `\| default: 24` on integers |
| Layout | ✅ Table-based — no `<div>` for structural elements |
| Inline styles | ✅ All styles inlined; `<style>` block for reset only |
| Klaviyo namespace | ✅ `person.first_name`, `event.extra.reset_url`, `event.extra.expiry_hours` |
| Dark mode | ✅ Full `@media (prefers-color-scheme: dark)` with `[data-ogsc]` fallback |
| MSO ghost table | ✅ `<!--[if mso]>` wrapper around outer table |
| `mso-line-height-rule: exactly` | ✅ Applied on all text elements |
| Assumptions declared | ✅ 9 explicit assumptions before template |
| Variables table | ✅ With Klaviyo namespace, required/optional, fallback columns |
| Send path note | ✅ Klaviyo-specific instructions |
| Test checklist | ✅ 5 targeted checks including fallback previews |
| Post-generation Elder offer | ✅ Offered at end of output |

**Doctrines read (confirmed from tool trace):** rendering, html-css, accessibility, deliverability, gotchas, liquid — exactly the 6 specified for scribe (no content-ux, no tooling).

### Elder with skill

| Criterion | Result |
|---|---|
| Total findings | 37 (17 mortal + 14 venial + 6 counsel) |
| Severity vocabulary | ✅ Mortal sins / Venial sins / Counsel from the elders |
| Rule IDs | ✅ Every finding cited |
| Witchfinder voice | ✅ Throughout |
| Verdict format | ✅ Exact SKILL.md spec with priority ranking |
| Preheader | ✅ Correctly classified as **mortal sin** (UX-002) |
| Unsubscribe link | ✅ UX-016 mortal sin |
| Physical address | ✅ DELIV-012 venial sin |
| Klaviyo namespace | ✅ LIQ-012 mortal sin |
| Default filters | ✅ All 5 output tags flagged (LIQ-001) |
| `role="presentation"` | ✅ RENDER-007/ACCESS-003 mortal sin |
| `display:none`/`mso-hide:all` | ✅ HTML-003 correctly identified |
| Whitespace control in loops | ✅ LIQ-009 venial sin |
| `{% for %}` missing `{% else %}` | ✅ LIQ-002 venial sin |
| Prioritised verdict | ✅ Top 5 by audience impact with reasoning |
| "Found righteous" section | ✅ Present with partial credit noted |

**Doctrines read (confirmed from tool trace):** rendering, html-css, content-ux, accessibility, deliverability, gotchas, tooling, liquid — all 8 specified for elder. ✅

---

## Delta Summary

| Metric | Baseline | With skill | Delta |
|---|---|---|---|
| **Scribe** — preheader present | ❌ | ✅ | +1 critical fix |
| **Scribe** — CSS shorthand violations | ~8–12 | 0 | −8–12 |
| **Scribe** — missing default filters | 3–4 | 0 | −3–4 |
| **Scribe** — layout divs | 3 | 0 | −3 |
| **Scribe** — Klaviyo namespace correct | ❌ | ✅ | |
| **Elder** — total findings | 16 | 37 | +21 (+131%) |
| **Elder** — rule IDs cited | 0 | 37 | +37 |
| **Elder** — correct vocabulary | ❌ | ✅ | |
| **Elder** — preheader severity | Low | **Mortal** | |
| **Elder** — deliverability findings | 0 | 3 | +3 |

---

## REFACTOR — Changes made post-baseline

Identified from RED phase, applied before GREEN confirmation:

1. **`${CLAUDE_SKILL_DIR}` removed** — fictional shell variable replaced with natural language path description in both elder and scribe
2. **visitation cross-references updated** — `elder/SKILL.md` file-path style → `email-absolution:elder` skill-name style (3 instances)
3. **Scribe Common Mistakes strengthened:**
   - Preheader entry: clarified as first `<body>` element, explained consequence (client shows body text as preview)
   - Default filter entry: expanded from "every variable" to explicitly cover URLs and integers, not just strings
   - Added `box-shadow`/`border-radius` inline styles entry
   - Added CSS shorthand context (head `<style>` block vs inline element styles)
4. **Scribe Step 4 preheader bolded** — added bold emphasis with consequence explanation

Commit: `661729a refactor(email-absolution): harden skill files via writing-skills TDD pass`

---

## Notes for future iterations

- **Visitation not directly tested** — its workflow is identical to elder (same doctrine load, same output format, narrower scope). Red/green pattern will match elder.
- **Description optimization not run** — `run_loop.py` trigger accuracy optimization deferred. All three skill descriptions pass manual CSO review.
- **Template complexity** — the audit template had 17 seeded violations. A more complex template (two-column layout, dark mode, conditional sections) would exercise RENDER-012/013 and HTML-015/016 doctrine rules not covered here.
- **MJML/React Email stack not tested** — per-language doctrine loading confirmed correct for liquid. Other stacks untested.
