import { useEffect, useRef, useState } from "react";

/** The one viewport where the top bar auto-hides: landscape (width > height)
 * AND short. Kept as a string so the CSS `@media` and this JS test stay in
 * lock-step — change both together. */
export const SHORT_LANDSCAPE_QUERY =
  "(orientation: landscape) and (max-height: 600px)";

/** Ignore sub-pixel / tiny scroll jitter before toggling. */
const TOGGLE_THRESHOLD_PX = 6;

/**
 * On a short landscape viewport, hides the top bar when the board scrolls DOWN
 * and reveals it on scroll UP (and whenever the scroller is at the very top).
 * Off that viewport it always returns `false`.
 *
 * Listens in the CAPTURE phase on `document` (scroll doesn't bubble) so it
 * catches whichever element actually scrolls — on the desktop layout each lane
 * scrolls independently — scoped to scrolls inside `.board-region` so an open
 * drawer/popover elsewhere never toggles the bar. Per-target last-position is
 * tracked so mixed lane scrolls each read their own direction. Purely
 * presentational; resets on media-query change.
 */
export function useHideTopBarOnScroll(): boolean {
  const [hidden, setHidden] = useState(false);
  const lastByTarget = useRef(new WeakMap<HTMLElement, number>());

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(SHORT_LANDSCAPE_QUERY);
    const seen = lastByTarget.current;

    function onScroll(e: Event) {
      if (!mq.matches) return;
      const t = e.target as HTMLElement | null;
      if (!t || typeof t.closest !== "function" || !t.closest(".board-region"))
        return;
      const y = t.scrollTop;
      const last = seen.get(t) ?? y;
      seen.set(t, y);
      const dy = y - last;
      if (Math.abs(dy) < TOGGLE_THRESHOLD_PX) return;
      // At/near the top the bar is always shown; else down hides, up shows.
      setHidden(y > 4 && dy > 0);
    }

    function onMqChange() {
      if (!mq.matches) setHidden(false); // never hidden off short-landscape
    }

    document.addEventListener("scroll", onScroll, {
      capture: true,
      passive: true,
    });
    mq.addEventListener("change", onMqChange);
    onMqChange();
    return () => {
      document.removeEventListener("scroll", onScroll, {
        capture: true,
      } as EventListenerOptions);
      mq.removeEventListener("change", onMqChange);
    };
  }, []);

  return hidden;
}
