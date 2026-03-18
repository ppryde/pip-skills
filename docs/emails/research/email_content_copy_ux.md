# Email Content, Copy & UX Patterns

Practical reference for engineers and product teams building transactional and marketing email systems.
Based on published research from Litmus, Campaign Monitor, Mailchimp, Nielsen Norman Group, and Email on Acid.

Last verified: March 2026. Live source checks performed at this date; see Sources section for URL status notes.

---

## Subject/Preheader Patterns

### Character Limits

- **Subject line**: Keep to **40–50 characters** for reliable display in mobile preview panes — most mobile clients truncate at 33–41 characters depending on screen width and OS. Desktop clients show more: up to 60–70 characters is legible in Gmail and Apple Mail on desktop. The 40–50 character range is the safest cross-client target. Subjects under 20 characters and over 70 characters both underperform mid-range on average (Campaign Monitor benchmark data, 2023).
- **Preheader text**: Keep to **under 90 characters** as a safe universal limit. Display length varies dramatically by client and by user-configured preview settings: a subscriber can see anywhere from 0 lines of preview text to approximately 278 characters (5 lines), so there is no single correct length. Gmail (which calls this field "Snippets") adjusts the preheader width inversely to subject line length — a shorter subject line leaves more room for preheader. The practical floor is around 40–50 characters; below that you risk the client pulling fallback body text. Target 85–100 characters of combined subject + preheader for Gmail mobile specifically, which renders approximately 100 combined characters (Litmus, *The Ultimate Guide to Email Preheader Text*, 2022; verified March 2026 — under 90 char guidance confirmed live).
- If no preheader is explicitly set, mail clients pull the first visible text content from the email body — often a navigation link or "View in browser" notice. This wastes the highest-value real estate in the inbox.
- Avoid redundancy: the preheader should extend or complement the subject line, never repeat it.

### Personalisation

- Emails with personalised subject lines (first name, company, purchase reference) have **26% higher unique open rates** than non-personalised equivalents (Campaign Monitor, 2022).
- Personalisation beyond first name — referencing a specific product purchased or a city — performs better than name-only tokens, but requires clean data. A malformed merge tag (e.g. "Hi [FIRST_NAME],") is worse than no personalisation at all (Mailchimp, *Email Marketing Benchmarks*, 2023).
- For transactional emails, including an order or reference number in the subject line aids recall and reduces "did my order go through?" support tickets.

### Emoji

- Emoji in subject lines can **increase open rates by ~56%** in some segments, but this is audience- and context-dependent (Mailchimp internal study cited in Campaign Monitor, 2022). B2B audiences often respond negatively.
- Emoji render inconsistently across clients: a thumbs-up on Apple Mail renders differently on Outlook for Windows. Test using Email on Acid or Litmus Checkers before shipping.
- Never lead with an emoji if the subject line loses all meaning when the emoji is stripped — some enterprise mail gateways strip non-ASCII characters entirely.
- One emoji per subject line is the observed sweet spot. Multiple emoji dilute attention and read as spam to both algorithms and humans.

### Power Words & Psychological Triggers

- **Urgency words** ("today only", "expires", "last chance") increase clicks but erode trust if overused. Reserve for genuinely time-sensitive communications (Litmus, *Email Marketing ROI Study*, 2023).
- **Exclusivity** ("for members only", "you're invited") outperforms generic promotional language in B2C retail (Campaign Monitor, 2023).
- **Curiosity gaps** ("You won't believe what's in your cart") boost opens but increase unsubscribes if the email body does not deliver on the promise — a practice known as "bait and switch" (Nielsen Norman Group, *Email Newsletter Usability*, 2nd edition).
- **Numbers and specificity** ("Save £47 today" vs "Save money today") improve click-through rates. Specific figures are more credible than vague claims (Mailchimp research, 2022).
- Avoid spam trigger words in subjects: "Free!!!", "WINNER", "Click here", excessive ALL CAPS. These harm deliverability as well as open rates.

### A/B Test Findings (Published)

- **Question vs statement subjects**: Question format ("Ready for summer?") performs 10–14% better for lifestyle brands; statement format outperforms for transactional and B2B contexts (Litmus, 2022).
- **Sender name matters more than subject line** for list health: 68% of recipients decide whether to open based on the "From" name alone (Litmus, *State of Email*, 2023 — report now gated behind sign-up; figure widely cited in industry). A trusted sender name makes subject line optimisation more impactful.
- Testing cadence: run A/B tests for at least 4 hours before declaring a winner on open rate, 24 hours for click rate. Premature winner selection inflates false positives (Mailchimp, *A/B Testing Guide*, 2022).

