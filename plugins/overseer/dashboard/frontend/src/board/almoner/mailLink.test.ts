import { describe, expect, it } from "vitest";
import { gmailLink } from "./mailLink";

describe("gmailLink", () => {
  it("finds a message by its RFC 822 id", () => {
    expect(gmailLink("abc123@mail.example.com")).toContain(
      "#search/rfc822msgid:abc123%40mail.example.com"
    );
  });

  it("strips the angle brackets the header carries", () => {
    // IMAP returns `Message-ID: <abc@host>`; Gmail's search wants the bare id.
    expect(gmailLink("<abc@host>")).toBe(gmailLink("abc@host"));
  });

  it("opens the mailbox by address, not by signed-in order", () => {
    // `/u/0/` indexes accounts by sign-in ORDER — unstable, different per
    // device, and unusable in a stored link when there are two mailboxes.
    expect(gmailLink("a@b.com", "work@example.com")).toContain("/mail/u/work%40example.com/");
  });

  it("falls back to the first mailbox when no address is known", () => {
    expect(gmailLink("a@b.com")).toContain("/mail/u/0/");
  });

  it("escapes an id containing url-significant characters", () => {
    expect(gmailLink("a+b/c?d@host")).toContain("rfc822msgid:a%2Bb%2Fc%3Fd%40host");
  });

  it("renders no link at all when there is no message id", () => {
    // Better no link than one that searches for nothing and lands on an
    // empty results page.
    expect(gmailLink(undefined)).toBe("");
    expect(gmailLink("")).toBe("");
    expect(gmailLink("   ")).toBe("");
    expect(gmailLink("<>")).toBe("");
  });
});
