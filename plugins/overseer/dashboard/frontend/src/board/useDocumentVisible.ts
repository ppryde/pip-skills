/**
 * Page Visibility for the dashboard's pollers. A background tab has no one
 * to show anything to, so every timer that fetches or syncs pauses while
 * the tab is hidden and catches up once when it returns. Shared by the
 * board, sessions and chronicle hooks so they agree on when to run.
 */
import { useEffect, useRef, useState } from "react";

/** Whether the page is in the foreground (Page Visibility API). */
export function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(() => typeof document === "undefined" || !document.hidden);
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

export interface VisibleIntervalOptions {
  /** When to fire `tick` immediately, besides on the interval:
   * - `"always"` (default): whenever the hook becomes active — mount, page
   *   shown, re-enabled. For a caller whose only fetch path is this hook.
   * - `"on-return"`: only when the page comes BACK to the foreground after
   *   having been hidden. For a caller that already loads on mount and on
   *   its own inputs changing, and wants just the catch-up. */
  immediate?: "always" | "on-return";
}

/** Run `tick` every `ms` while `enabled` and the page is visible, plus the
 * immediate firings `immediate` selects — so a hook's data is fresh when it
 * is looked at and untouched while it is not. `tick` is read through a ref
 * so callers can pass a fresh closure every render without the interval
 * being torn down and remade. */
export function useVisibleInterval(
  tick: () => void,
  ms: number,
  enabled: boolean,
  { immediate = "always" }: VisibleIntervalOptions = {}
): void {
  const visible = useDocumentVisible();
  const active = enabled && visible;
  const tickRef = useRef(tick);
  tickRef.current = tick;
  // Has the page been hidden since this hook mounted? Only then is an
  // activation a "return" rather than the first showing.
  const wasHiddenRef = useRef(false);
  if (!visible) wasHiddenRef.current = true;
  useEffect(() => {
    if (!active) return;
    if (immediate === "always" || wasHiddenRef.current) {
      wasHiddenRef.current = false;
      tickRef.current();
    }
    const id = setInterval(() => tickRef.current(), ms);
    return () => clearInterval(id);
  }, [active, ms, immediate]);
}
