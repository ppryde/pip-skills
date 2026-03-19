# HTML Email Research – Claude Code Subagents Setup

## Overview

Lightweight subagent setup for researching robust HTML email practices using 6 specialized subagents. Optimized for low token usage.

- One main Claude Code session orchestrates 6 **subagents**. Only 2 should run in parallel at a time to avoid loss of data due to context exhaustion
- Each writes to a **distinct Markdown file** under `docs/emails/research`
- **No tool use** – pure research and documentation
- Frequent progress updates prevent context loss

---

## Main Orchestrator Prompt

```
You are orchestrating 6 parallel subagents researching HTML email best practices.

Your job:
- Spawn all 6 subagents simultaneously with their system prompts below
- Let them work independently and write to their assigned docs/emails/research files
- Monitor progress via file updates (don't micromanage)
- When all 6 docs have "COMPLETE" markers, create synthesis: docs/emails/research/ALL_EMAIL_RESEARCH_SUMMARY.md

---

SUBAGENT 1: Rendering & Client Compatibility
File: docs/emails/research/email_rendering_compatibility.md

You research HTML email rendering across clients, emphasizing transactional emails that MUST work in very old clients.

**Research:**
- Major clients & rendering engines (Outlook desktop, Gmail, Apple Mail, etc)
- CSS/HTML support levels (safe/partial/risky) especially legacy clients
- Workarounds ensuring transactional content remains readable everywhere

**Rules:**
- Cite 1+ sources per factual claim
- Write progress after each major section
- Label sections clearly for incremental appends
- End with "COMPLETE" when done

**Output structure:**
## Client Landscape
## Feature Support Matrix
## Transactional Guarantees & Workarounds
## Sources
## TODOs

---

SUBAGENT 2: HTML/CSS Coding Practices
File: docs/emails/research/email_html_css_practices.md

You research general HTML/CSS patterns for reliable email templates.

**Research:**
- Recommended HTML structures (tables vs divs)
- Safe CSS properties and inline styling patterns
- Common components (buttons, headers, grids)
- Tradeoffs modern vs reliable approaches

**Rules:** Cite sources, write frequent progress, end with "COMPLETE"

**Output structure:**
## Core Principles
## Recommended Patterns
## Component Examples
## Sources
## TODOs

---

SUBAGENT 3: Content, Copy & UX
File: docs/emails/research/email_content_copy_ux.md

You research email content patterns improving opens/clicks/reads.

**Research:**
- Subject lines & preheaders that perform
- Body structure, scannability, CTA patterns
- Mobile UX and readability guidelines
- Transactional vs marketing differences

**Rules:** Cite sources, write frequent progress, end with "COMPLETE"

**Output structure:**
## Subject/Preheader Patterns
## Body Structure & UX
## Content Checklist
## Sources
## TODOs

---

SUBAGENT 4: Accessibility & Inclusivity
File: docs/emails/research/email_accessibility_inclusivity.md

You research email accessibility including WCAG/EAA compliance.

**Research:**
- Semantic HTML, contrast, alt text requirements
- Typography and interaction patterns
- WCAG alignment and regional regulations
- Transactional email accessibility priorities

**Rules:** Cite sources, write frequent progress, end with "COMPLETE"

**Output structure:**
## Accessibility Checklist
## Code Patterns
## Regulatory Context
## Sources
## TODOs

---

SUBAGENT 5: Deliverability & Technical Hygiene
File: docs/emails/research/email_deliverability_technical_hygiene.md

You research technical factors affecting inbox placement/rendering.

**Research:**
- HTML patterns triggering spam filters
- MIME structure, text:HTML balance
- Link/image checks, unsubscribe requirements
- Transactional deliverability nuances

**Rules:** Cite sources, write frequent progress, end with "COMPLETE"

**Output structure:**
## Deliverability Principles
## Pre-send QA Checklist
## Transactional Notes
## Sources
## TODOs

---

SUBAGENT 6: Email Templating Languages
File: docs/emails/research/email_templating_languages_frameworks.md

You research templating languages/frameworks for dynamic emails.

**Research:**
- Handlebars, Liquid, MJML, ESP syntaxes
- Integration patterns with sending platforms
- Dynamic content (loops, conditionals, variables)
- Compiled output reliability

**Rules:** Cite sources, write frequent progress, end with "COMPLETE"

**Output structure:**
## Templating Tools Overview
## Syntax Examples
## Workflow Patterns
## Sources
## TODOs

---

Rules:
- Subagents write frequently to avoid context loss
- Never interrupt their research flow
- Only combine final outputs, don't rewrite their work
```

---

## Expected File Structure
docs/emails/research/
├── email_rendering_compatibility.md              [COMPLETE]
├── email_html_css_practices.md                   [COMPLETE]
├── email_content_copy_ux.md                      [COMPLETE]
├── email_accessibility_inclusivity.md            [COMPLETE]
├── email_deliverability_technical_hygiene.md     [COMPLETE]
├── email_templating_languages_frameworks.md      [COMPLETE]
└── ALL_EMAIL_RESEARCH_SUMMARY.md                 [synthesized]
---

## Token Efficiency

✅ **Parallel execution** – 6 subagents work simultaneously
✅ **Incremental writes** – progress preserved across context windows
✅ **No inter-agent chatter** – independent research domains
✅ **Fixed outputs** – no coordination overhead
✅ **No tools** – pure research/documentation
