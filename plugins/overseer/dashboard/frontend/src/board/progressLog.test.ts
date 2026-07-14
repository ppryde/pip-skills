import { describe, expect, it } from "vitest";
import { parseProgressLog } from "./progressLog";

describe("parseProgressLog", () => {
  it("parses well-formed entries", () => {
    const text =
      "- 2026-07-14T08:19 — comms: subagent mode (~0 tokens)\n" +
      "- 2026-07-14T08:37 — plan-review passed (~165k tokens)";

    expect(parseProgressLog(text)).toEqual([
      {
        timestamp: "2026-07-14T08:19",
        note: "comms: subagent mode",
        tokens: "0",
      },
      {
        timestamp: "2026-07-14T08:37",
        note: "plan-review passed",
        tokens: "165k",
      },
    ]);
  });

  it("parses a single entry", () => {
    expect(
      parseProgressLog("- 2026-01-01T00:00 — started (~1 tokens)")
    ).toEqual([{ timestamp: "2026-01-01T00:00", note: "started", tokens: "1" }]);
  });

  it("returns null for an absent/empty section", () => {
    expect(parseProgressLog("")).toBeNull();
    expect(parseProgressLog("   \n   \n")).toBeNull();
  });

  it("returns null (never partial) when one line among several is malformed", () => {
    const text =
      "- 2026-07-14T08:19 — comms: subagent mode (~0 tokens)\n" +
      "not a valid line at all\n" +
      "- 2026-07-14T08:37 — plan-review passed (~165k tokens)";

    expect(parseProgressLog(text)).toBeNull();
  });

  it("returns null for a line missing the tokens suffix", () => {
    expect(
      parseProgressLog("- 2026-07-14T08:19 — comms: subagent mode")
    ).toBeNull();
  });

  it("returns null for a line missing the leading dash", () => {
    expect(
      parseProgressLog("2026-07-14T08:19 — comms: subagent mode (~0 tokens)")
    ).toBeNull();
  });

  it("returns null when a note contains an embedded newline — the log_progress line format doesn't survive a multi-line note intact", () => {
    // log_progress("line one\nline two", ...) emits ONE logical bullet whose
    // note spans two physical lines once stored/rendered:
    //   - 2026-07-14T09:00 — line one
    //   line two (~50 tokens)
    // Neither resulting physical line matches the full-line pattern alone —
    // this is the malformed bucket's multi-line-note case (Decisions).
    const text = "- 2026-07-14T09:00 — line one\nline two (~50 tokens)";
    expect(parseProgressLog(text)).toBeNull();
  });

  it("returns null when a multi-line note is sandwiched between otherwise well-formed entries", () => {
    const text =
      "- 2026-07-14T08:00 — first entry (~10 tokens)\n" +
      "- 2026-07-14T09:00 — a note that spans\n" +
      "two physical lines (~50 tokens)\n" +
      "- 2026-07-14T10:00 — third entry (~20 tokens)";
    expect(parseProgressLog(text)).toBeNull();
  });
});
