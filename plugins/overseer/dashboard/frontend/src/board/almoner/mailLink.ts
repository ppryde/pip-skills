/**
 * Deep links into Gmail for a mail-sourced row.
 *
 * The useful discovery: this needs nothing but the RFC 822 `Message-ID`
 * header, which every IMAP fetch already returns. So the `via: imap` adapter
 * can link out without the Gmail API and without asking for another scope.
 *
 * CAVEAT, and it is a real one: this is a SEARCH url, not a direct link to
 * the message. Gmail's own opaque web id is wrapped with a per-account server
 * key, cannot be derived offline, and is not returned by the API — so a
 * durable direct link is simply not available to us. The reader lands on a
 * search page holding exactly one result. Good enough to act on; not the same
 * thing as opening the message, and worth not pretending otherwise.
 *
 * On a phone the Gmail app claims `mail.google.com` links, so the same URL
 * opens the app rather than the browser. One link covers both.
 */

const GMAIL = "https://mail.google.com/mail";

/**
 * A Gmail link that finds one message by its `Message-ID`.
 *
 * `account` is the mailbox to open it in. Gmail's `/u/<n>/` form indexes
 * accounts by signed-in ORDER, which is unstable and differs per device — an
 * unusable thing to bake into a stored link. Passing the address instead lets
 * Gmail resolve the right mailbox itself, which matters here because the
 * design has always assumed more than one (a work source and a personal one).
 * Falls back to `/u/0/` when no address is known.
 *
 * Returns "" when there is no message id, so a caller renders no link rather
 * than a link that searches for nothing.
 */
export function gmailLink(messageId: string | undefined, account?: string): string {
  if (!messageId) return "";
  // Message-IDs are conventionally wrapped in angle brackets in the header;
  // Gmail's search wants the bare id.
  const bare = messageId.trim().replace(/^<|>$/g, "");
  if (bare === "") return "";
  const mailbox = account ? encodeURIComponent(account) : "0";
  return `${GMAIL}/u/${mailbox}/#search/rfc822msgid:${encodeURIComponent(bare)}`;
}
