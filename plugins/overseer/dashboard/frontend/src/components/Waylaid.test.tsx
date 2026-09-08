import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Waylaid from "./Waylaid";
import type { FetchFailure } from "../board/useBoard";

const riding = (over: Partial<FetchFailure> = {}): FetchFailure => ({
  message: "Failed to fetch",
  kind: "retryable",
  retries: 1,
  retryInSeconds: 2,
  ...over,
});

describe("<Waylaid/>", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("tells the story, keeps the raw error, and counts down to the scheduled rider", () => {
    render(<Waylaid error="Failed to fetch" failure={riding({ retryInSeconds: 5 })} onRetry={() => {}} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The messenger has been waylaid.");
    expect(alert).toHaveTextContent("Failed to fetch · rider 1 of 5 leaves in 5s");
    act(() => vi.advanceTimersByTime(3000));
    expect(alert).toHaveTextContent("rider 1 of 5 leaves in 2s");
  });

  it("counts DOWN to zero and stops, rather than wrapping round", () => {
    // The old strip wrapped its countdown forever because the retry behind it
    // never ended. The schedule is finite now and the next wait is a longer
    // one set by the hook, so wrapping would be a second invented schedule.
    render(<Waylaid error="Failed to fetch" failure={riding({ retryInSeconds: 2 })} onRetry={() => {}} />);
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.getByRole("alert")).toHaveTextContent("leaves in 0s");
  });

  it("restarts the countdown when the hook schedules the next, longer wait", () => {
    const { rerender } = render(
      <Waylaid error="Failed to fetch" failure={riding({ retries: 1, retryInSeconds: 2 })} onRetry={() => {}} />
    );
    rerender(
      <Waylaid error="Failed to fetch" failure={riding({ retries: 2, retryInSeconds: 4 })} onRetry={() => {}} />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("rider 2 of 5 leaves in 4s");
  });

  it("says the riders are spent once the budget runs out, with no countdown", () => {
    render(
      <Waylaid
        error="Failed to fetch"
        failure={riding({ retries: 5, retryInSeconds: null })}
        onRetry={() => {}}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No rider made it through.");
    expect(alert).toHaveTextContent("Nothing further will be tried on its own.");
    expect(alert).toHaveTextContent("gave up after 5 riders");
    expect(alert).not.toHaveTextContent("leaves in");
  });

  it("names a refused token as final, and never promises another attempt", () => {
    render(
      <Waylaid
        error="missing or invalid dashboard token"
        failure={riding({ kind: "auth", retries: 0, retryInSeconds: null })}
        onRetry={() => {}}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The gate turned the rider back.");
    expect(alert).toHaveTextContent("the token itself has to change");
    expect(alert).toHaveTextContent("missing or invalid dashboard token");
    expect(alert).not.toHaveTextContent("leaves in");
    expect(alert).not.toHaveTextContent("gave up after");
  });

  it("stills the needle whenever nothing is actually riding", () => {
    const { rerender } = render(
      <Waylaid error="x" failure={riding()} onRetry={() => {}} />
    );
    expect(screen.getByTestId("waylaid-needle").getAttribute("class"))
      .not.toContain("waylaid__needle--still");
    rerender(
      <Waylaid error="x" failure={riding({ kind: "auth", retryInSeconds: null })} onRetry={() => {}} />
    );
    expect(screen.getByTestId("waylaid-needle").getAttribute("class"))
      .toContain("waylaid__needle--still");
  });

  it("offers Cancel only while there is something to call back", () => {
    const onCancel = vi.fn();
    const { rerender } = render(
      <Waylaid error="x" failure={riding()} onRetry={() => {}} onCancel={onCancel} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Call them back" }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    // Budget spent: nothing is in flight or scheduled, so there is nothing
    // Cancel could stop.
    rerender(
      <Waylaid
        error="x"
        failure={riding({ retries: 5, retryInSeconds: null })}
        onRetry={() => {}}
        onCancel={onCancel}
      />
    );
    expect(screen.queryByRole("button", { name: "Call them back" })).not.toBeInTheDocument();
  });

  it("sends a rider now on the button", () => {
    const onRetry = vi.fn();
    render(<Waylaid error="Failed to fetch" failure={riding()} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Send a rider" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("claims no schedule at all for a caller that has none (the Chronicle)", () => {
    // `useChronicle` does no automatic retrying. The banner used to count
    // down 30s there against nothing whatsoever; it must now neither promise
    // a rider nor claim to have spent any.
    render(<Waylaid error="Failed to fetch" onRetry={() => {}} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The messenger has been waylaid.");
    expect(alert).toHaveTextContent("Failed to fetch");
    expect(alert).not.toHaveTextContent("leaves in");
    expect(alert).not.toHaveTextContent("gave up after");
  });
});
