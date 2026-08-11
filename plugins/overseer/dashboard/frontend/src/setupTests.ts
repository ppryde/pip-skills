// Vitest setup: extends `expect` with jest-dom matchers (toBeInTheDocument,
// etc.) for RTL render tests.
import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement `matchMedia` at all — without this, Board.tsx's
// `useMediaQuery("(max-width:720px)")` (WF-085 in-progress lane) would throw
// in every component test that renders <Board/>/<App/>. Default is
// not-mobile (matches: false) so every EXISTING test keeps today's desktop
// (11-lane) behaviour without touching this file; tests that specifically
// exercise the mobile collapse override `window.matchMedia` themselves (see
// Board.test.tsx's "mobile" describe block).
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList => {
    return {
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  };
}

// jsdom doesn't implement `ResizeObserver` at all — without this, the Epic
// Atlas's `AtlasTrail` (WF-086), which measures its own lane box to size the
// SVG trail, would throw in every component test that renders it. This is a
// no-op default (never fires a callback) so every test keeps a stable,
// zero-size initial measurement without touching this file; tests that
// specifically exercise the re-measure path stub their own `ResizeObserver`
// (via `vi.stubGlobal`) to capture and fire the callback — same pattern as
// Board.test.tsx's "mobile" describe block overriding `matchMedia` above.
if (typeof window !== "undefined" && typeof window.ResizeObserver !== "function") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
