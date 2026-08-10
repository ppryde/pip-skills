import { useEffect, useState } from "react";

/**
 * Mobile-collapse gate (WF-085 in-progress lane): tiny `matchMedia` wrapper
 * so `Board.tsx` can pick `collapseStagesForMobile(lanes)` vs `lanes` by
 * viewport width — `useMediaQuery("(max-width:720px)")` mirrors the exact
 * breakpoint the mobile CSS block in styles.css already gates on.
 *
 * SSR/jsdom-safe: `window.matchMedia` doesn't exist in every environment
 * (older jsdom, non-browser SSR) — both the initial read and the listener
 * setup guard on `typeof window.matchMedia === "function"` and fall back to
 * `false` (not-mobile) rather than throwing. `setupTests.ts` installs a
 * default `matchMedia` polyfill (also reporting not-mobile) so component
 * tests that don't care about viewport keep today's desktop behaviour
 * without each one stubbing it individually.
 */
export function useMediaQuery(query: string): boolean {
  const getMatches = (): boolean => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia(query).matches;
  };

  const [matches, setMatches] = useState<boolean>(getMatches);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(query);
    const listener = () => setMatches(mql.matches);
    // The query string itself (not just the listener target) can change
    // between renders — resync immediately rather than waiting for the
    // next viewport change to fire.
    listener();

    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", listener);
      return () => mql.removeEventListener("change", listener);
    }
    // Safari <14 fallback — deprecated but still the only API there.
    if (typeof mql.addListener === "function") {
      mql.addListener(listener);
      return () => mql.removeListener(listener);
    }
    return undefined;
  }, [query]);

  return matches;
}
