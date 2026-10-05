import { describe, expect, it } from "vitest";
import { slackLink } from "./slackLink";

describe("slackLink", () => {
  it("builds a channel-only deep link when the permalink carries no message", () => {
    // This is the shape most rows actually carry — miss it and the feature
    // does nothing.
    const link = slackLink("https://example.slack.com/archives/G01EXAMPLE");
    expect(link).toBe("slack://channel?id=G01EXAMPLE");
    expect(link).not.toContain("message=");
  });

  it("splits a 16-digit message timestamp into seconds.micros", () => {
    const link = slackLink(
      "https://example.slack.com/archives/G01EXAMPLE/p1789371022073699"
    );
    expect(link).toBe("slack://channel?id=G01EXAMPLE&message=1789371022.073699");
  });

  it("splits a shorter, 15-digit message timestamp the same way", () => {
    const link = slackLink(
      "https://example.slack.com/archives/G01EXAMPLE/p000000000000100"
    );
    expect(link).toBe("slack://channel?id=G01EXAMPLE&message=000000000.000100");
  });

  it("passes a thread_ts query param through untouched", () => {
    const link = slackLink(
      "https://example.slack.com/archives/G01EXAMPLE/p1789371022073699?thread_ts=1789371000.000100"
    );
    expect(link).toBe(
      "slack://channel?id=G01EXAMPLE&message=1789371022.073699&thread_ts=1789371000.000100"
    );
  });

  it("includes team only when opts.team is given and well-formed", () => {
    const withTeam = slackLink("https://example.slack.com/archives/G01EXAMPLE", {
      team: "T01EXAMPLE",
    });
    expect(withTeam).toBe("slack://channel?id=G01EXAMPLE&team=T01EXAMPLE");

    const withoutTeam = slackLink("https://example.slack.com/archives/G01EXAMPLE");
    expect(withoutTeam).not.toContain("team=");

    // Malformed team ids are dropped rather than smuggled through.
    const malformed = slackLink("https://example.slack.com/archives/G01EXAMPLE", {
      team: "not-a-team-id",
    });
    expect(malformed).not.toContain("team=");
  });

  it("rejects a non-Slack host", () => {
    expect(slackLink("https://example.com/archives/G01EXAMPLE")).toBe("");
  });

  it("rejects a non-https scheme", () => {
    expect(slackLink("http://example.slack.com/archives/G01EXAMPLE")).toBe("");
  });

  it("rejects javascript: and data: urls outright", () => {
    expect(slackLink("javascript:alert(1)")).toBe("");
    expect(slackLink("data:text/html,<script>alert(1)</script>")).toBe("");
  });

  it("rejects a lookalike host that merely contains slack.com", () => {
    // The attack this guards: string-substitution into a template would
    // happily accept this. Allowlist parsing must not.
    expect(slackLink("https://evil-slack.com.attacker.net/archives/G01EXAMPLE")).toBe("");
  });

  it("rejects a path with extra segments or traversal", () => {
    expect(slackLink("https://example.slack.com/archives/G01EXAMPLE/extra/segments")).toBe("");
    expect(slackLink("https://example.slack.com/archives/../etc/passwd")).toBe("");
    expect(slackLink("https://example.slack.com/not-archives/G01EXAMPLE")).toBe("");
  });

  it("renders no link at all for undefined or empty input", () => {
    expect(slackLink(undefined)).toBe("");
    expect(slackLink("")).toBe("");
  });

  it("renders no link for a string that cannot be parsed as a URL", () => {
    expect(slackLink("not a url at all")).toBe("");
  });
});
