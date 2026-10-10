# Verdict layout: Visitation

Read when writing the verdict. The sample is illustrative: ids, files and counts come from the run. `audit.md §Verdict` adds the `Rules checked` footer and any warnings.

The Visitation report is scoped and concise:

```
Email Visitation — PR Review
=============================

Branch: feat/order-confirmation-redesign → main
Doctrines: rendering, html-css, content-ux, accessibility,
           deliverability, gotchas, tooling, liquid
Templates in scope: 2 changed, 1 added

MORTAL SINS — must be absolved before merge (3):
-------------------------------------------------
[RENDER-002] Image missing display: block
  File: src/emails/order-confirmation.liquid:45 (modified)
  Found: <img src="..." width="600" style="border: 0;">
  Requires: display: block in the image's inline style

[LIQ-001] Missing default filter on output variable
  File: src/emails/new-template.liquid:12 (added)
  Found: {{ customer.company }}
  Requires: {{ customer.company | default: "" }}

[ACCESS-003] Layout table missing role="presentation"
  File: src/emails/new-template.liquid:8 (added)
  Found: <table width="600" cellpadding="0" cellspacing="0" border="0">
  Requires: role="presentation" attribute added

VENIAL SINS — should be absolved (1):
--------------------------------------
[HTML-008] Inline style uses CSS shorthand padding
  File: src/emails/order-confirmation.liquid:52 (modified)
  Found: style="padding: 16px 24px"
  Requires: padding-top/right/bottom/left longhand on <td>

EXISTING DEBT (not introduced in this diff):
  src/emails/order-confirmation.liquid — 2 pre-existing venial sins
  (run /email-absolution:elder to see full list)

FOUND RIGHTEOUS in this diff:
  src/emails/shipping-notification.liquid (modified — clean)

VERDICT: The Visitation finds 3 mortal sins in this branch.
Absolve them before this branch earns its place in the sanctum.
```
