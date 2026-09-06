import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import CopyablePath from "./CopyablePath";

const PATH = "/Users/someone/.claude/overseer/ledger-poc-3f2a/backups/2026-09-06T01-00-00";

describe("<CopyablePath/>", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("shows the whole path as text and title, left-truncated by CSS", () => {
    render(<CopyablePath path={PATH} />);
    const text = screen.getByTitle(PATH);
    expect(text).toHaveTextContent(PATH);
    expect(text).toHaveAttribute("dir", "rtl");
  });

  it("copies the path to the clipboard and says so briefly", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyablePath path={PATH} />);
    const button = screen.getByRole("button", { name: "Copy path" });
    await act(async () => {
      fireEvent.click(button);
    });
    expect(writeText).toHaveBeenCalledWith(PATH);
    expect(button).toHaveTextContent("copied");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(button).toHaveTextContent("copy");
  });

  it("stays quiet when the clipboard is unavailable", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    render(<CopyablePath path={PATH} />);
    const button = screen.getByRole("button", { name: "Copy path" });
    await act(async () => {
      fireEvent.click(button);
    });
    expect(button).toHaveTextContent("copy");
  });
});
