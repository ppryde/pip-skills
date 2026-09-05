import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Waylaid from "./Waylaid";

describe("<Waylaid/>", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("tells the story, keeps the raw error, counts down and wraps", () => {
    render(<Waylaid error="Failed to fetch" retryEverySeconds={5} onRetry={() => {}} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The messenger has been waylaid.");
    expect(alert).toHaveTextContent("keep sending riders until one makes it through");
    expect(alert).toHaveTextContent("Failed to fetch · another rider leaves in 5s");
    act(() => vi.advanceTimersByTime(3000));
    expect(alert).toHaveTextContent("another rider leaves in 2s");
    act(() => vi.advanceTimersByTime(2000));
    expect(alert).toHaveTextContent("another rider leaves in 5s"); // the poll fired; a new rider is out
  });

  it("sends a rider now on the button, and the needle is there to seek", () => {
    const onRetry = vi.fn();
    render(<Waylaid error="Failed to fetch" retryEverySeconds={30} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Send a rider" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("waylaid-needle")).toBeInTheDocument();
  });
});
