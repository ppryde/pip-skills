import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AlmonerPage from "./AlmonerPage";

const INSTALLED = { installed: true, configured: true };

/** Report a narrow or wide viewport to any `matchMedia` caller.
 *
 * The page no longer reads it — the layout is one table at every width, with
 * the narrow case handled purely in CSS — so these stubs are deliberately
 * INERT. That is the point: the two tests below prove the table survives
 * regardless of what `matchMedia` says, which is the invariant that replaced
 * the old card restack. `setupTests.ts` polyfills it as not-mobile. */
function setViewport(isMobile: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: isMobile,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("AlmonerPage", () => {
  it("labels the sample digest as a fixture, not your inflow", () => {
    // An unlabelled fixture that looks like real inflow is the one way this
    // page could actively mislead.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/Sample data/i)).toBeInTheDocument();
  });

  it("stamps each row and its chip with the source, so colour can key off it", () => {
    // The colour lives in CSS; what the component owes it is the hook. Both
    // the row and the chip carry it because they are coloured differently —
    // the row's lead cell takes a wash, the chip takes a border and fill.
    const { container } = render(<AlmonerPage status={null} demo />);
    const rows = [...container.querySelectorAll(".alm-table__item")];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const source = row.getAttribute("data-source");
      expect(source).toBeTruthy();
      // The chip in this row must agree with the row, or the two channels
      // would colour the same item two different ways.
      expect(row.querySelector(".alm-lab--src")).toHaveAttribute("data-source", source!);
    }
  });

  it("colours by source WITHOUT disturbing the state spine", () => {
    // Source and state are different questions. If a row ever carried its
    // source in place of its state class, "does this still want me" would
    // have quietly stopped being answerable.
    const { container } = render(<AlmonerPage status={null} demo />);
    const states = ["open", "reconcile", "settled", "bundled"];
    for (const row of container.querySelectorAll(".alm-table__item")) {
      expect(states.some((s) => row.classList.contains(`alm-row--${s}`))).toBe(true);
    }
  });

  it("leaves the page's name to the guild bar, not a second heading", () => {
    // TopBar's per-view title owns it now; the page name repeated directly
    // under the bar's copy of it is a layout that has lost track of who names
    // the page.
    const { container } = render(<AlmonerPage status={null} demo />);
    expect(container.querySelector(".almoner__heading")).toBeNull();
  });

  it("lays the digest out by day, newest first", () => {
    render(<AlmonerPage status={null} demo />);
    const days = screen.getAllByRole("columnheader", { name: /Today|Yesterday|September|October/i });
    expect(days.length).toBeGreaterThanOrEqual(1);
  });

  it("marks a row you have not answered as needing you", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getAllByText("needs you").length).toBeGreaterThanOrEqual(1);
  });

  it("marks a thread you closed yourself as settled, not as an open ask", () => {
    // Asked at 11:06, settled by 13:37 — a digest that still calls that open
    // is simply wrong.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText("settled")).toBeInTheDocument();
  });

  it("gives a derived check its own state rather than calling it a message", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText("reconcile")).toBeInTheDocument();
  });

  it("says how many messages a row collapsed", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText("5 messages")).toBeInTheDocument();
  });

  it("keeps a collapsed conversation hidden until the row is opened", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.queryByText(/helps us find the edges/i)).not.toBeVisible();
  });

  it("opens a conversation in place, and closes it again", () => {
    render(<AlmonerPage status={null} demo />);
    const toggle = screen.getByRole("button", { name: /Show 5 messages/i });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/helps us find the edges/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /^Hide/i }));
    expect(screen.queryByText(/helps us find the edges/i)).not.toBeVisible();
  });

  it("explains, in the open conversation, why the row is classified as it is", () => {
    // The last-speaker rule stops being invisible machinery.
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 5 messages/i }));
    expect(screen.getByText(/Their word was last/i)).toBeVisible();
  });

  it("gives each message in an opened conversation its own permalink", () => {
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 5 messages/i }));
    expect(screen.getAllByRole("link", { name: "↗" }).length).toBeGreaterThanOrEqual(5);
  });

  it("names the app each row links out to", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getAllByRole("link", { name: /Open in Slack/i }).length).toBe(1);
    expect(screen.getByRole("link", { name: /Open in Linear/i })).toBeInTheDocument();
  });

  it("does not offer to expand a row that collapsed nothing", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.queryByRole("button", { name: /Show 1 messages/i })).not.toBeInTheDocument();
  });

  it("names who is waiting and how long they have waited", () => {
    render(<AlmonerPage status={null} demo />);
    const strip = screen.getByRole("list");
    expect(within(strip).getByText("Rhona Baird")).toBeInTheDocument();
  });

  it("shows someone you answered last as clear, not as owed", () => {
    render(<AlmonerPage status={null} demo />);
    const strip = screen.getByRole("list");
    expect(within(strip).getByText("Village Hall")).toBeInTheDocument();
    expect(within(strip).getAllByText("clear").length).toBeGreaterThanOrEqual(1);
  });

  it("describes the day band for a reader who cannot see it", () => {
    // The axis itself is aria-hidden — a scatter of positioned dots is
    // meaningless read aloud.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/arrivals between/i)).toBeInTheDocument();
  });

  it("still draws a band when the newest day holds only a derived row", () => {
    // Found by the clock rolling past midnight mid-session. `groupByDay` parks
    // undated reconcile items on today, so in the small hours the newest day
    // is a synthetic one with a single derived row and no arrival times — and
    // the band, reading only `days[0]`, drew nothing. The page looked broken
    // for the first hours of every day, and no test noticed because they all
    // happened to run in the afternoon.
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date(Date.now() + 26 * 3600_000));
      render(<AlmonerPage status={null} demo />);
      expect(screen.getByText(/arrivals between/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("names a source it could not reach", () => {
    // A silently short digest reads as "nothing needs you" — the one wrong
    // answer this page can give.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/could not reach/i)).toHaveTextContent("work");
  });

  it("folds each kind of machine mail into one row that says how many", () => {
    // Twenty threads, two written by a person. Listing the rest individually
    // drowns the two that matter; dropping them loses "did it ship?".
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText("3 delivery updates")).toBeInTheDocument();
    expect(screen.getByText("4 newsletters")).toBeInTheDocument();
    expect(screen.getAllByText("bundled").length).toBe(4);
    expect(screen.getByText("2 security alerts")).toBeInTheDocument();
  });

  it("never folds a security alert it cannot attribute to you", () => {
    // A sign-in you made is noise. A sign-in you did NOT make, to a bank, is
    // the most urgent thing that can arrive all week — burying it under
    // "3 security alerts" beside the newsletters is worse than not folding.
    render(<AlmonerPage status={null} demo />);
    const row = screen.getByText(/Unrecognised sign-in · bank account/i).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("needs you")).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("bundled")).not.toBeInTheDocument();
  });

  it("names the account a security event happened to, not just the sender", () => {
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(
      screen.getByRole("button", { name: /Show 2 messages in 2 security alerts/i })
    );
    expect(screen.getByText(/Mail account — new sign-in from your own Mac/i)).toBeVisible();
  });

  it("makes a rollup name its subjects, not just its count", () => {
    // "3 security alerts" is a row you must open every time. Naming the
    // accounts is what lets it be dismissed at a glance.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/Mail provider: a sign-in you made/i)).toBeInTheDocument();
    expect(screen.getByText(/plane manual not yet dispatched/i)).toBeInTheDocument();
  });

  it("names the individual account or order inside an opened rollup", () => {
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 3 messages in 3 delivery updates/i }));
    expect(screen.getByText(/Combination plane manual/i)).toBeVisible();
  });

  it("does not claim a conversation nobody had, inside a rollup", () => {
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 4 messages in 4 newsletters/i }));
    // Scoped to the panel that was opened: every rollup carries this footer
    // in the DOM, hidden until its own row is expanded.
    const panel = document.getElementById("alm-thread-mail:bundle-news");
    expect(panel?.hidden).toBe(false);
    expect(within(panel as HTMLElement).getByText(/no person wrote these/i)).toBeInTheDocument();
  });

  it("opens a rollup with the same control as a conversation", () => {
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 4 messages in 4 newsletters/i }));
    expect(screen.getByText(/hummingbird haven/i)).toBeVisible();
  });

  it("keeps rollups off the day band", () => {
    // The band is about when work reached you, not when mail did.
    render(<AlmonerPage status={null} demo />);
    // Three real arrivals today — Slack, Linear, and the bank alert that
    // escaped its bundle. Were the four rollups counted it would say seven.
    expect(screen.getByText(/arrivals between/i)).toHaveTextContent(/^3 arrivals/);
  });

  it("says how much it filtered out before ranking", () => {
    // A real mailbox scan found two human messages in twenty threads. A
    // digest that does not say it dropped the rest reads as a quiet inbox
    // rather than as filtering that worked.
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/filtered out before ranking/i)).toHaveTextContent("4");
  });

  it("says when the judging pass did not run", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByText(/Unranked/i)).toBeInTheDocument();
  });

  it("invites a gather before anything has been fetched", () => {
    // No poll and no fetch on mount: a digest is several remote round trips,
    // so it gathers only when asked.
    render(<AlmonerPage status={INSTALLED} />);
    expect(screen.getByText(/Nothing gathered yet/i)).toBeInTheDocument();
  });

  it("distinguishes 'no sources configured' from 'nothing needs you'", () => {
    render(<AlmonerPage status={{ installed: true, configured: false }} />);
    expect(screen.getByText(/No sources configured/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing gathered yet/i)).not.toBeInTheDocument();
  });

  it("disables Gather while showing the sample", () => {
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByRole("button", { name: /Gather/i })).toBeDisabled();
  });

  it("renders a real table on a wide viewport", () => {
    setViewport(false);
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("STAYS a table on a narrow viewport", () => {
    // It used to restack into cards here. The table simply vanishing on a
    // narrow window was more confusing than a table that has to be tight.
    setViewport(true);
    render(<AlmonerPage status={null} demo />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText("needs you").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("5 messages")).toBeInTheDocument();
  });

  it("keeps the conversation expandable when narrow", () => {
    setViewport(true);
    render(<AlmonerPage status={null} demo />);
    fireEvent.click(screen.getByRole("button", { name: /Show 5 messages/i }));
    expect(screen.getByText(/helps us find the edges/i)).toBeVisible();
  });
});
