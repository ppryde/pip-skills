import type { AlmonerDigest } from "../../api/types";

/** Fixture timestamps are RELATIVE, computed at import.
 *
 * A fixture pinned to fixed dates ages into nonsense — within a week the
 * sample day sits under a heading naming a date last month, and the day band
 * has nothing to draw because none of it is "today" any more. Offsets keep
 * the demo showing a live-looking day forever. */
const ago = (hours: number): string =>
  new Date(Date.now() - hours * 3_600_000).toISOString();

/**
 * A sample digest, reachable at `#almoner?demo=1` and used by the page's
 * tests.
 *
 * It exists because the page ships before the almoner CLI does: without it
 * the route returns `{items: []}` and there is nothing to look at or judge.
 * The page labels it loudly as sample data — an unlabelled fixture that
 * looks like real inflow is the one way this could actively mislead.
 *
 * ## Drawn from real inflow, but INVENTED
 *
 * The shapes, the mix and above all the RATIO come from an actual scan of a
 * Slack workspace and a personal mailbox. Every name, message, link and
 * number here is made up, and must stay made up: this repo is PUBLIC and
 * this file ships, so a real colleague, order number or message body
 * committed here is published to the world.
 *
 * What that scan showed, and what this fixture therefore encodes:
 *
 *  - **Machine mail is the overwhelming majority, and it is not all junk.**
 *    Twenty threads across four days contained exactly two written by a
 *    human; the rest were delivery updates, job alerts, security notices and
 *    newsletters. Dropping those silently loses real information ("did it
 *    ship?"); listing them individually drowns the two that matter. So each
 *    KIND folds into one `bundled` row that expands like any conversation,
 *    and only genuine junk is counted in `suppressed`.
 *  - **Most asks are already closed.** One of those two humans had already
 *    been answered — the last-speaker rule settles mail exactly as it settles
 *    Slack. So a settled row is the majority case, not an edge case.
 *  - **A burst is one thing, not five.** A run of messages inside a minute
 *    collapses to a single row that discloses the collapse.
 *  - **One event can arrive twice.** Issue trackers email you as well.
 *  - **A weekend is legitimately empty.** The Slack scan returned nothing at
 *    all on a Saturday, which is a real answer and not a failure.
 */
