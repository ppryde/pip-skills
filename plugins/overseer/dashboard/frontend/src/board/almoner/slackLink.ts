/**
 * Deep links into the Slack desktop app for a Slack-sourced row.
 *
 * A stored `url` here is a Slack web permalink
 * (`https://<team>.slack.com/archives/<channel>[/p<ts>]`), because that is
 * what the Slack API and web UI hand back. `slack://` is Slack's own scheme
 * for opening the same target in the installed app instead of a browser tab.
 *
 * ALLOWLIST-PARSE, NEVER STRING-SUBSTITUTE. Digest content is built from
 * messages written by other people; a crafted `url` reaching an `href` is
 * the real attack surface here, not a cosmetic detail. `url` is parsed with
 * `new URL(...)` and checked against a strict scheme/host/path allowlist —
 * `https:`, a single `<workspace>.slack.com` label, and exactly
 * `/archives/<ID>` or `/archives/<ID>/p<digits>` — before anything is read
 * out of it. Anything else, including a host that merely CONTAINS
 * `slack.com` (`evil-slack.com.attacker.net`) or a path with extra segments,
 * returns `""`. Every component emitted into the result is passed through
 * `encodeURIComponent`.
 *
 * CAVEAT, and it is a real one: a `slack://` click is silent when the Slack
 * app is not installed — no error, no fallback, nothing happens. That is
 * why the UI always renders the ordinary https permalink beside this one,
 * never in place of it.
 *
 * Team: Slack's own docs mark `team=<T>` as REQUIRED on this scheme. We omit
 * it unless the caller supplies one, relying on the desktop client to fall
 * back to the active workspace — that fallback is UNVERIFIED, just the best
 * available behaviour without a team id in hand. The eventual Slack adapter
 * will carry the team id on the source record (`AlmonerSource`), which the
 * backend passes through untouched to here.
 */

const HOST = /^[a-z0-9-]+\.slack\.com$/;
const PATH = /^\/archives\/([A-Z0-9]+)(?:\/p(\d+))?$/;
const TEAM = /^T[A-Z0-9]+$/;

/**
 * Builds a `slack://channel` deep link from a Slack web permalink, or `""`
 * when `url` is missing, empty, or does not match the allowlisted shape.
 */
export function slackLink(url: string | undefined, opts?: { team?: string }): string {
  if (!url) return "";

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "";
  }
  if (parsed.protocol !== "https:") return "";
  if (!HOST.test(parsed.hostname)) return "";

  const match = PATH.exec(parsed.pathname);
  if (!match) return "";
  const [, pathId, digits] = match;

  // Slack permalinks for a thread reply sometimes carry the channel in
  // `?cid=` rather than the path; the path id here is required by `PATH`
  // above, so this only matters if that ever loosens. Never synthesise a
  // channel id that wasn't in the url.
  const channelId = pathId || parsed.searchParams.get("cid");
  if (!channelId) return "";

  const parts = [`id=${encodeURIComponent(channelId)}`];

  if (digits) {
    // Slack message timestamps are `<seconds>.<micros>` — the permalink's
    // `p<digits>` is that same number with the dot removed. The micros are
    // always the last six digits; do NOT assume 16 digits total (a shorter
    // epoch still splits the same way).
    const seconds = digits.slice(0, -6);
    const micros = digits.slice(-6);
    parts.push(`message=${encodeURIComponent(`${seconds}.${micros}`)}`);
  }

  const threadTs = parsed.searchParams.get("thread_ts");
  if (threadTs) parts.push(`thread_ts=${encodeURIComponent(threadTs)}`);

  if (opts?.team && TEAM.test(opts.team)) {
    parts.push(`team=${encodeURIComponent(opts.team)}`);
  }

  return `slack://channel?${parts.join("&")}`;
}
