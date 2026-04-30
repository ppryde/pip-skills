# Deliverability — Email Doctrine

## Purpose

Guards against sending infrastructure failures, authentication gaps, and content patterns that route transactional email to spam or cause outright rejection. Since February 2024, Google and Yahoo enforce mandatory SPF+DKIM+DMARC and one-click unsubscribe requirements for bulk senders — these are no longer best-practice recommendations. A technically correct HTML template that fails deliverability checks never reaches the inbox.

## Rule Catalog

---

**[DELIV-001]** `transactional: mortal | marketing: mortal` — SPF must be published for the sending domain.
> SPF (RFC 7208) allows receiving MTAs to verify that the sending IP is authorised to send on behalf of your domain. Missing SPF causes messages to fail authentication checks. Google and Yahoo (2024) require valid SPF alignment for all senders. Source: [RFC 7208](https://datatracker.ietf.org/doc/html/rfc7208); [Google Sender Guidelines 2024](https://support.google.com/mail/answer/81126).
> `detect: contextual` — check that `stack.esp` config implies SPF is configured; flag as requiring infrastructure verification

**[DELIV-002]** `transactional: mortal | marketing: mortal` — DKIM must be configured with a minimum 2048-bit RSA key, signing at least the `from`, `to`, `subject`, `date`, and `message-id` headers.
> DKIM (RFC 6376) provides cryptographic proof that the message was authorised by the signing domain. RSA-1024 keys are deprecated and rejected by Gmail. The `h=` header list must include `from` for DMARC alignment. Google and Yahoo (2024) require passing DKIM alignment. Source: [RFC 6376](https://datatracker.ietf.org/doc/html/rfc6376); Google Sender Guidelines 2024.
> `detect: contextual` — check stack.esp config implies DKIM is configured; flag key size and signed headers as requiring infrastructure verification

**[DELIV-003]** `transactional: mortal | marketing: mortal` — DMARC must be published at minimum `p=none` with a valid `rua=` reporting address.
> DMARC (RFC 7489) ties SPF and DKIM together and requires identifier alignment — the authenticated domain must match the RFC5322 `From:` domain. Google and Yahoo (2024) require DMARC published for bulk senders. `p=none` is the minimum; progression to `p=quarantine` then `p=reject` is required for full protection. Source: [RFC 7489](https://datatracker.ietf.org/doc/html/rfc7489); Google Sender Guidelines 2024.
> `detect: contextual` — infrastructure verification required; flag absence of DMARC intent in project config

**[DELIV-004]** `transactional: mortal | marketing: mortal` — All image URLs must use HTTPS. HTTP image URLs are blocked by default in most modern clients and reduce trust scores.
> HTTP image URLs trigger security warnings in Gmail, iOS Mail, and Outlook. Many corporate security proxies block HTTP content entirely. Serving images over HTTP also reduces the sender's technical hygiene score with spam filters. Source: Campaign Monitor; Litmus Email Design Guide.
> `detect: regex` — pattern: `(?:src|href)=["']http://`

**[DELIV-005]** `transactional: mortal | marketing: mortal` — Total HTML must remain under 102 KB (102,400 bytes).
> Gmail clips email HTML at exactly 102 KB. Content beyond this limit is hidden behind a "[Message clipped] View entire message" link. Transactional content (order details, CTAs) placed after the clip is effectively invisible to users who don't click through. Source: [caniemail.com/features/html-style](https://www.caniemail.com/features/html-style/).
> `detect: contextual` — estimate compiled HTML size; flag templates approaching or exceeding the limit

**[DELIV-006]** `transactional: mortal | marketing: mortal` — MIME structure must be `multipart/alternative` with `text/plain` before `text/html`.
> RFC 2046 requires `text/plain` to appear before `text/html` in `multipart/alternative` (parts listed in increasing order of preference; the last supported part renders). Inverting this causes plain-text-only clients to display raw HTML source. Missing plain-text parts raise spam scores on Barracuda and Proofpoint filters. Source: [RFC 2046 §5.1.4](https://datatracker.ietf.org/doc/html/rfc2046#section-5.1.4).
> `detect: contextual` — check email.config.yml for MIME structure configuration or flag for manual verification

**[DELIV-007]** `transactional: mortal | marketing: mortal` — Plain-text version must be a complete, coherent prose rendering — not a stub.
> Stub plain-text bodies ("Please view the HTML version") raise spam scores and fail CAN-SPAM's requirement that required content (physical address, opt-out) be present and readable in plain text. Some corporate mail gateways default to plain text entirely. Source: CAN-SPAM Act (15 U.S.C. §7704); Postmark "Plain-Text Emails".
> `detect: contextual` — check if email.config.yml or template tooling generates a genuine plain-text version

**[DELIV-008]** `transactional: mortal | marketing: mortal` — Do not use consumer URL shorteners (bit.ly, tinyurl, t.co) in email links.
> Consumer shortener domains accumulate spam reputation and are permanently blocklisted in SURBL and URIBL. The obscured destination is itself a spam signal. If a shortener service has an outage, all links in sent messages break. Use a dedicated tracking subdomain instead (`click.example.com/c/[token]`). Source: [Postmark: URL Shorteners and Deliverability](https://postmarkapp.com/blog/url-shorteners-hurt-email-deliverability).
> `detect: regex` — pattern: `href=["']https?://(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly)/`

**[DELIV-009]** `transactional: mortal | marketing: mortal` — Do not use ALL-CAPS words in subject lines or excessive capitalisation in body text.
> SpamAssassin's `UPPERCASE_25_50` and higher rules fire when 25–75%+ of body words are capitalised. ALL-CAPS subject lines are one of the oldest and most reliable spam signals. Source: [Apache SpamAssassin HTML rules](https://spamassassin.apache.org/full/3.4.x/doc/Mail_SpamAssassin_Plugin_HTMLEval.html).
> `detect: contextual` — check subject field in email.config.yml and primary body text for excessive capitalisation

**[DELIV-010]** `transactional: mortal | marketing: mortal` — Marketing-style spam trigger words must not appear in transactional email subject lines.
> Phrases like "Act now", "Limited time offer", "Free gift", "You have been selected", and financial urgency language raise composite spam scores. Transactional emails should use purely functional, transactional language. Source: HubSpot "Spam Trigger Words"; Mailchimp "Spam Filters".
> `detect: contextual` — check subject line in email.config.yml for promotional/urgency language

**[DELIV-011]** `transactional: venial | marketing: venial` — List-Unsubscribe and List-Unsubscribe-Post headers must be present for subscribed/marketing mail sent at ≥ 5,000 messages/day to Gmail or Yahoo.
> Google and Yahoo (2024) require one-click unsubscribe (RFC 8058) for bulk senders. The `List-Unsubscribe-Post: List-Unsubscribe=One-Click` header enables Gmail's UI "Unsubscribe" button. The HTTPS endpoint must accept POST requests without redirects, remove the subscriber within 2 days, and not require session state or cookies. Source: [RFC 8058](https://www.rfc-editor.org/rfc/rfc8058); Google Sender Guidelines 2024.
> `detect: contextual` — check email.config.yml `unsubscribe: true` flag; if marketing email, verify header is configured in ESP settings

**[DELIV-012]** `transactional: venial | marketing: venial` — Physical mailing address must appear in the email footer.
> CAN-SPAM (US) requires a physical postal address in every commercial email. CASL (Canada) requires sender identification. This applies to transactional emails that contain any promotional content. Purely transactional messages (order confirmation, password reset) are exempt under CAN-SPAM's transactional exception (§7702(17)) but including the address is best practice regardless. Source: CAN-SPAM Act (15 U.S.C. §7704).
> `detect: contextual` — check if footer section contains a physical address

**[DELIV-013]** `transactional: venial | marketing: venial` — Do not use raw IP addresses as link destinations.
> Links using raw IP addresses (e.g., `http://192.0.2.1/track`) are a strong spam signal and are scored by SpamAssassin URI rules. All tracking and redirect links must use proper domain names. Source: SpamAssassin URI rules; Postmark "Why Emails Go to Spam".
> `detect: regex` — pattern: `href=["']https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}`

**[DELIV-014]** `transactional: venial | marketing: venial` — Images must not have invisible or hidden `alt` text to evade spam filters.
> Font colour identical to background, `font-size: 0`, `display: none` on large text blocks, and `overflow: hidden` on zero-height containers are all scored by spam filters as deceptive content padding. The preheader pattern (which does use `display: none`) is a known-good exception, but bulk hidden text is not. Source: SpamAssassin HTML rules.
> `detect: contextual` — check for large hidden text blocks that are not preheaders

**[DELIV-015]** `transactional: venial | marketing: venial` — Email must include at least 500 characters of live (non-image) text for messages containing significant images.
> Spam filters penalise high image-to-text ratios. Single-image emails with no text body (other than a footer) are high-risk. There is no universally applicable magic ratio, but ensuring substantial live text content defends against content-based filtering. Source: Campaign Monitor "Image-to-Text Ratio"; Litmus HTML Email Design Guide.
> `detect: contextual` — estimate live text content vs image content ratio

**[DELIV-016]** `transactional: venial | marketing: venial` — DMARC should progress from `p=none` to `p=quarantine` then `p=reject` once authentication is stable.
> `p=none` monitors but takes no enforcement action. `p=quarantine` routes failing mail to spam. `p=reject` causes receiving MTAs to discard failing messages at SMTP time. Google's stated roadmap indicates `p=none` will eventually be insufficient. Progressive tightening is required. Source: [RFC 7489](https://datatracker.ietf.org/doc/html/rfc7489); Google Sender Guidelines 2024.
> `detect: contextual` — advisory; check project documentation for DMARC policy posture

**[DELIV-017]** `transactional: venial | marketing: venial` — Spam complaint rate must remain below 0.10% for Gmail; below 0.30% triggers delivery rejection.
> Google Postmaster Tools reports spam complaint rates. Rates above 0.08% trigger warnings. Above 0.10% triggers enforcement action. Above 0.30% causes delivery rejection. Complaint rates are driven by unsubscribe friction, unexpected email content, and poor list hygiene. Source: [Google Postmaster Tools](https://support.google.com/mail/answer/81126).
> `detect: contextual` — operational concern; flag in config review if tracking is not configured

**[DELIV-018]** `transactional: counsel | marketing: counsel` — Hard bounces must be suppressed immediately and permanently.
> Sending to hard-bounced addresses (permanent delivery failures — address does not exist) is a major blocklist trigger. Repeated attempts to non-existent addresses raise the sender's bounce rate, damaging IP reputation. Source: RFC 5321 §4.2; Postmark "Bounce Handling".
> `detect: contextual` — advisory; flag if email config indicates bounce handling is not configured at ESP level

**[DELIV-019]** `transactional: counsel | marketing: counsel` — Tracking pixels should be hosted on a dedicated subdomain with proper Content-Type headers.
> Apple Mail Privacy Protection (iOS 15+) pre-fetches all remote content through Apple's proxy servers, inflating open rates. Gmail's image proxy serves cached copies. Mixing tracking pixel domains with main website domains conflates web-browsing reputation with mail reputation. Use a dedicated subdomain (`track.example.com`). Source: Apple Mail Privacy Protection; Litmus "Email Tracking Pixels".
> `detect: contextual` — check tracking configuration in email.config.yml

**[DELIV-020]** `transactional: counsel | marketing: counsel` — SPF record must not exceed 10 DNS lookups.
> RFC 7208 §4.6.4 specifies that SPF evaluation must not require more than 10 DNS lookups. Exceeding this returns `permerror`, which many receivers treat as `fail`. Monitor with MXToolbox or dmarcian. Source: [RFC 7208 §4.6.4](https://datatracker.ietf.org/doc/html/rfc7208#section-4.6.4).
> `detect: contextual` — advisory; flag for infrastructure review

---

## Authentication DNS Reference

### SPF record syntax

```dns
; Authorise SendGrid + a specific IP, hard fail everything else
example.com.  IN  TXT  "v=spf1 include:_spf.sendgrid.net ip4:203.0.113.10 -all"
```

**Common mechanisms:**
- `include:_spf.sendgrid.net` — delegate to ESP's SPF record
- `ip4:203.0.113.0/24` — authorise an IPv4 CIDR
- `-all` — hard fail anything not listed (recommended once deployed)
- `~all` — softfail (use during testing/migration)
- Never use `+all` — authorises any sender

### DKIM selector DNS record

```dns
selector._domainkey.example.com.  IN  TXT
  "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."
```

**DKIM `h=` must include at minimum:** `from:to:subject:date:message-id:mime-version`

### DMARC record

```dns
_dmarc.example.com.  IN  TXT
  "v=DMARC1; p=reject; rua=mailto:dmarc-agg@example.com;
   ruf=mailto:dmarc-forensic@example.com; fo=1;
   adkim=r; aspf=r; pct=100"
```

**Deployment progression:** `p=none` (monitor) → `p=quarantine; pct=10` → `p=quarantine; pct=100` → `p=reject`

### RFC 8058 one-click unsubscribe headers

```
List-Unsubscribe: <mailto:unsubscribe@example.com?subject=unsubscribe-TOKEN>,
  <https://example.com/unsubscribe/TOKEN>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

**Endpoint requirements:** Accept HTTP POST (no redirects), extract subscriber from TOKEN in URL, suppress within 2 days, no session state or cookies required.

## Support Matrix

| Requirement | Applies to | Since |
|-------------|-----------|-------|
| SPF | All senders to Gmail/Yahoo | Google/Yahoo 2024 guidelines |
| DKIM (aligned, ≥1024-bit) | All senders to Gmail/Yahoo | Google/Yahoo 2024 guidelines |
| DMARC `p=none` minimum | Bulk senders ≥5,000/day | Google/Yahoo 2024 guidelines |
| One-click unsubscribe (RFC 8058) | Bulk subscribed/marketing mail ≥5,000/day | Google/Yahoo 2024 guidelines |
| Spam complaint rate < 0.10% | All senders to Gmail | Ongoing enforcement |
| Physical address in footer | US commercial email | CAN-SPAM Act |
| MIME `text/plain` before `text/html` | All senders | RFC 2046 |

## Patterns & Code Examples

### MIME multipart/alternative structure (correct order)

```
Content-Type: multipart/alternative; boundary="BOUNDARY001"

--BOUNDARY001
Content-Type: text/plain; charset="UTF-8"
Content-Transfer-Encoding: quoted-printable

Your order #12345 has shipped.

Estimated delivery: Friday, March 20, 2026.

Track your order:
https://example.com/track/TOKEN

--
Acme Ltd, 123 High Street, London EC1A 1BB
Unsubscribe: https://example.com/unsubscribe/TOKEN

--BOUNDARY001
Content-Type: text/html; charset="UTF-8"
Content-Transfer-Encoding: quoted-printable

<!DOCTYPE html>
<html lang="en">
  ... full HTML template ...
</html>

--BOUNDARY001--
```

`text/plain` appears **before** `text/html`. RFC 2046 multipart/alternative parts are ordered least-preferred to most-preferred. The final part is rendered by clients that support it. Reversing this order causes plain-text clients to display raw HTML source.

### email.config.yml unsubscribe configuration

```yaml
# email.config.yml
subject: "Your order #{{ order.id }} has shipped"
from:
  name: "Acme Shipping"
  email: "shipping@acme.com"

unsubscribe:
  enabled: true
  endpoint: "https://acme.com/unsubscribe/{{ token }}"
  mailto: "unsubscribe@acme.com"
  # Generates: List-Unsubscribe + List-Unsubscribe-Post headers
  # Endpoint must: accept POST, suppress within 2 days, no cookies required

tracking:
  pixel_domain: "track.acme.com"
  click_domain: "click.acme.com"
```

### IP warm-up schedule reference

New IPs have no sending reputation. ESPs assign reputation incrementally. Exceeding the daily volume for a warm-up stage causes block listing.

| Week | Daily volume | Cumulative |
|------|-------------|------------|
| 1 | 200–500 | ~2,500 |
| 2 | 1,000–2,000 | ~10,000 |
| 3 | 5,000–10,000 | ~50,000 |
| 4 | 20,000–50,000 | ~200,000 |
| 5–8 | Full volume | — |

**Warm-up prerequisites:** Start with your best-engaged recipients (recent openers/clickers). High engagement signal early establishes reputation with receiving MTAs. Never warm up with re-engagement campaigns or cold lists.

### Pre-send checklist (config-level verification)

Before deploying a new email template to production, verify:

```
☐ SPF record published for sending domain (MXToolbox: mxtoolbox.com/spf.aspx)
☐ DKIM signed with ≥2048-bit key; h= includes from,to,subject,date,message-id
☐ DMARC published (minimum p=none with rua=)
☐ MIME structure: text/plain before text/html
☐ Plain-text version: complete prose rendering, not stub
☐ No HTTP image URLs (all src= values use https://)
☐ No consumer URL shorteners in any href
☐ Subject line: no ALL-CAPS, no spam trigger phrases
☐ Physical address present in footer
☐ List-Unsubscribe headers configured (if bulk/subscribed mail)
☐ HTML < 102 KB compiled
☐ Complaint rate monitoring active (Google Postmaster Tools configured)
```

## Known Afflictions

**Apple Mail Privacy Protection (MPP) open rate inflation** — iOS 15+ Apple Mail pre-fetches all email content (including tracking pixels) through Apple's proxy regardless of whether the user opens the email. Open rate metrics are unreliable as a deliverability signal for audiences with significant iOS Mail usage. Do not use open rate thresholds for IP warm-up calculations without adjusting for MPP inflation.
Affects: iOS 15+, macOS Monterey+ Apple Mail. Source: [Apple: Mail Privacy Protection](https://support.apple.com/en-us/HT212850).
Fix: Use click rate and complaint rate as primary deliverability signals. Segment MPP-flagged opens from genuine opens in analytics.

**Gmail image proxy caching** — Gmail proxies and caches all email images. The IP that fetches your tracking pixel will be Google's datacenter IP, not the recipient's. Once Gmail fetches and caches an image, subsequent "opens" by the same recipient may not trigger your tracking pixel at all.
Affects: Gmail (all platforms). Source: Litmus.
Fix: Use message-level tokens in image URLs, not session state. Accept that Gmail open tracking is approximate.

**Yahoo aggressive filtering** — Yahoo Mail uses proprietary content-based filtering that scores email independently of authentication status. Yahoo can route authenticated, compliant email to spam if content triggers its Brightmail filters. Subject lines with excessive punctuation (!!!), HTTPS URLs using non-domain-match hostnames, and high image-to-text ratios trigger Yahoo filtering even when authentication is passing.
Affects: Yahoo Mail, AOL Mail (same infrastructure). Source: Yahoo Sender Best Practices 2024.
Fix: Follow content hygiene rules (DELIV-009, DELIV-010, DELIV-015). Monitor Yahoo-specific complaint rates via Yahoo Postmaster (postmaster.yahooinc.com).

**Microsoft SmartScreen / Outlook.com filtering** — Microsoft uses machine-learning filters (SmartScreen) separate from authentication. New sending IPs are automatically treated as suspicious for 30–60 days regardless of authentication status. Microsoft also operates its own blocklist (delist.messaging.microsoft.com).
Affects: Outlook.com, Hotmail, Live.com. Source: Microsoft Sender Support documentation.
Fix: Warm up new IPs gradually. Monitor JMRP (Junk Mail Reporting Program) complaints. If blocklisted, use Microsoft's Self-Service Delisting Portal.

## BIMI (Brand Indicators for Message Identification)

BIMI (RFC 9091) displays your brand logo in Gmail and Apple Mail next to authenticated messages. It is an aspirational standard — not required by the 2024 Google/Yahoo mandates, but increasingly visible to recipients.

**Prerequisites:** DMARC at `p=quarantine` or `p=reject` (BIMI does not work with `p=none`). A Verified Mark Certificate (VMC) from DigiCert or Entrust is required for Gmail display. Apple Mail supports BIMI without a VMC.

```dns
default._bimi.example.com.  IN  TXT
  "v=BIMI1; l=https://example.com/logo.svg; a=https://example.com/vmc.pem"
```

Logo must be in SVG Tiny PS format (a subset of SVG used for print). Standard SVG files are rejected.

BIMI is counsel-level guidance — it has no corresponding rule in this catalog but informs the DMARC progression recommendation (DELIV-016).

## Bounce Categories Reference

Not all bounces are equal. Misclassifying bounces wastes list hygiene budget and masks infrastructure problems.

| Code | Type | Action | Examples |
|------|------|--------|----------|
| 5xx | Hard bounce | Suppress immediately | 550 user unknown, 551 user not local |
| 4xx | Soft bounce | Retry 3× over 72h, then suppress | 421 service unavailable, 452 mailbox full |
| 5.1.1 | User unknown | Hard suppress | Address does not exist |
| 5.7.1 | Rejected (policy) | Investigate | SPF/DKIM failure, blocklisted IP |
| 5.3.4 | Message too large | Reduce template size | HTML exceeds server limit |

**Hard bounces above 2% of sent volume** signal list quality problems and will trigger ESP account reviews. Suppress hard bounces within the same send, not the next day.

## Sources

1. **RFC 7208 (SPF)** — https://datatracker.ietf.org/doc/html/rfc7208
2. **RFC 6376 (DKIM)** — https://datatracker.ietf.org/doc/html/rfc6376
3. **RFC 7489 (DMARC)** — https://datatracker.ietf.org/doc/html/rfc7489
4. **RFC 8058 (One-click unsubscribe)** — https://www.rfc-editor.org/rfc/rfc8058
5. **RFC 2046 (MIME multipart)** — https://datatracker.ietf.org/doc/html/rfc2046
6. **RFC 5321 (SMTP)** — https://datatracker.ietf.org/doc/html/rfc5321 — Bounce codes and retry semantics.
7. **Google Sender Guidelines 2024** — https://support.google.com/mail/answer/81126
8. **Yahoo Sender Best Practices 2024** — https://senders.yahooinc.com/best-practices/
9. **CAN-SPAM Act** — https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
10. **Apache SpamAssassin** — https://spamassassin.apache.org — CAPS rules, HTML evaluation rules.
11. **Postmark** — https://postmarkapp.com/guides — Bounce handling, spam trigger words, URL shorteners.
12. **dmarcian** — https://dmarcian.com — SPF lookup count checker, DMARC deployment tooling.
13. **MXToolbox** — https://mxtoolbox.com — SPF, DKIM, DMARC, blocklist verification.