---

## Body Structure & UX

### F-Pattern Reading

- Eye-tracking research shows that on-screen readers follow an F-shaped pattern: they read fully across the first line or two, then scan down the left margin, with progressively shorter horizontal reads (Nielsen Norman Group, *F-Shaped Pattern for Reading Web Content*, Pernice 2017).
- In email this means: **critical information must appear in the first sentence of each paragraph**. Readers will not excavate buried lede copy.
- Left-aligned text (not justified) reinforces the F-pattern by keeping the left edge clean for scanning. Centred body copy is harder to scan for anything over a few words.
- Place the single most important fact or action in the **first 200–300 pixels** of the email body, below any logo/header. This is visible above the fold on most mobile previews without scrolling.

### Visual Hierarchy

- Establish a clear H1 → body → CTA hierarchy. Use font size differentials of at least 4–6pt between heading and body to create visible contrast (Email on Acid, *Email Typography Guide*, 2022).
- Limit font families to **two maximum**: one for headings, one for body. Web-safe fallback stacks are mandatory because custom fonts fail silently in Outlook, Gmail app on Android, and others.
- Use **bold** to highlight key terms within body text, not italics. Italics reduce readability at small sizes and render poorly on low-DPI screens.
- Colour contrast for body text: minimum **4.5:1 ratio** against background per WCAG 2.1 AA. Use a tool like WebAIM Contrast Checker. Dark grey (#333333) on white outperforms pure black (#000000) for extended reading (Litmus accessibility guidance, 2023).

### Whitespace

- **Line height**: 1.4–1.6× font size for body text. The CSS property `line-height: 1.5` on `<p>` tags is a reliable baseline (Email on Acid, 2022).
- Paragraph spacing: a visual gap between paragraphs (margin-bottom: 16px minimum) is more scannable than relying on line breaks alone.
- Generous whitespace signals confidence and professionalism; dense, wall-of-text emails read as low-effort and increase the chance the reader abandons before the CTA (Nielsen Norman Group, *Legibility, Readability, and Comprehension*, 2020).
- Single-column layouts work best for mobile. Two-column layouts can work on desktop but require media query reflow. Three columns in email are almost always a mistake — they collapse to narrow widths on mobile without careful CSS.

### Paragraph Length

- **Maximum 3–4 sentences per paragraph** in email body copy. Email is a low-attention-span medium; long paragraphs are read less thoroughly than the same content broken into shorter chunks (Nielsen Norman Group, *How Little Do Users Read?*, 2008 — confirmed in 2020 email-specific studies).
- Inverted pyramid structure: most important → supporting detail → background context. Do not build to a reveal — state the main point first.
- Reading level: aim for **Grade 7–9 Flesch-Kincaid** for consumer email. Simpler language correlates with higher engagement even among professional audiences (Mailchimp, *Email Content and Readability*, 2021).

---

## CTA Patterns

### Button Copy

- **Verb-first copy** outperforms noun-first: "Download the report" beats "Report download". The first word sets intent (Campaign Monitor CTA copy guide, 2022).
- **First-person copy** ("Get my guide", "Start my trial") outperforms second-person ("Get your guide") in multiple published A/B tests, by 7–14% CTR uplift (Unbounce, *Conversion Benchmark Report* 2022; referenced in Litmus 2023 content).
- Button copy should be **2–5 words**. Single words ("Submit", "Go") are too vague; full sentences reduce scannability.
- Avoid "Click here" — it is accessibility-hostile (screen readers announce it without context) and performs poorly compared to descriptive alternatives (WebAIM, *Links and Hypertext*, 2023).
- Reinforce value in the button: "Claim my 20% discount" > "Continue to checkout". The button copy should restate the benefit, not the mechanism.

### Placement

- **Above the fold**: include at least one CTA visible without scrolling. On mobile this is roughly the first 500–600px of rendered height (Litmus, *Email Design Reference*, 2023).
- For longer emails (newsletters, product announcements), repeat the primary CTA at the bottom. This serves readers who scan to the end before acting. The two CTAs should be identical in copy and destination URL.
- Avoid placing CTAs immediately after the opening sentence — readers need minimal context to understand why they should act. Aim for CTA placement after the value proposition has been stated (1–3 short paragraphs in).

### Single vs Multiple CTAs

- **Single primary CTA** has a higher click-through rate per email send. Every additional CTA reduces the probability of any CTA being clicked — a manifestation of Hick's Law (the time to make a decision increases with the number of choices) (Campaign Monitor, *The Best Email CTA Strategies*, 2022).
- When multiple CTAs are unavoidable (e.g. a weekly digest with multiple articles), use **visual hierarchy** to establish a primary action: larger button, stronger colour, more whitespace around it. Secondary links should be text links, not buttons.
- Mixed-purpose emails (e.g. invoice + upsell) should keep the transactional CTA as the dominant visual element and demote the marketing CTA to smaller text below. Reversing this priority erodes trust (Litmus, *Transactional Email Best Practices*, 2023).
- Never use two buttons of equal visual weight side-by-side. Cognitive load increases and conversion rate for both drops.

### Button Design

- Minimum button dimensions: **44px height**, **120px minimum width** (see Mobile UX section). Use CSS padding rather than a fixed height so text scales correctly across clients.
- Use bulletproof HTML buttons (VML/CSS hybrid) rather than image-based buttons. Image-based buttons disappear when images are blocked; approximately 43% of email recipients have images blocked by default in some clients (Litmus, *Email Client Market Share*, 2023).
- Button colour should contrast with the email background by at least 3:1 (WCAG AA for UI components). Test in greyscale to verify contrast without colour dependency.

---

## Mobile UX

### Tap Target Size

- Apple Human Interface Guidelines specify a minimum tap target of **44×44pt** (logical pixels). Google Material Design specifies **48×48dp**. Apply the more conservative Apple minimum for email buttons as a safe cross-platform floor.
- Tap targets below 44px in any dimension result in increased mis-taps and frustration, particularly for users over 40 or those using their phone one-handed (Nielsen Norman Group, *Touch Target Sizes*, 2019).
- Ensure adequate **spacing between tap targets**: at least 8px between adjacent links/buttons to prevent mis-taps on dense link lists (e.g. navigation headers, footer link rows).

### Font Size Minimums

- **Body text**: 14px minimum; 16px preferred. iOS auto-inflates text smaller than 13px, which can break single-column layouts (Email on Acid, *Mobile Email Rendering Guide*, 2022).
- **Heading text**: 18–22px for H1, 16–18px for H2. This maintains hierarchy at 14px body.
- Set font sizes in **px, not pt** for email CSS. Points render inconsistently across clients. Avoid em/rem for top-level email container font sizes — em cascades unexpectedly across nested tables in older clients.
- Never rely solely on font colour to convey importance on mobile: colour rendering varies across OLED and LCD screens, and approximately 8% of men have colour vision deficiency (Colour Blind Awareness, cited in Email on Acid accessibility guide, 2023).

### Thumb Zones

- On a standard smartphone held in one hand, the **comfortable thumb zone** occupies the lower-centre portion of the screen. The top corners and far edges are stretch zones requiring a grip shift (Hoober, *How Do Users Really Hold Mobile Devices?*, UXmatters 2013 — repeatedly cited as foundational in mobile UX literature including Litmus 2022 mobile guide).
- Primary CTAs should not be anchored to the top of the email (outside sticky headers). For short emails, placing the CTA in the lower third of the email body lands it naturally in the thumb zone as the reader finishes reading.
- Footer links (unsubscribe, legal, preferences) are deliberately placed in the difficult-to-reach top-corner zone by some senders to reduce unsubscribes. This is a **dark pattern** that violates CAN-SPAM/GDPR requirements for easy unsubscribe access and is increasingly flagged by Gmail's spam classifier (Google, *Gmail Postmaster Tools documentation*, 2023).

### Single-Column Layouts

- Single-column layouts at **560–600px max-width** are the most reliable pattern for mixed-client rendering. On mobile the layout scales down gracefully; on desktop it reads as a contained, intentional design (Campaign Monitor, *HTML Email Design Fundamentals*, 2022).
- Use `width: 100%; max-width: 600px` on the outer container. Fixed 600px tables clip on screens narrower than 600px (some Android devices, older iPhones with large text size settings).
- Multi-column layouts require robust media queries to reflow to single-column on mobile. Two columns can work for structured content (e.g. product grids) but must be tested across clients. Three columns are almost always a mistake without careful CSS.
- Images should use `max-width: 100%` and be hosted on a reliable CDN — never email-attached — so they scale correctly and do not hit attachment size limits.

### Dark Mode

- Over **35% of email opens** occur in a dark mode environment (Litmus, *Dark Mode Statistics*, 2023). Test dark mode rendering via Email on Acid or Litmus.
- Use the `@media (prefers-color-scheme: dark)` media query to invert backgrounds and adjust text colours. Clients that support it: Apple Mail, iOS Mail, Outlook 2019+, Samsung Mail.
- Avoid pure-white logos on transparent backgrounds — they disappear in dark mode. Provide a version with a dark background or use the `mix-blend-mode` CSS trick (supported in limited clients).
- Transparent PNG images over coloured background cells are dangerous in dark mode: the cell background colour inverts but the transparent PNG area inherits the new inverted background unexpectedly.

---

## Transactional vs Marketing

### Tone

- **Transactional emails** (order confirmations, password resets, shipping notifications, invoices) should be **direct, factual, and minimal**. The reader opened it for information, not an experience. Over-designed transactional emails feel intrusive and erode trust (Litmus, *Transactional Email Best Practices*, 2023).
- **Marketing emails** have licence to be expressive, brand-forward, and persuasive. However, even marketing emails benefit from front-loading value — recipients scan for "what's in it for me" in the first 3 seconds (Nielsen Norman Group, *Email Newsletter Usability*, 2nd edition).
- Avoid injecting marketing tone into transactional emails. "Your password was reset. WHILE YOU'RE HERE, check out our SALE!" treats an anxious security moment as a sales opportunity, erodes trust, and can cause users to doubt the email's legitimacy.

### Urgency

- In transactional email, urgency should be factual: "Your reservation expires in 24 hours" (if true). Manufactured urgency in transactional contexts ("Act fast!") feels out of place and reads as unprofessional.
- In marketing email, urgency must be genuine or clearly framed as promotional convention. Countdown timers to artificial deadlines are considered a dark pattern by GDPR-focused regulators in the UK and EU (ICO, *Direct Marketing Guidance*, 2020).
- Password reset emails benefit from stating a genuine expiry time: "This link expires in 60 minutes." This is security information, not urgency marketing (OWASP, *Forgot Password Cheat Sheet*, 2023).

### Trust Signals

- **Transactional**: include the company legal name or trading name, a support contact (email or phone), and a reference number. These are the primary trust signals — they allow the recipient to verify the email is legitimate (Litmus, *Transactional Email Best Practices*, 2023).
- For transactional emails involving payment, include partial card/account details (last 4 digits) to help recipients identify the associated account. Never include full card numbers.
- **Marketing**: trust signals include unsubscribe links (required legally), physical mailing address (required by CAN-SPAM), sender name consistency, and social proof (review counts, user statistics).
- Domain alignment matters for both types: the sending domain should match the brand domain visually and via DMARC/DKIM records. Misaligned domains (e.g. sending from `notifications.brand-emails.com` without brand context) increase spam classification and reduce recipient trust.

### Legal Requirements

**CAN-SPAM (US)**
- Marketing emails require: a clear sender identification, a non-deceptive subject line, a physical postal address, and a working opt-out mechanism honoured within 10 business days.
- Transactional emails are **exempt** from CAN-SPAM opt-out requirements if they contain primarily transactional content. Mixing marketing content into a transactional email can reclassify it under CAN-SPAM and impose all marketing obligations (FTC, *CAN-SPAM Act: A Compliance Guide*, 2009, updated 2021).

**GDPR/UK GDPR (EU/UK)**
- Marketing emails require a **lawful basis** — typically explicit consent (opt-in). Soft opt-in applies for existing customers being marketed similar products/services (ICO, *Email Marketing Guidance*, 2022).
- Transactional emails are sent under the **contractual necessity** or **legitimate interests** lawful basis and do not require marketing consent.
- Unsubscribe links must be functional and honoured promptly (ICO guidance recommends within 10 days in practice).
- Privacy notice must be accessible from the email (footer link is standard).

**CASL (Canada)**
- More stringent than CAN-SPAM: requires **express or implied consent** for commercial electronic messages.
- Transactional messages (receipts, password resets, account notifications) are exempt as "non-commercial" under CASL.
- Implied consent (e.g. from a recent business relationship) expires after **2 years**. Systems should track consent date and suppress lapsed contacts (CRTC, *CASL Compliance Guidance*, 2014, updated 2021).

### Content Density

- Transactional emails: keep to **one purpose per email**. An order confirmation confirms the order. A shipping notification confirms shipping. Combining them with upsell content increases cognitive load at a moment when the user's primary need is task confirmation.
- Marketing emails: newsletters and digests can have multiple items, but each item should have a single clear link. The primary content block should receive at least 60% of visual weight.

---

## Content Checklist

Use this checklist before shipping any email template.

### Subject & Preheader
- [ ] Subject line is 40–50 characters (mobile-safe); extended to 60 characters maximum for desktop-primary sends
- [ ] Preheader is explicitly set, under 90 characters, and extends (not repeats) the subject
- [ ] No spam trigger words in subject line
- [ ] Merge tags tested with fallback values (no `[FIRST_NAME]` in production)
- [ ] Emoji tested across target clients if used

### Body Copy
- [ ] Opening sentence states the primary purpose of the email
- [ ] Paragraphs are 3–4 sentences maximum
- [ ] Font size is 14px minimum for body, 18px minimum for headings
- [ ] Line height is at least 1.4
- [ ] Text is left-aligned (not justified)
- [ ] Critical information appears above the fold on mobile

### CTA
- [ ] Primary CTA uses verb-first, first-person copy (where appropriate)
- [ ] Button is at least 44px tall with CSS padding (not fixed height image)
- [ ] Button is a bulletproof HTML button, not an image
- [ ] Button colour passes 3:1 contrast ratio against background
- [ ] CTA copy is 2–5 words
- [ ] Only one primary CTA per email (secondary CTAs are text links)

### Mobile
- [ ] Template uses single-column layout at max 600px width
- [ ] Tested in iOS Mail and Gmail Android (minimum)
- [ ] Dark mode rendering tested
- [ ] All tap targets are at least 44×44px with 8px spacing between adjacent links
- [ ] Images have `max-width: 100%` and `alt` text

### Transactional-Specific
- [ ] Email contains a reference number or identifier
- [ ] Support contact is visible
- [ ] Expiry times stated where relevant (password resets, offers embedded in receipts)
- [ ] No disproportionate marketing content in a transactional email
- [ ] Sending domain is aligned with brand domain and DMARC-authenticated

### Marketing-Specific
- [ ] Unsubscribe link is present and functional
- [ ] Physical mailing address is in the footer (CAN-SPAM)
- [ ] Consent basis documented in sending platform
- [ ] Subject line is not deceptive

### Accessibility
- [ ] All images have descriptive `alt` text (or `alt=""` for purely decorative images)
- [ ] Colour is not the sole means of conveying information
- [ ] Text-to-background contrast meets WCAG 2.1 AA (4.5:1 for body, 3:1 for large text)
- [ ] Reading order in source HTML matches visual order
- [ ] Link text is descriptive (no "click here")

---

## Sources

1. **Campaign Monitor** — *Email Marketing Benchmarks* (2022, 2023): subject line character length, personalisation open rate uplift, single vs multiple CTAs, single-column layouts. https://www.campaignmonitor.com/resources/guides/email-marketing-benchmarks/

2. **Litmus** — *State of Email* (2022, 2023): sender name trust data, dark mode statistics, email client market share, transactional email best practices, bulletproof buttons. https://www.litmus.com/resources/state-of-email/ *(Report is now gated behind an email sign-up form as of March 2026. Statistics cited here are from the 2022/2023 editions.)*

3. **Litmus** — *The Ultimate Guide to Email Preheader Text* (2022): preheader character guidance confirmed live March 2026 — under-90-character universal limit validated, per-client variability documented. https://www.litmus.com/blog/the-ultimate-guide-to-preview-text-support/

4. **Litmus** — *Email Client Market Share*: https://www.litmus.com/email-client-market-share/ *(Note: emailclientmarketshare.com now redirects here. Page is JavaScript-rendered; data requires browser access.)*

5. **Mailchimp** — *Email Marketing Benchmarks and Statistics* (2022, 2023): personalisation data, reading level guidance, A/B testing methodology. https://mailchimp.com/resources/email-marketing-benchmarks/

6. **Nielsen Norman Group** — *F-Shaped Pattern for Reading Web Content* (Pernice, 2017). https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content-discovered/

7. **Nielsen Norman Group** — *Email Newsletter Usability* (2nd edition, 2006; findings repeatedly validated through 2020). https://www.nngroup.com/reports/email-newsletter-usability/

8. **Nielsen Norman Group** — *Touch Target Sizes* (2019). https://www.nngroup.com/articles/touch-target-size/

9. **Nielsen Norman Group** — *Legibility, Readability, and Comprehension* (2020). https://www.nngroup.com/articles/legibility-readability-comprehension/

10. **Email on Acid** — *Mobile Email Rendering Guide* (2022): iOS font inflation, font size minimums, dark mode rendering. https://www.emailonacid.com/blog/article/email-development/mobile-email-rendering/

11. **Email on Acid** — *Email Typography Guide* (2022): font hierarchy, line height, web-safe fonts. https://www.emailonacid.com/blog/article/email-development/email-fonts/

12. **Email on Acid** — *Accessibility in Email* (2023): colour contrast, alt text, WCAG compliance. https://www.emailonacid.com/blog/article/email-development/accessibility-in-email/

13. **Hoober, Steven** — *How Do Users Really Hold Mobile Devices?* (UXmatters, 2013): thumb zone research foundational reference. https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php

14. **Apple** — *Human Interface Guidelines: Layout* (current): 44×44pt minimum tap target. https://developer.apple.com/design/human-interface-guidelines/layout *(Page requires JavaScript to render; guideline is a long-standing stable standard.)*

15. **Google Material Design** — *Accessibility: Touch targets* (current): 48×48dp minimum tap target. https://m3.material.io/foundations/accessible-design/overview *(Previous URL at /accessibility-basics returns 404 as of March 2026.)*

16. **FTC** — *CAN-SPAM Act: A Compliance Guide for Business* (2009, updated 2021). https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business

17. **ICO (UK)** — *Direct Marketing Guidance* (2020); *Email Marketing Guidance* (2022). https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/

18. **CRTC** — *CASL Compliance and Enforcement* (2014, updated 2021). https://crtc.gc.ca/eng/internet/anti.htm

19. **OWASP** — *Forgot Password Cheat Sheet* (2023): password reset expiry security guidance. https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html

20. **WebAIM** — *Links and Hypertext* (2023): descriptive link text, "click here" anti-pattern. https://webaim.org/techniques/hypertext/

21. **Unbounce** — *Conversion Benchmark Report* (2022): first-person vs second-person CTA copy A/B test data. https://unbounce.com/conversion-benchmark-report/

22. **Google** — *Gmail Postmaster Tools Documentation* (2023): spam classifier signals, unsubscribe dark patterns. https://postmaster.google.com/

23. **Colour Blind Awareness** — prevalence statistics (8% of men): https://www.colourblindawareness.org/colour-blindness/

---

## TODOs

- [ ] **Validate dark mode CSS patterns** against current Email on Acid client support matrix — dark mode support across Outlook versions is fragmented and changes with Office updates.
- [ ] **Add image-blocking statistics by industry vertical** — the 43% figure from Litmus is an aggregate; B2B senders typically see higher image-blocking rates than B2C.
- [ ] **Expand CASL section** with implied vs express consent decision tree for product teams building onboarding flows.
- [ ] **Add AMP for Email section** — AMP email allows interactive components (forms, carousels) inline. Supported by Gmail, Yahoo Mail, and Mail.ru. Requires separate AMP MIME part. Growing relevance for transactional flows (e.g. inline survey, one-click action).
- [ ] **Benchmark data by email type** — open/click benchmarks differ significantly between welcome series, cart abandonment, weekly digest, and transactional confirmation. Source per-type benchmarks from Klaviyo or Iterable 2025/2026 data.
- [ ] **Add plain-text version guidance** — all emails should include a `text/plain` MIME part. Plain-text version content strategy is under-documented and worth a dedicated section.
- [ ] **Internationalisation considerations** — RTL language support (Arabic, Hebrew) in email requires `dir="rtl"` on the HTML element and reversal of F-pattern assumptions. Expand when building for multilingual sends.
- [ ] **Refresh Litmus market share data** — emailclientmarketshare.com now redirects to litmus.com/email-client-market-share/ but the page is JavaScript-rendered and inaccessible to automated fetching. Retrieve mobile vs desktop split manually via a browser to update the mobile UX section with current figures.
- [ ] **Verify Apple HIG and Material Design URLs** — both pages require JavaScript to render and could not be confirmed live in March 2026. Spot-check manually before citing in external documentation.
- [ ] **Legal review flag** — CAN-SPAM, GDPR, and CASL notes above are based on published guidance as of early 2026. Have legal counsel confirm applicability before shipping to regulated industries (financial services, healthcare).

COMPLETE
