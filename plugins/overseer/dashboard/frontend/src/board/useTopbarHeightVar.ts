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
 */
export function useTopbarHeightVar(): void {
  useEffect(() => {
    const apply = (height: number) => {
      const px = Number.isFinite(height) && height > 0 ? Math.round(height) : DEFAULT_TOPBAR_HEIGHT_PX;
      document.documentElement.style.setProperty(CSS_VAR, `${px}px`);
    };

    const topbar = document.querySelector<HTMLElement>(".topbar");
    if (!topbar) {
      apply(NaN);
      return;
    }

    apply(topbar.getBoundingClientRect().height);

    // jsdom (unlike every real browser) has no ResizeObserver in every test
    // environment — same guard as AtlasTrail.tsx's own measurement effects.
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) apply(entry.contentRect.height);
    });
    ro.observe(topbar);
    return () => ro.disconnect();
  }, []);
}
