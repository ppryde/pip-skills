import { useEffect } from "react";

/** CSS custom property the Atlas page's epic-lane scroll-snap reads for its
 * `scroll-margin-top` (styles.css) — set on `document.documentElement` so
 * every row's rule can see it via `var()` without prop-drilling a measured
 * pixel value through the component tree. */
export const CSS_VAR = "--atlas-topbar-height";

/** Used before the first real measurement lands, and whenever there's no
 * `.topbar` element to measure at all (defensive) — roughly the desktop
 * single-row topbar's height. */
export const DEFAULT_TOPBAR_HEIGHT_PX = 64;

/**
 * Impl-review round 1, finding 4 (HANDOFF's Mobile/Across "Epic-lane snap":
 * `scroll-margin-top` driven by "the real wrap-dependent topbar height").
 * No such measurement utility existed anywhere in the codebase — this is
 * it. Queries the DOM directly for `.topbar` (rather than taking a ref)
 * specifically so this can live entirely in Atlas-only code (EpicAtlas.tsx)
 * without touching App.tsx/TopBar.tsx — the topbar is TopBar's own root
 * element and is always a sibling already in the document by the time
 * EpicAtlas mounts (App.tsx only ever mounts EpicAtlas once `view ===
 * "atlas"`, alongside the topbar, never before it).
 *
 * Publishes the measurement as a CSS custom property on the document root
 * (`--atlas-topbar-height`) rather than returning a value for inline
 * styles — a single source every row's `scroll-margin-top` rule can read
 * via `var()`, so no per-row re-render is needed when the topbar's own
 * height changes (WF-085's R2-R5 mobile row scheme wraps it to different
 * heights across viewport widths).
 *
 * Impl-review round 2, finding 4 (real-browser, 390px): a residual gap was
 * observed between the snap point and the topbar's real rendered height —
 * suspected root cause is catching the topbar's height BEFORE its wrapped
 * rows (WF-085's R2-R5 mobile scheme) have fully settled, e.g. before
 * async content (session/repo/fleet counts) populates pills that push it
 * to another wrapped row. Three layered re-measurement triggers now:
 * (1) `remeasureKey` — pass something that changes across a breakpoint
 * crossing (EpicAtlas.tsx passes `isMobile`) to force a fresh synchronous
 * measurement, not just rely on the existing observer's own timing;
 * (2) the ResizeObserver on `.topbar` itself, unchanged, for continuous
 * tracking within a given breakpoint; (3) a `requestAnimationFrame`-
 * deferred re-measure after the initial synchronous one, specifically to
 * catch a topbar that hasn't finished wrapping in the very first layout
 * pass. Cannot fully verify the real-browser wrap-settling timing from
 * jsdom (no real layout engine) — flagged for the reviewer's own
 * real-browser re-check per their instruction.
 */
export function useTopbarHeightVar(remeasureKey?: unknown): void {
  useEffect(() => {
    const apply = (height: number) => {
      const px = Number.isFinite(height) && height > 0 ? Math.round(height) : DEFAULT_TOPBAR_HEIGHT_PX;
      document.documentElement.style.setProperty(CSS_VAR, `${px}px`);
    };

    const measure = () => {
      const topbar = document.querySelector<HTMLElement>(".topbar");
      apply(topbar ? topbar.getBoundingClientRect().height : NaN);
      return topbar;
    };

    const topbar = measure();
    if (!topbar) return;

    // Catches a topbar that hasn't finished wrapping in the very first
    // layout pass (e.g. async content arriving right after mount pushes it
    // to another row) — one extra measurement after the browser's next
    // paint, cheap insurance beyond the ResizeObserver below.
    const raf =
      typeof requestAnimationFrame === "function" ? requestAnimationFrame(measure) : undefined;

    // jsdom (unlike every real browser) has no ResizeObserver in every test
    // environment — same guard as AtlasTrail.tsx's own measurement effects.
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry) apply(entry.contentRect.height);
      });
      ro.observe(topbar);
    }

    return () => {
      if (raf !== undefined) cancelAnimationFrame(raf);
      ro?.disconnect();
    };
    // `remeasureKey` deliberately forces this WHOLE effect (fresh DOM
    // query + synchronous measurement + a new observer) to re-run on a
    // breakpoint crossing, rather than trusting the existing observer's
    // own timing to catch a wrap change promptly.
  }, [remeasureKey]);
}
