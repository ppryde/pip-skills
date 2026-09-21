import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Suspense, lazy } from "react";
import ChunkLoadBoundary from "./ChunkLoadBoundary";

// Stands in for `ChroniclePage`'s real `React.lazy(() => import(...))`: a
// chunk whose fetch rejects, the way a stale tab's hashed chunk file does
// once a `dist/` rebuild has removed it (a 404 on the dynamic import).
const FailingLazyPage = lazy(() =>
  Promise.reject(new Error("Failed to fetch dynamically imported module"))
);

describe("<ChunkLoadBoundary/>", () => {
  const originalConsoleError = console.error;

  afterEach(() => {
    // React logs the error it caught to the console — silenced per-test
    // below, restored here so it doesn't leak into unrelated suites.
    console.error = originalConsoleError;
    vi.restoreAllMocks();
  });

  it("renders children unchanged when nothing fails", () => {
    render(
      <ChunkLoadBoundary>
        <p>the real page</p>
      </ChunkLoadBoundary>
    );

    expect(screen.getByText("the real page")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("catches a rejected lazy import, renders a contained fallback with Reload, and leaves the rest of the tree mounted", async () => {
    // Without the boundary this throw unwinds past <Suspense> and unmounts
    // everything rendered alongside it — the exact failure this test guards
    // against. React also logs the caught error to the console; silenced so
    // the test output isn't a wall of the error under test.
    console.error = vi.fn();
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload },
      writable: true,
      configurable: true,
    });

    render(
      <div>
        {/* Stands in for the rest of <App/> — the board, the top bar —
            which must survive a Chronicle-only chunk failure. */}
        <p>rest of the app</p>
        <ChunkLoadBoundary>
          <Suspense fallback={<p>Loading…</p>}>
            <FailingLazyPage />
          </Suspense>
        </ChunkLoadBoundary>
      </div>
    );

    // The rejection propagates asynchronously — wait for the boundary to
    // catch it and swap in its fallback.
    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(alert.textContent).toMatch(/couldn't load/i);

    // The sibling outside the boundary is untouched.
    expect(screen.getByText("rest of the app")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
