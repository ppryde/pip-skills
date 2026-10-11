# Verdict layout: report mode

Read when writing the terminal verdict. The sample is illustrative: ids, files and counts come from the run. `audit.md §Verdict` adds the `Rules checked` footer and any warnings.

```
Email Inquisition — Full Audit Report
======================================

Doctrines applied: rendering, html-css, content-ux, accessibility,
                   deliverability, gotchas, tooling, liquid
Templates examined: 8
Stack: Klaviyo / Liquid / Outlook 2019 + Gmail + Apple Mail

MORTAL SINS — must be absolved before send (4):
------------------------------------------------
[LIQ-001] Missing default filter
  File: src/emails/order-confirmation.liquid:14
  Found: {{ first_name }}
  Requires: {{ first_name | default: "Valued Customer" }}

[RENDER-014] Bulletproof button absent
  File: src/emails/welcome.liquid:67
  Found: <a href="..."> styled as button — no VML fallback
  Requires: VML conditional comment wrapping for Outlook 2007–2019

[DELIV-002] DKIM record not confirmed
  Config: stack.esp = klaviyo
  Found: No DKIM domain record in config or documentation
  Requires: DKIM configured on sending domain before deployment

[ACCESS-003] Missing role="presentation" on layout table
  File: src/emails/order-confirmation.liquid:28
  Found: <table width="600"> with no role attribute
  Requires: role="presentation" on all layout tables

VENIAL SINS — should be absolved (5):
--------------------------------------
[ACCESS-012] Body text below minimum size
  File: src/emails/welcome.liquid:41
  Found: font-size: 12px on body copy
  Requires: Body text at least 14px (16px preferred)

[TOOL-008] ESP-native templates create vendor lock-in
  Found: Klaviyo-native templates with no documented trade-off
  Requires: Document the lock-in trade-off explicitly (e.g. in an architecture decision record)

... (3 more venial sins)

COUNSEL FROM THE ELDERS — advisory (1):
-----------------------------------------
[LIQ-016] cycle tag not used for alternating rows
  File: src/emails/order-confirmation.liquid:100
  Advisory: Use {% cycle "#f4f4f4", "#ffffff" %} for alternating row colours

FOUND RIGHTEOUS (2 templates):
  src/emails/shipping-notification.liquid
  src/emails/password-reset.liquid

VERDICT: The sanctum is not clean. Absolve 4 mortal sins before sending.
```
