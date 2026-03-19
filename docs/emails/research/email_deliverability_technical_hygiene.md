# Email Deliverability & Technical Hygiene

> Reference document for engineers configuring transactional email infrastructure.
> All claims are sourced to authoritative publications. Version: 2026-03-17.

---

## Deliverability Principles

### What "deliverability" actually measures

Deliverability is the probability that a sent message reaches the recipient's inbox
rather than their spam folder, a quarantine queue, or a silent discard. It is a
composite of sender reputation, authentication pass rates, content quality, and
engagement signals. A message can be technically transmitted (delivery rate) yet
still fail deliverability if it lands in spam.

Sources: [SendGrid Email Deliverability Guide](https://sendgrid.com/resource/the-sendgrid-email-deliverability-guide/);
[Mailjet Deliverability Handbook](https://www.mailjet.com/blog/deliverability/email-deliverability-guide/)

### HTML patterns that trigger spam filters

**Excessive capitalisation**
Spam filters score messages that contain ALL-CAPS words outside of abbreviations.
SpamAssassin's `UPPERCASE_25_50` rule fires when 25–50 % of body words are
capitalised; `UPPERCASE_50_75` and `UPPERCASE_75_100` assign escalating scores.
Subject lines are especially sensitive: a subject written entirely in caps is one
of the oldest and most reliable spam signals.

Source: [Apache SpamAssassin Rules — CAPS rules](https://spamassassin.apache.org/full/3.4.x/doc/Mail_SpamAssassin_Plugin_HTMLEval.html);
[Litmus: Email Subject Line Best Practices](https://www.litmus.com/blog/subject-line-best-practices/)

**Spam trigger words**
Certain phrases carry high prior probability of spam based on corpus training.
High-risk clusters include:
- Financial urgency: "Act now", "Limited time offer", "This won't last", "Cash bonus"
- Medication/health: "Weight loss", "Cure", "Miracle"
- Get-rich schemes: "Make money fast", "Work from home", "Earn $", "Double your income"
- Deceptive framing: "You have been selected", "Congratulations", "Free gift"
- Urgency/scarcity with punctuation: "!!!", "???", "$ $ $"

These words are not absolute triggers — context, authentication state, and sender
reputation moderate their impact — but they raise composite spam scores. For
transactional email the best practice is to avoid marketing-style language entirely.

Source: [HubSpot: 394 Spam Trigger Words to Avoid](https://blog.hubspot.com/marketing/words-that-make-your-email-spammy);
[Mailchimp: Spam Filters](https://mailchimp.com/help/about-spam-filters/)

**Image-to-text ratio**
A message composed almost entirely of images with little or no text is a classic
evasion technique: spammers embed text inside images to bypass keyword scanning.
Consequently, spam filters penalise high image-to-text ratios.

The "60 % text / 40 % images" guideline that circulated widely was a rule of thumb
from early-2010s ESPs, not a formally specified filter threshold. Current guidance
from major ESPs (Litmus, Campaign Monitor, Mailchimp) has evolved: there is no
single magic ratio, and modern filters weight sender reputation and authentication
state far more than image ratio alone. The practical rules that remain valid:
- Include at minimum 500 characters of live (non-image) text for any message
  containing significant images.
- Single-image emails with no text body (other than a footer) are high-risk
  regardless of ratio.
- Alt text must be present on all images.
- Images must be hosted on HTTPS with correct Content-Type headers (a filter
  signal independent of ratio).

Source: [Campaign Monitor: Image-to-Text Ratio](https://www.campaignmonitor.com/resources/guides/image-spam/);
[Litmus: HTML Email Design Guide](https://www.litmus.com/blog/best-practices-for-html-email/)

**Link density**
Too many hyperlinks relative to body text raises spam scores. SpamAssassin's
`HTML_IMAGE_RATIO_*` and `LOTS_OF_MONEY` rules are partly driven by link counts.
Practical guidance:
- Avoid more than ~3 links per 100 words of body text.
- Do not use raw IP addresses as link destinations (e.g., `http://192.0.2.1/track`).
- Avoid multiple different domains in a single email; every domain linked is
  checked against URI blocklists (SURBL, URIBL).
- Avoid redirect chains where the final domain differs from the visible anchor text.

Source: [SpamAssassin: URI-based rules](https://spamassassin.apache.org/full/3.4.x/doc/);
[Postmark: Why Emails Go to Spam](https://postmarkapp.com/guides/why-emails-go-to-spam)

**Invisible text and CSS tricks**
Font colour identical or very close to background colour, font-size set to 0 or 1 px,
`display:none` applied to large text blocks, and `overflow:hidden` with zero-height
containers are all scored by filters as deceptive content padding. Avoid all of these.

Source: [SpamAssassin: HTML rules](https://spamassassin.apache.org/full/3.4.x/doc/Mail_SpamAssassin_Plugin_HTMLEval.html)

**Malformed or tag-soup HTML**
Spam filters and rendering engines alike treat severely malformed HTML (unclosed
tags, missing DOCTYPE, invalid nesting) as suspicious, partly because it is
consistent with programmatically generated spam. Use a proper HTML serialiser and
validate output.

Source: [Litmus: HTML Email Best Practices](https://www.litmus.com/blog/best-practices-for-html-email/)

---

## MIME Structure

### The correct multipart structure

Transactional email MUST be sent as `multipart/alternative` when both HTML and
plain-text versions are included. The correct MIME tree is:

```
Content-Type: multipart/alternative; boundary="boundary-string"

--boundary-string
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: quoted-printable

[plain text version]

--boundary-string
Content-Type: text/html; charset=UTF-8
Content-Transfer-Encoding: quoted-printable

[HTML version]

--boundary-string--
```

MIME part order matters: `text/plain` MUST come before `text/html`. RFC 2046
specifies that for `multipart/alternative`, parts are listed in increasing order
of preference (the last part is preferred). Mail clients render the last part they
can handle, so HTML must appear last. Inverting this order causes plain-text-only
clients to display raw HTML source.

Source: [RFC 2046 §5.1.4 — The Multipart/Alternative Subtype](https://datatracker.ietf.org/doc/html/rfc2046#section-5.1.4)

### When attachments are present

If the message includes attachments, the correct outer type is `multipart/mixed`,
with the `multipart/alternative` part nested inside it:

```
Content-Type: multipart/mixed; boundary="outer"

--outer
Content-Type: multipart/alternative; boundary="inner"

--inner
Content-Type: text/plain; charset=UTF-8
...

--inner
Content-Type: text/html; charset=UTF-8
...
--inner--

--outer
Content-Type: application/pdf; name="invoice.pdf"
Content-Disposition: attachment; filename="invoice.pdf"
Content-Transfer-Encoding: base64
...
--outer--
```

Source: [RFC 2046 §5.1.3 — The Multipart/Mixed Subtype](https://datatracker.ietf.org/doc/html/rfc2046#section-5.1.3)

### Character encoding

Always declare `charset=UTF-8` on text parts. Use `quoted-printable` (QP) encoding
for text parts (better readability in raw form, preferred for text) and `base64` for
binary attachments. Using `8bit` Content-Transfer-Encoding is technically valid
per RFC 6152 but is not universally safe across all MTA hops; QP is safer.

Source: [RFC 2045 §6 — Content-Transfer-Encoding](https://datatracker.ietf.org/doc/html/rfc2045#section-6);
[RFC 6152 — SMTP Service Extension for 8-bit MIME Transport](https://datatracker.ietf.org/doc/html/rfc6152)

### Plain-text version requirements

Plain-text versions are not optional for good deliverability:
1. Their absence raises spam scores on some filters (Barracuda, Proofpoint).
2. Accessibility screen readers and some corporate mail gateways default to
   plain text.
3. They are required by CAN-SPAM for commercial messages (physical address in
   plain text must be present and readable).

The plain-text version must be a genuine prose rendering of the HTML content,
not a stub ("Please view the HTML version of this email") and not a raw HTML
dump. Strip all tags and replace structural elements with whitespace/dashes.

Source: [CAN-SPAM Act (15 U.S.C. §7704)](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business);
[Postmark: Plain-Text Emails](https://postmarkapp.com/guides/plain-text-vs-html-emails)

### Text-to-HTML ratio within the HTML part

Within the HTML body itself, ensure rendered text (content visible to a user)
is not dwarfed by tag overhead. A useful heuristic: the ratio of HTML source
bytes to rendered-text bytes should not exceed 10:1. Heavily nested table
layouts from legacy ESP templates can push this to 50:1, which some filters
penalise. Use semantic HTML5 where possible in new templates.

Source: [Litmus: HTML Email Design Guide](https://www.litmus.com/blog/best-practices-for-html-email/)

### Line length

RFC 5321 sets a hard limit of 998 octets per line for the DATA portion of an
SMTP message and recommends lines of 78 characters or fewer. Quoted-printable
encoding handles this automatically for text parts. For the HTML part, ensure
your serialiser wraps at or before 998 characters. Some older gateway software
silently truncates or corrupts lines that exceed this limit, which breaks
DKIM signatures.

Source: [RFC 5321 §4.5.3.1.6 — Maximum Message Size](https://datatracker.ietf.org/doc/html/rfc5321#section-4.5.3.1.6)

---

## Authentication (SPF, DKIM, DMARC)

### SPF — Sender Policy Framework

**What it does**
SPF (RFC 7208) allows a domain owner to publish, via DNS TXT records, an
authoritative list of IP addresses and hostnames permitted to send mail from
that domain. The receiving MTA checks the `MAIL FROM` (envelope sender, also
called the Return-Path) against the sending IP. If the IP is not listed, the
result is `fail` or `softfail`.

SPF alone does not protect the `From:` header — that is DMARC's role.

**Record syntax**

```
v=spf1 [mechanisms] [modifiers] [all]
```

Common mechanisms:
- `ip4:203.0.113.0/24` — authorise an IPv4 CIDR range
- `ip6:2001:db8::/32` — authorise an IPv6 CIDR range
- `include:_spf.sendgrid.net` — delegate to a third-party provider's SPF record
- `a` — authorise the domain's A/AAAA record IPs
- `mx` — authorise the domain's MX record IPs
- `exists:%{i}._spf.example.com` — macro-based authorisation

Qualifiers (prefix to mechanism):
- `+` (default) — Pass
- `-` — Fail (hard fail)
- `~` — SoftFail (tag but accept)
- `?` — Neutral

**All mechanism (terminator)**
- `-all` — hard fail anything not listed; recommended once fully deployed
- `~all` — softfail; used during migration/testing
- `+all` — authorises any sender; never use this

**Recommended configuration**

```dns
example.com.  IN  TXT  "v=spf1 include:_spf.sendgrid.net ip4:203.0.113.10 -all"
```

**SPF DNS lookup limit**
RFC 7208 §4.6.4 specifies that SPF evaluation MUST NOT require more than 10 DNS
lookups that themselves trigger further lookups (`include`, `a`, `mx`, `exists`,
`redirect`). Exceeding 10 lookups returns `permerror`, which many receivers treat
as `fail`. The `ip4` and `ip6` mechanisms do NOT count against the limit.

Monitor lookup count with tools such as MXToolbox SPF checker or dmarcian.

**Verification**

```bash
dig TXT example.com +short | grep spf
nslookup -type=TXT example.com
```

Source: [RFC 7208 — Sender Policy Framework (SPF)](https://datatracker.ietf.org/doc/html/rfc7208)

---

### DKIM — DomainKeys Identified Mail

**What it does**
DKIM (RFC 6376) allows a sending domain to cryptographically sign outgoing
messages. The signature is added as a `DKIM-Signature:` header. The receiving
MTA retrieves the public key from DNS and verifies the signature against the
signed headers and body. A valid DKIM signature proves:
1. The message was authorised by the owner of the signing domain.
2. The signed headers and body have not been modified in transit.

DKIM signs the `From:` header (when `h=` includes `from`), which directly
supports DMARC alignment.

**Key components**

`DKIM-Signature` header fields:
- `v=1` — version
- `a=rsa-sha256` — signing algorithm (rsa-sha256 is required; ed25519-sha256 is
  supported since RFC 8463 and recommended as a second signature for modern clients)
- `c=relaxed/relaxed` — canonicalisation (header/body); `relaxed` is tolerant
  of minor whitespace changes introduced by MTAs; preferred over `simple/simple`
- `d=example.com` — signing domain
- `s=selector` — selector (maps to DNS key record)
- `h=from:to:subject:date:message-id:mime-version:content-type` — signed headers
- `bh=` — body hash (base64)
- `b=` — header signature (base64)

**DNS key record**

```dns
selector._domainkey.example.com.  IN  TXT
  "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."
```

**Recommended key size**
RSA-2048 is the minimum recommended key length. RSA-1024 is deprecated and
rejected by many receivers including Gmail. RSA-4096 is supported but has
higher signing overhead and some DNS record size limitations (requires multiple
TXT strings). ed25519 keys are 256-bit and are fast with small DNS records.

**Header fields to include in `h=`**
Always include: `from`, `to`, `subject`, `date`, `message-id`, `mime-version`.
Consider also: `content-type`, `reply-to`, `cc`. Do NOT include
`received`, `return-path`, or `resent-*` headers as they are modified by MTAs.

**Key rotation**
Rotate DKIM keys at least annually, or immediately upon suspected compromise.
Use a new selector for each key. Keep the old selector in DNS for 48–72 hours
after rotation to allow in-flight messages to verify.

**Verification**

```bash
dig TXT selector._domainkey.example.com +short
```

Source: [RFC 6376 — DomainKeys Identified Mail (DKIM) Signatures](https://datatracker.ietf.org/doc/html/rfc6376);
[RFC 8463 — A New Cryptographic Signature Method for DomainKeys Identified Mail (DKIM)](https://datatracker.ietf.org/doc/html/rfc8463)

---

### DMARC — Domain-based Message Authentication, Reporting, and Conformance

**What it does**
DMARC (RFC 7489) builds on SPF and DKIM by:
1. Defining a policy for what receivers should do with messages that fail both
   SPF and DKIM alignment.
2. Requiring "identifier alignment" — the authenticated domain (from SPF or DKIM)
   must match the RFC5322 `From:` domain.
3. Enabling aggregate (rua) and forensic (ruf) reporting back to the domain owner.

**Alignment modes**
- **Relaxed** (`aspf=r`, `adkim=r`, default): the authenticated domain must share
  the organisational domain (eTLD+1) with the `From:` domain.
  e.g., `mail.example.com` aligns with `example.com`.
- **Strict** (`aspf=s`, `adkim=s`): the authenticated domain must exactly match
  the `From:` domain.

Use relaxed for most deployments. Strict is appropriate when subdomains are
operated by different parties.

**Policy values (`p=`)**
- `none` — monitor only; no action taken on failing messages; use for initial
  visibility phase
- `quarantine` — route failing messages to the spam/junk folder
- `reject` — the receiving MTA should reject the message at SMTP time; strongest
  protection; use once confident in your authentication posture

**Subdomain policy (`sp=`)**
Optionally set a separate policy for subdomains. Useful when the parent domain is
at `p=reject` but subdomains are not yet fully authenticated.

**DNS record**

```dns
_dmarc.example.com.  IN  TXT
  "v=DMARC1; p=reject; rua=mailto:dmarc-agg@example.com;
   ruf=mailto:dmarc-forensic@example.com; fo=1;
   adkim=r; aspf=r; pct=100"
```

Key tags:
- `rua=` — URI(s) for aggregate XML reports (sent daily by receivers)
- `ruf=` — URI(s) for failure/forensic reports (per-message redacted copies)
- `fo=1` — generate forensic report on any authentication failure (not just total
  DMARC failure); `fo=0` is default (only report if all mechanisms fail)
- `pct=` — percentage of messages the policy applies to; use `pct=10` → `pct=100`
  during staged rollout; remove tag (implicit 100) once fully deployed
- `ri=` — reporting interval in seconds (default 86400 = 24 h)

**Deployment roadmap**
1. Publish `p=none; rua=mailto:...` and collect aggregate reports for ≥ 2 weeks.
2. Analyse reports with dmarcian, Postmark DMARC, or Google Postmaster Tools.
3. Resolve any SPF/DKIM alignment failures (e.g., third-party senders not covered).
4. Move to `p=quarantine; pct=10`, then `pct=100`.
5. Move to `p=reject` once quarantine shows negligible legitimate failures.

**Google & Yahoo February 2024 mandatory sender requirements**

Effective February 2024, Google and Yahoo imposed requirements on bulk senders
(defined as senders of ≥ 5,000 messages/day to Gmail or Yahoo addresses).
These are no longer best-practice recommendations — they are enforced, with
non-compliant mail subject to rejection.

Requirements applicable to ALL senders (any volume):
- Valid forward-confirmed reverse DNS (FCrDNS) for the sending IP.
- TLS for the SMTP connection.
- Valid SPF or DKIM alignment with the `From:` domain.

Additional requirements for bulk senders (≥ 5,000 msgs/day):
- **SPF** must pass for the sending domain.
- **DKIM** must pass with a key of at least 1024 bits (2048 recommended); the
  signing domain (`d=`) must align with the `From:` domain.
- **DMARC** must be published at minimum `p=none` with a valid `rua=` address.
  Google's stated roadmap is that `p=none` will eventually be insufficient;
  movement toward `p=quarantine` or `p=reject` is encouraged.
- **One-click unsubscribe** (RFC 8058 `List-Unsubscribe-Post` header) must be
  present and functional for all subscribed/marketing mail. The address must be
  removed within 2 days of a one-click unsubscribe request.
- **Spam complaint rate** must remain below 0.10 %; sustained rates above 0.08 %
  trigger warnings in Google Postmaster Tools. Rates above 0.30 % result in
  delivery rejection.

Yahoo's 2024 requirements are substantively identical to Google's for bulk senders,
with the same authentication (SPF + DKIM + DMARC `p=none` minimum) and one-click
unsubscribe mandate.

Source: [RFC 7489 — DMARC](https://datatracker.ietf.org/doc/html/rfc7489);
[Google: Email Sender Guidelines (2024)](https://support.google.com/mail/answer/81126);
[Yahoo: Sender Best Practices](https://senders.yahooinc.com/best-practices/)

---

### MTA-STS and DNSSEC (supplementary authentication)

**MTA-STS** (RFC 8461) allows a domain to declare that inbound SMTP connections
must use TLS and specify which certificates are acceptable. This prevents
downgrade attacks. Publish a policy file at
`https://mta-sts.example.com/.well-known/mta-sts.txt` and a DNS record:

```dns
_mta-sts.example.com.  IN  TXT  "v=STSv1; id=20260301120000Z"
```

**TLS-RPT** (RFC 8460) provides SMTP TLS reporting, analogous to DMARC's `rua`.

**BIMI** (Brand Indicators for Message Identification) allows a verified logo to
appear next to authenticated messages in supporting clients (Gmail, Yahoo, Apple
Mail). Requires DMARC at `p=quarantine` or `p=reject` and a Verified Mark
Certificate (VMC) from a qualifying CA. DNS record at `default._bimi.example.com`.

Source: [RFC 8461 — SMTP MTA Strict Transport Security (MTA-STS)](https://datatracker.ietf.org/doc/html/rfc8461);
[RFC 8460 — SMTP TLS Reporting](https://datatracker.ietf.org/doc/html/rfc8460);
[BIMI Group Specification](https://bimigroup.org/specification/)

---

## Link & Image Hygiene

### Tracking pixels

A tracking pixel is a 1×1 (or 0×0) transparent image whose URL encodes a unique
message identifier. When the email client fetches the image, the server records
an open event.

Technical considerations:
- Host tracking pixels on a dedicated subdomain (e.g., `track.example.com`) with
  a clean IP reputation. Sharing a tracking domain with your main website mixes
  web-browsing reputation with mail reputation.
- Respond to pixel requests with the correct `Content-Type: image/gif` (or PNG)
  and return a genuine 1×1 transparent GIF/PNG, not a redirect to an image.
  Redirect chains on image URLs can trigger URL scanners.
- Apple Mail Privacy Protection (iOS 15+, macOS Monterey+) pre-fetches all remote
  content including tracking pixels through Apple's proxy servers, inflating open
  rates. Do not use open rate as a sole deliverability signal.
- Gmail's image proxy caches and re-serves images; the IP that fetches your pixel
  will be Google's, not the recipient's.

Source: [Litmus: Email Tracking Pixels](https://www.litmus.com/blog/email-tracking-pixel/);
[Apple: Mail Privacy Protection](https://support.apple.com/en-us/HT212850)

### URL shorteners

Do NOT use consumer URL shorteners (bit.ly, tinyurl.com, t.co) in transactional
or marketing email. Reasons:
1. Shared shortener domains accumulate spam reputation; many are permanently
   blocklisted in SURBL and URIBL.
2. The final destination is obscured, which is itself a spam signal.
3. If the shortener service has an outage, all links in sent messages break.

Use your own tracking domain as a redirect proxy instead
(e.g., `click.example.com/c/[token]` → final URL).

Source: [Postmark: URL Shorteners and Deliverability](https://postmarkapp.com/blog/url-shorteners-hurt-email-deliverability);
[SparkPost/MessageBird: Link Tracking Best Practices](https://www.sparkpost.com/blog/email-link-tracking/)

### CDN hosting for images

Host all email images on a CDN with:
- HTTPS (HTTP image URLs receive lower trust scores from some filters, and many
  clients block HTTP images by default).
- A stable, dedicated subdomain (`images.example.com`) with consistent DNS; do
  not use S3 bucket URLs (`*.s3.amazonaws.com`) or generic CDN hostnames — these
  are shared-reputation domains that may be flagged.
- Long cache-control headers (images in sent email are immutable; `max-age=31536000`
  is appropriate).
- Correct Content-Type headers per image format.

Source: [Campaign Monitor: Hosting Images for Email](https://www.campaignmonitor.com/resources/guides/image-spam/);
[Litmus: Email Image Hosting](https://www.litmus.com/blog/best-practices-for-html-email/)

### Unsubscribe link requirements

**CAN-SPAM (US)**: commercial messages must include a clear, functioning opt-out
mechanism. The opt-out link must remain functional for at least 30 days after
the message is sent. Opt-out requests must be honoured within 10 business days.
Physical postal address must also be present.

**GDPR/CASL**: consent-based opt-out requirements with stricter definitions of
"commercial message". Not covered in detail here — consult a legal review.

**List-Unsubscribe header**: add both the mailto and HTTPS variants:

```
List-Unsubscribe: <mailto:unsubscribe@example.com?subject=unsubscribe-[token]>,
  <https://example.com/unsubscribe/[token]>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

**RFC 8058 one-click unsubscribe — technical requirements**

The `List-Unsubscribe-Post` header value must be exactly `List-Unsubscribe=One-Click`
(RFC 8058 §3.2). When a mail client issues a one-click unsubscribe signal, it sends
an HTTP POST to the HTTPS URI specified in `List-Unsubscribe:`. The POST body is
encoded as either `multipart/form-data` (RFC 7578) or
`application/x-www-form-urlencoded`, containing the single key-value pair
`List-Unsubscribe=One-Click`.

Endpoint implementation requirements (RFC 8058 §3):
- The HTTPS URI must embed sufficient opaque data (e.g., a per-recipient token) to
  identify the subscription without requiring the client to send cookies, HTTP
  authorisation headers, or session state.
- The endpoint MUST NOT return HTTP redirects in response to the POST; redirect
  behaviour on POST requests is unreliable across implementations.
- Process the suppression immediately on receipt (Google's 2024 guidelines require
  removal within 2 business days; immediate suppression is the correct engineering
  target).

Google's 2024 sender requirements mandate `List-Unsubscribe-Post` for all bulk
marketing/subscribed mail sent to Gmail at ≥ 5,000 msgs/day. Yahoo's 2024
requirements impose the same mandate. When a Gmail user clicks the "Unsubscribe"
link rendered by Gmail's UI, Gmail issues the RFC 8058 POST on their behalf.

Source: [CAN-SPAM Act (15 U.S.C. §7704)](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business);
[RFC 8058 — Signaling One-Click Functionality for List Email Headers](https://www.rfc-editor.org/rfc/rfc8058);
[Google: Sender Guidelines — Unsubscribe](https://support.google.com/mail/answer/81126)

### URI blocklist checking

Before deploying any domain in email links, verify it is not listed in:
- **SURBL** (surbl.org) — spam URI realtime blocklist
- **URIBL** (uribl.com) — multi-zone URI blocklist
- **Google Safe Browsing** (transparencyreport.google.com/safe-browsing/search)
- **Spamhaus DBL** (Domain Block List)

Check programmatically via DNS lookups against the blocklist zones. For SURBL:

```bash
host example.com.multi.surbl.org
# NXDOMAIN = not listed (clean)
# Returns 127.0.0.x = listed
```

Source: [SURBL Documentation](https://www.surbl.org/usage);
[Spamhaus DBL](https://www.spamhaus.org/dbl/)

---

## Transactional Notes

### Transactional vs marketing deliverability: key differences

| Dimension               | Transactional                          | Marketing/Bulk                         |
|-------------------------|----------------------------------------|----------------------------------------|
| Consent basis           | Implied by user action (signup, order) | Explicit opt-in required               |
| Expected engagement     | High (password reset, receipt)         | Variable; unsubscribes common          |
| IP strategy             | Dedicated IPs, low volume              | Dedicated IPs, warm-up required        |
| Content sensitivity     | Functional, minimal HTML               | Promotional, image-heavy               |
| Urgency tolerance       | High (time-critical)                   | Low (batch delivery acceptable)        |
| List hygiene            | Auto-suppress hard bounces             | Regular list scrubbing required        |
| CAN-SPAM classification | Transactional (§7702(17))              | Commercial (§7702(2))                  |
| Unsubscribe requirement | Not required by CAN-SPAM (transactional exception) | Mandatory |
| One-click unsubscribe   | Not required                           | Required (Google/Yahoo ≥ 5k/day)       |

CAN-SPAM's transactional exception (15 U.S.C. §7702(17)) applies only to messages
whose "primary purpose" is transactional. If a transactional message contains
promotional content (upsell, cross-sell), its classification may shift to
"commercial" and it must include an opt-out.

Source: [CAN-SPAM Act (15 U.S.C. §7702)](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business);
[SendGrid: Transactional vs Marketing Email](https://sendgrid.com/blog/transactional-vs-marketing-email/)

### IP reputation and dedicated IPs

Every sending IP has a reputation maintained by ISPs and blocklist operators.
New IPs have no reputation — they are treated neutrally until enough volume
accumulates to establish a signal. Very low volume from a new IP can look
suspicious (some spammers use fresh IPs and send a single blast).

Dedicated IPs isolate your reputation from other senders. They are recommended
when:
- Daily volume exceeds ~50,000 messages, OR
- You need strict SLA isolation (transactional must not be harmed by marketing
  campaigns on the same IP).

Below ~10,000–50,000 messages/day, the reputation signal is too thin for a
dedicated IP to be advantageous; shared IPs from a reputable ESP are typically
safer because they carry pooled positive reputation.

Source: [SendGrid: Dedicated IP Addresses](https://docs.sendgrid.com/ui/account-and-settings/dedicated-ip-addresses);
[Mailjet: Dedicated IP Guide](https://www.mailjet.com/blog/deliverability/dedicated-ip-address/)

### IP warm-up strategy

A new dedicated IP must be "warmed up" — volume is ramped incrementally to
build reputation before sending at full scale. A typical ramp-up schedule
for a transactional stream (already engaged users):

| Day(s)   | Max messages/day |
|----------|-----------------|
| 1–2      | 200             |
| 3–4      | 500             |
| 5–7      | 1,000           |
| 8–11     | 5,000           |
| 12–17    | 10,000          |
| 18–24    | 25,000          |
| 25–30    | 50,000          |
| 31+      | Full volume     |

During warm-up, send only to your highest-engagement segment (users who opened or
clicked recently). Hard bounces and spam complaints during warm-up cause
disproportionate reputation damage. Aim for:
- Spam complaint rate < 0.08 % (Google's threshold for warning; 0.10 % triggers
  enforcement action; 0.30 % triggers delivery rejection)
- Hard bounce rate < 2 %

Monitor with Google Postmaster Tools, Microsoft SNDS (Smart Network Data Services),
and your ESP's reputation dashboard.

Source: [SendGrid: IP Warm-up Guide](https://sendgrid.com/resource/everything-about-ip-warm-up/);
[Google: Postmaster Tools — Spam Rate Threshold](https://support.google.com/mail/answer/81126);
[Microsoft SNDS](https://sendersupport.olc.protection.outlook.com/snds/)

### Bounce handling

**Hard bounce** (5xx permanent): address does not exist or domain is invalid.
Suppress the address immediately and permanently. Do not retry.

**Soft bounce** (4xx temporary): mailbox full, server temporarily unavailable,
rate limit. Retry with exponential back-off. After 3–5 consecutive soft bounces
over 72 hours, treat as a hard bounce and suppress.

Maintain a suppression list and check new addresses against it before sending.
Sending to previously hard-bounced addresses repeatedly is a major blocklist
trigger.

Source: [RFC 5321 §4.2 — SMTP Reply Codes](https://datatracker.ietf.org/doc/html/rfc5321#section-4.2);
[Postmark: Bounce Handling](https://postmarkapp.com/developer/api/bounce-api)

### Feedback loops (FBL)

Major ISPs offer feedback loop programmes: when a recipient clicks "Mark as
Spam", the ISP forwards a copy of the message (or a redacted ARF report) to the
sender. Register with:
- **Gmail** — Google does not offer a traditional FBL; use Postmaster Tools
  complaint rate instead.
- **Microsoft/Outlook** — [Junk Mail Reporting Program (JMRP)](https://sendersupport.olc.protection.outlook.com/jmrp/)
- **Yahoo** — [Complaint Feedback Loop](https://senders.yahooinc.com/)
- **SpamCop** — forwards ARF (Abuse Reporting Format, RFC 5965) reports

Upon receiving an FBL complaint, suppress the reporting address immediately.

Source: [RFC 5965 — An Extensible Format for Email Feedback Reports](https://datatracker.ietf.org/doc/html/rfc5965);
[Microsoft JMRP](https://sendersupport.olc.protection.outlook.com/jmrp/)

### Sending infrastructure headers

Add these headers to every outbound message for traceability and filtering:

```
Message-ID: <unique-id@mail.example.com>
Date: [RFC 2822 formatted timestamp]
X-Mailer: YourAppName/1.0
```

`Message-ID` must be globally unique; a common pattern is
`<timestamp.random@sending-domain.com>`. `Date` must be present (RFC 5322
requires it) and accurate — large skews from the current time trigger spam filters.

Source: [RFC 5322 §3.6 — Field Definitions](https://datatracker.ietf.org/doc/html/rfc5322#section-3.6)

---

## Pre-send QA Checklist

A checklist for engineers releasing a new transactional email template or
routing change to production.

### Authentication

- [ ] SPF record published for sending domain; `dig TXT sending-domain.com` returns a valid `v=spf1` record
- [ ] SPF lookup count ≤ 10 (verified with MXToolbox or dmarcian)
- [ ] DKIM key published at `selector._domainkey.sending-domain.com`; key is RSA-2048 or ed25519
- [ ] DKIM signing configured on the MTA/ESP; `DKIM-Signature` header present in raw message
- [ ] DKIM canonicalisation set to `relaxed/relaxed`
- [ ] `From:` domain matches (or aligns with) SPF and DKIM signing domain for DMARC alignment
- [ ] DMARC record published at `_dmarc.sending-domain.com`; at minimum `p=none; rua=mailto:...`
- [ ] Aggregate DMARC reports being received and reviewed
- [ ] If subdomain is used for sending (e.g., `mail.example.com`), DMARC alignment confirmed
- [ ] If sending ≥ 5,000 msgs/day to Gmail or Yahoo: SPF + DKIM + DMARC all present (February 2024 mandatory requirement)

### MIME and Content

- [ ] Message is `multipart/alternative` with `text/plain` before `text/html`
- [ ] If attachments present, outer type is `multipart/mixed` with `multipart/alternative` nested correctly
- [ ] Plain-text part is a genuine prose version of the HTML (not a stub)
- [ ] Both parts declare `charset=UTF-8`
- [ ] Content-Transfer-Encoding is `quoted-printable` for text parts
- [ ] No lines exceed 998 octets in the DATA section
- [ ] `Message-ID` header present and globally unique
- [ ] `Date` header present and accurate (within ±30 minutes of actual send time)
- [ ] HTML does not contain ALL-CAPS words outside of standard abbreviations
- [ ] No spam trigger words in subject or body
- [ ] Sufficient live text present (≥ 500 characters for image-heavy messages)
- [ ] No invisible text (white text on white, font-size 0, display:none padding)
- [ ] HTML DOCTYPE declared; HTML is well-formed

### Links and Images

- [ ] All URLs use HTTPS
- [ ] No URL shorteners (bit.ly, tinyurl, etc.)
- [ ] Tracking domain (click/open) is on a dedicated subdomain, not the main website
- [ ] All linked domains checked against SURBL, URIBL, Spamhaus DBL — clean
- [ ] All image domains checked against blocklists — clean
- [ ] Images hosted on HTTPS CDN with correct Content-Type headers
- [ ] Tracking pixel returns a genuine 1×1 image, not a redirect
- [ ] `List-Unsubscribe` header present (even for transactional — best practice)
- [ ] `List-Unsubscribe-Post: List-Unsubscribe=One-Click` present for all bulk/subscribed streams
- [ ] Unsubscribe HTTPS endpoint correctly processes POST with body `List-Unsubscribe=One-Click`
- [ ] Unsubscribe endpoint does NOT issue HTTP redirects in response to POST
- [ ] Suppression applied within 2 business days of one-click unsubscribe receipt (Google/Yahoo requirement)

### Infrastructure

- [ ] Sending IP is not listed in Spamhaus SBL, XBL, PBL; checked via `dig`
- [ ] Reverse DNS (PTR) record for sending IP resolves to the sending hostname
- [ ] Forward-confirmed rDNS: the hostname in PTR resolves back to the sending IP (FCrDNS)
- [ ] If new dedicated IP: warm-up schedule is active; not sending full volume
- [ ] Hard bounce suppression is active; previously bounced addresses will not receive this message
- [ ] Soft bounce retry logic uses exponential back-off with a cap (e.g., max 3 retries over 72 h)
- [ ] FBL registrations are active for Microsoft JMRP and Yahoo
- [ ] Google Postmaster Tools domain verified; complaint rate dashboard monitored; alert set at 0.08 %

### Compliance

- [ ] Physical mailing address present in message body (CAN-SPAM requirement for commercial email)
- [ ] If message contains any promotional content, opt-out link is present
- [ ] Opt-out processing will complete within 10 business days (CAN-SPAM) or immediately (CASL)
- [ ] `From:` display name and address are not deceptive; domain matches sending infrastructure

### Pre-deployment test

- [ ] Send test message to a seed list across major providers (Gmail, Outlook, Yahoo, Apple Mail)
- [ ] Run message through [Mail Tester](https://www.mail-tester.com/) or [GlockApps](https://glockapps.com/) to check spam score
- [ ] Verify rendering across clients using Litmus or Email on Acid
- [ ] Inspect raw message headers to confirm DKIM signature is present and validates
- [ ] Confirm SPF passes by checking `Authentication-Results` header in a received message
- [ ] Confirm DMARC alignment by checking `Authentication-Results` — both `spf=pass` and `dkim=pass` with correct domain

---

## Sources

All sources are publicly accessible as of 2026-03-17.

### RFCs (Internet Engineering Task Force)

1. **RFC 2045** — Multipurpose Internet Mail Extensions (MIME) Part One: Format of Internet Message Bodies.
   https://datatracker.ietf.org/doc/html/rfc2045

2. **RFC 2046** — MIME Part Two: Media Types (defines `multipart/alternative`, `multipart/mixed`).
   https://datatracker.ietf.org/doc/html/rfc2046

3. **RFC 5321** — Simple Mail Transfer Protocol (reply codes, message size limits, DATA section rules).
   https://datatracker.ietf.org/doc/html/rfc5321

4. **RFC 5322** — Internet Message Format (headers: `From`, `Date`, `Message-ID`, etc.).
   https://datatracker.ietf.org/doc/html/rfc5322

5. **RFC 5965** — An Extensible Format for Email Feedback Reports (ARF/FBL format).
   https://datatracker.ietf.org/doc/html/rfc5965

6. **RFC 6152** — SMTP Service Extension for 8-bit MIME Transport.
   https://datatracker.ietf.org/doc/html/rfc6152

7. **RFC 6376** — DomainKeys Identified Mail (DKIM) Signatures.
   https://datatracker.ietf.org/doc/html/rfc6376

8. **RFC 7208** — Sender Policy Framework (SPF) for Authorizing Use of Domains in Email.
   https://datatracker.ietf.org/doc/html/rfc7208

9. **RFC 7489** — Domain-based Message Authentication, Reporting, and Conformance (DMARC).
   https://datatracker.ietf.org/doc/html/rfc7489

10. **RFC 8058** — Signaling One-Click Functionality for List Email Headers.
    https://www.rfc-editor.org/rfc/rfc8058

11. **RFC 8461** — SMTP MTA Strict Transport Security (MTA-STS).
    https://datatracker.ietf.org/doc/html/rfc8461

12. **RFC 8460** — SMTP TLS Reporting (TLS-RPT).
    https://datatracker.ietf.org/doc/html/rfc8460

13. **RFC 8463** — A New Cryptographic Signature Method for DomainKeys Identified Mail (ed25519-sha256).
    https://datatracker.ietf.org/doc/html/rfc8463

### Regulatory

14. **CAN-SPAM Act (15 U.S.C. §7701–7713)** — US commercial email law.
    https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business

### ESP / Platform Documentation

15. **Google: Email Sender Guidelines (2024 update)**.
    https://support.google.com/mail/answer/81126

16. **Google Postmaster Tools**.
    https://postmaster.google.com/

17. **Yahoo / Verizon Media: Sender Best Practices**.
    https://senders.yahooinc.com/best-practices/

18. **Microsoft SNDS (Smart Network Data Services)**.
    https://sendersupport.olc.protection.outlook.com/snds/

19. **Microsoft JMRP (Junk Mail Reporting Program)**.
    https://sendersupport.olc.protection.outlook.com/jmrp/

20. **SendGrid: Email Deliverability Guide**.
    https://sendgrid.com/resource/the-sendgrid-email-deliverability-guide/

21. **SendGrid: IP Warm-up Guide**.
    https://sendgrid.com/resource/everything-about-ip-warm-up/

22. **SendGrid: Dedicated IP Addresses**.
    https://docs.sendgrid.com/ui/account-and-settings/dedicated-ip-addresses

23. **SendGrid: Transactional vs Marketing Email**.
    https://sendgrid.com/blog/transactional-vs-marketing-email/

24. **Mailjet: Email Deliverability Handbook**.
    https://www.mailjet.com/blog/deliverability/email-deliverability-guide/

25. **Mailjet: Dedicated IP Guide**.
    https://www.mailjet.com/blog/deliverability/dedicated-ip-address/

26. **SparkPost/MessageBird: Link Tracking Best Practices**.
    https://www.sparkpost.com/blog/email-link-tracking/

27. **Postmark: Why Emails Go to Spam**.
    https://postmarkapp.com/guides/why-emails-go-to-spam

28. **Postmark: Plain-Text Emails**.
    https://postmarkapp.com/guides/plain-text-vs-html-emails

29. **Postmark: Bounce Handling**.
    https://postmarkapp.com/developer/api/bounce-api

30. **Postmark: URL Shorteners and Deliverability**.
    https://postmarkapp.com/blog/url-shorteners-hurt-email-deliverability

### Content / Design

31. **Litmus: HTML Email Best Practices**.
    https://www.litmus.com/blog/best-practices-for-html-email/

32. **Litmus: Email Tracking Pixels**.
    https://www.litmus.com/blog/email-tracking-pixel/

33. **Litmus: Email Subject Line Best Practices**.
    https://www.litmus.com/blog/subject-line-best-practices/

34. **Campaign Monitor: Image-to-Text Ratio and Spam Filters**.
    https://www.campaignmonitor.com/resources/guides/image-spam/

35. **HubSpot: 394 Spam Trigger Words to Avoid**.
    https://blog.hubspot.com/marketing/words-that-make-your-email-spammy

36. **Mailchimp: About Spam Filters**.
    https://mailchimp.com/help/about-spam-filters/

### Spam Filter / Blocklist Tools

37. **Apache SpamAssassin Rules Documentation**.
    https://spamassassin.apache.org/full/3.4.x/doc/

38. **SURBL: Usage Documentation**.
    https://www.surbl.org/usage

39. **Spamhaus DBL (Domain Block List)**.
    https://www.spamhaus.org/dbl/

### Emerging Standards

40. **BIMI Group Specification**.
    https://bimigroup.org/specification/

41. **Apple Mail Privacy Protection**.
    https://support.apple.com/en-us/HT212850

---

## TODOs

- [ ] **BIMI deployment walkthrough**: Document end-to-end steps for obtaining a Verified Mark Certificate (VMC) and configuring BIMI DNS records once the domain reaches `p=reject`. Include supported client matrix (Gmail, Apple Mail, Yahoo, Fastmail).

- [ ] **MTA-STS + TLS-RPT setup guide**: Detailed configuration steps for the policy file, DNS record, and interpretation of TLS reporting JSON. Cover the `testing` vs `enforce` mode rollout.

- [ ] **DKIM ed25519 dual-signing**: Document how to publish both RSA-2048 and ed25519 key records simultaneously for backward/forward compatibility, and how to configure dual signing in common MTAs (Postfix, Exim, Haraka).

- [ ] **ESP-specific authentication passthrough**: Investigate and document how DKIM alignment works when sending via third-party ESPs (SendGrid, Mailjet, Postmark) with custom return-path and from-domain alignment. Cover authenticated domain vs sub-user domain scenarios.

- [ ] **IPv6 sending considerations**: SPF `ip6` mechanism usage, PTR record requirements for IPv6 sending addresses, and ISP IPv6 reputation behaviour (many ISPs distrust IPv6 senders by default).

- [ ] **Suppression list architecture**: Recommend a concrete schema and API surface for a suppression service (hard bounce, FBL complaint, unsubscribe, manual suppress) that can be queried pre-send and updated via webhook.

- [ ] **Spam score benchmarking**: Run representative transactional templates through SpamAssassin locally (`spamassassin -t < message.eml`) and document baseline scores and any rules that fire, with remediation steps.

- [ ] **Warm-up automation**: Evaluate tooling (Mailwarm, Warmup Inbox, GlockApps Warmup) for automated IP warm-up and ongoing engagement seeding; document trade-offs for transactional vs marketing IP pools.

- [ ] **GDPR / CASL compliance layer**: Document opt-in consent record requirements, data subject access/erasure impact on suppression lists, and jurisdictional differences between CAN-SPAM, GDPR, and CASL for transactional email.

- [ ] **Deliverability monitoring stack**: Specify a recommended observability setup — which metrics to track (delivery rate, spam rate, bounce rate, DMARC pass rate, Postmaster Tools domain reputation), alert thresholds, and which tools to integrate.

- [ ] **DMARCbis tracking**: The IETF is working on an updated DMARC specification (draft-ietf-dmarc-dmarcbis). Monitor for publication and update authentication section accordingly.

COMPLETE
