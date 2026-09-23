import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AlmonerDigest } from "../../api/types";
import { groupByDay } from "../../board/almoner/days";
import DigestTable from "./DigestTable";

/** A minimal digest, one Slack row and one Notion row, built directly rather
 * than through `fixture.ts` — this test cares only about which affordances
 * a row renders, not about the demo's broader shape. */
function digestWith(items: AlmonerDigest["items"]): AlmonerDigest {
  return { fetched_at: null, ranked: false, suppressed: 0, sources: [], items };
}

describe("DigestTable — Slack app deep links", () => {
  it("renders both the app link and the browser link for a Slack row", () => {
    const digest = digestWith([
      {
        id: "slack:demo",
        source: "slack",
        context: "work",
        title: "Group DM",
        arrived: new Date().toISOString(),
        url: "https://example.slack.com/archives/G01EXAMPLE",
        seen_in: ["slack"],
      },
    ]);
    render(<DigestTable days={groupByDay(digest.items)} />);
    expect(screen.getByRole("link", { name: "Open in Slack (app)" })).toHaveAttribute(
      "href",
      "slack://channel?id=G01EXAMPLE"
    );
    expect(screen.getByRole("link", { name: "Open in Slack (browser)" })).toHaveAttribute(
      "href",
      "https://example.slack.com/archives/G01EXAMPLE"
    );
  });

  it("renders exactly one link for a non-Slack row — no behaviour change", () => {
    const digest = digestWith([
      {
        id: "notion:demo",
        source: "notion",
        context: "work",
        title: "A page",
        arrived: new Date().toISOString(),
        url: "https://www.notion.so/demo-page",
        seen_in: ["notion"],
      },
    ]);
    render(<DigestTable days={groupByDay(digest.items)} />);
    expect(screen.getByRole("link", { name: "Open in Notion" })).toHaveAttribute(
      "href",
      "https://www.notion.so/demo-page"
    );
    expect(screen.queryByRole("link", { name: /Open in Slack/i })).not.toBeInTheDocument();
  });
});