export const SAMPLE_DIGEST: AlmonerDigest = {
  fetched_at: null,
  ranked: false,
  suppressed: 4,
  sources: [
    { label: "slack", type: "slack", via: "agent", ok: true },
    { label: "linear", type: "linear", via: "api", ok: true },
    { label: "personal", type: "mail", via: "imap", ok: true },
    { label: "work", type: "mail", via: "imap", ok: false, error: "not configured" },
    { label: "notion", type: "notion", via: "api", ok: true },
  ],
  items: [
    {
      id: "slack:GDM-demo-1",
      source: "slack",
      context: "work",
      title: "Group DM · Rhona, Tomas",
      who: "Rhona Baird",
      excerpt: "Could we pull Priya into the pilot as well? Smaller book, but she gives good feedback.",
      count: 5,
      arrived: ago(2),
      awaiting: true,
      asks: "reply",
      url: "https://example.slack.com/archives/G01EXAMPLE",
      seen_in: ["slack"],
      // One thought, sent as five messages inside a minute. The row collapses
      // them; expanding shows what was said, each with its own permalink so a
      // reply can start from the right message.
      messages: [
        {
          who: "Rhona Baird",
          text: "Early feedback on the pilot is really positive by the way",
          at: ago(3.2),
          url: "https://example.slack.com/archives/G01EXAMPLE/p000000000000100",
        },
        {
          who: "Rhona Baird",
          text: "A couple of the alerts are noisy — mostly accounts that are already capped",
          at: ago(2.05),
          url: "https://example.slack.com/archives/G01EXAMPLE/p000000000000200",
        },
        {
          who: "Rhona Baird",
          text: "No need to apologise, it helps us find the edges",
          at: ago(2.03),
          url: "https://example.slack.com/archives/G01EXAMPLE/p000000000000300",
        },
        {
          who: "Rhona Baird",
          text: "But it looks great — thanks for turning it round so quickly",
          at: ago(2.01),
          url: "https://example.slack.com/archives/G01EXAMPLE/p000000000000400",
        },
        {
          who: "Rhona Baird",
          text: "Could we pull Priya into the pilot as well? Smaller book, but she gives good feedback.",
          at: ago(2),
          url: "https://example.slack.com/archives/G01EXAMPLE/p000000000000500",
        },
      ],
    },
    {
      // A page someone left a comment on. Notion's grain is the PAGE, not the
      // comment — the same conversation collapse Slack forced, arrived at from
      // a different direction.
      id: "notion:design-review",
      source: "notion",
      context: "work",
      title: "Comments on “Signal store — data model”",
      excerpt: "Rhona: the event table needs a tenant column before we cut over",
      count: 2,
      messages: [
        { who: "Rhona Baird", text: "The event table needs a tenant column before we cut over.", at: ago(6) },
        { who: "Rhona Baird", text: "Happy to pair on it tomorrow if that is easier.", at: ago(6) },
      ],
      who: "Rhona Baird",
      arrived: ago(6),
      awaiting: true,
      asks: "reply",
      url: "https://www.notion.so/demo-signal-store-data-model",
      seen_in: ["notion"],
      rank: null,
      because: null,
    },
    {
      id: "linear:ABC-412",
      source: "linear",
      context: "work",
      title: "Review requested · ABC-412",
      who: "Tomas Lindqvist",
      excerpt: "Rate resolution for repeat draws",
      arrived: ago(4),
      awaiting: true,
      asks: "review",
      url: "https://linear.app/example/issue/ABC-412",
      // The same event legitimately arrived twice — the tracker emails you too.
      seen_in: ["linear", "mail"],
    },
    {
      id: "almoner:inflow-gap:ABC-455",
      source: "almoner",
      context: "work",
      title: "No overseer card for ABC-455",
      excerpt: "Assigned to you and active upstream, but it never entered the board.",
      awaiting: true,
      asks: "reconcile",
      url: "https://linear.app/example/issue/ABC-455",
    },
    {
      id: "mail:bundle-delivery",
      source: "mail",
      context: "personal",
      title: "3 delivery updates",
      // A rollup must name its SUBJECTS, not just its count. "3 delivery
      // updates" tells you nothing you can act on; knowing the plane manual
      // is the one that has not shipped is the entire value of the row.
      excerpt: "Desk lamp arriving Tuesday · USB cable confirmed · plane manual not yet dispatched",
      count: 3,
      arrived: ago(5),
      bundled: true,
      asks: "fyi",
      seen_in: ["mail"],
      messages: [
        { who: "Hardware seller", text: "Combination plane manual — paid, posting Monday", at: ago(22) },
        { who: "Marketplace", text: "USB cable — order confirmed", at: ago(9) },
        { who: "Courier", text: "Desk lamp — arriving Tuesday, 09:00–13:00", at: ago(5) },
      ],
    },
    {
      id: "mail:bundle-jobs",
      source: "mail",
      context: "personal",
      title: "3 job alerts",
      excerpt: "Staff engineer at a code-hosting firm · principal engineer, remote UK · 18 recruiter matches",
      count: 3,
      arrived: ago(7),
      bundled: true,
      asks: "fyi",
      seen_in: ["mail"],
      messages: [
        { who: "Jobs board", text: "Staff Software Engineer — code-hosting company", at: ago(13) },
        { who: "Jobs board", text: "Principal Engineer — ticketing company, remote UK", at: ago(11) },
        { who: "Recruiter", text: "18 matches for your Python/AWS stack", at: ago(7) },
      ],
    },
    {
      id: "mail:bank-signin",
      source: "mail",
      context: "personal",
      title: "Unrecognised sign-in · bank account",
      // NOT bundled, deliberately. See the rule on `bundled` in types.ts: a
      // security alert the almoner cannot attribute to you is the single most
      // urgent thing that can arrive, and folding it under "3 security
      // alerts" beside the newsletters would be actively harmful.
      excerpt: "A sign-in from a device and city that match nothing you did. Verify or lock the account.",
      arrived: ago(3),
      awaiting: true,
      asks: "verify",
      url: "https://mail.example.com/thread/bank-signin",
      seen_in: ["mail"],
    },
    {
      id: "mail:bundle-security",
      source: "mail",
      context: "personal",
      title: "2 security alerts",
      // Named accounts, not "your account". The sender and the account the
      // event HAPPENED TO are different things, and only the second one lets
      // you decide whether to care.
      excerpt: "Mail provider: a sign-in you made, and a client you authorised — both matched to you",
      count: 2,
      arrived: ago(6),
      bundled: true,
      asks: "fyi",
      seen_in: ["mail"],
      messages: [
        {
          who: "Mail provider",
          text: "Mail account — new sign-in from your own Mac in Edinburgh, minutes after you asked for it",
          at: ago(24),
        },
        {
          who: "Mail provider",
          text: "Mail account — you authorised a desktop mail client to read your mail",
          at: ago(8),
        },
      ],
    },
    {
      id: "mail:bundle-news",
      source: "mail",
      context: "personal",
      title: "4 newsletters",
      excerpt: "Efficient inference in a new model · hummingbird feeders · insider buying signals · a growers co-op year",
      count: 4,
      arrived: ago(10),
      bundled: true,
      asks: "fyi",
      seen_in: ["mail"],
      messages: [
        { who: "AI weekly", text: "What a new model teaches us about efficient inference", at: ago(10) },
        { who: "Nature society", text: "Visit a hummingbird haven", at: ago(12) },
        { who: "Markets daily", text: "The insider signal every trader should know", at: ago(30) },
        { who: "Growers co-op", text: "273 farm visits this year", at: ago(16) },
      ],
    },
    {
      id: "mail:personal-club",
      source: "mail",
      context: "personal",
      title: "Club night moved to the 10th",
      who: "Village Hall",
      // Survived the filter because a person wrote it, then settled because
      // you answered. The majority case in real mail, not an edge case.
      excerpt: "Next session is in four weeks — I'm away on the 26th.",
      count: 2,
      arrived: ago(26),
      awaiting: false,
      url: "https://mail.example.com/thread/abc123",
      seen_in: ["mail"],
      messages: [
        {
          who: "Village Hall",
          text: "Just to say the next session will be in four weeks — I'm away on the 26th. See everyone on the 10th.",
          at: ago(27),
          url: "https://mail.example.com/thread/abc123#1",
        },
        {
          who: "You",
          text: "That's great, thanks for letting me know.",
          at: ago(26),
          url: "https://mail.example.com/thread/abc123#2",
        },
      ],
    },
  ],
};
