/**
 * Escape-to-close, owned in one place.
 *
 * Nine components each hand-rolled this — an effect, a `keydown` listener on
 * `window`, an `e.key === "Escape"` test and a matching teardown. Identical
 * every time, and the duplication was not free: with every overlay listening
 * independently, ONE press reached all of them, so a stacked pair had to
 * negotiate privately (the subagent drawer took the event in the capture
 * phase and called `stopPropagation` so the session drawer beneath it would
 * not also act). That negotiation is what a shared primitive removes.
 *
 * The contract is a STACK: exactly one dismisser fires per press, the one
 * registered last — the innermost layer on screen. A layer that should not
 * answer passes `enabled: false` and is not on the stack at all, which is
 * how the session drawer states "a subagent owns the key right now". That
 * stays a question about state, deliberately, rather than a race between
 * listeners: a component that knows it is not the top layer should say so,
 * not discover it from event ordering.
 *
 * One listener is installed for the whole app however many layers are open,
 * and removed once the last one closes.
 */
import { useEffect, useRef } from "react";

type Dismisser = { current: () => void };

// Mount order, which for nested overlays is outermost-first: a child's effect
// runs before its parent's on a shared commit, but an overlay and the overlay
// it opens never mount in the same commit — the inner one is opened by a
// state change in the outer one, a commit later. So the last entry is the
// innermost layer.
const stack: Dismisser[] = [];
let listening = false;

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  const top = stack[stack.length - 1];
  if (!top) return;
  // Only the top layer unwinds. Stopping propagation keeps any listener a
  // component still owns for its own reasons (a text input's own Escape, say)
  // from treating this as a second, unrelated press.
  event.stopPropagation();
  top.current();
}

/**
 * Close `onDismiss` when Escape is pressed and this is the innermost layer.
 *
 * `enabled` gates registration entirely, so a closed dialog, or one that has
 * handed the key to a layer above it, is not on the stack. `onDismiss` is
 * held in a ref, so a caller passing a fresh closure each render does not
 * re-register (and so does not jump the queue ahead of a layer above it).
 */
export function useDismiss(onDismiss: () => void, enabled: boolean = true): void {
  const ref = useRef(onDismiss);
  ref.current = onDismiss;

  useEffect(() => {
    if (!enabled) return;
    stack.push(ref);
    if (!listening) {
      window.addEventListener("keydown", onKeyDown);
      listening = true;
    }
    return () => {
      const at = stack.lastIndexOf(ref);
      if (at !== -1) stack.splice(at, 1);
      if (stack.length === 0 && listening) {
        window.removeEventListener("keydown", onKeyDown);
        listening = false;
      }
    };
  }, [enabled]);
}
