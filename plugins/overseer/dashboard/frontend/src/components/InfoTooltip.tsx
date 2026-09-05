import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { InfoIcon } from "./icons";

/** Which way the bubble hangs off its trigger. The default is below and
 * flush left; each axis flips independently when that side would leave the
 * viewport (the rightmost tile in a grid, or a trigger near the bottom of a
 * scrolled drawer). */
interface Placement {
  align: "start" | "end";
  side: "bottom" | "top";
}

const DEFAULT_PLACEMENT: Placement = { align: "start", side: "bottom" };
// Breathing room from the viewport edge before a flip is worth it.
const EDGE_GAP = 8;

export interface InfoTooltipProps {
  /** `aria-label` on the trigger button — what a screen reader announces
   * for "what does this info glyph explain". */
  label: string;
  children: React.ReactNode;
  /** Custom trigger content (default: the info glyph). The trigger is a
   * <button>; its click toggles the bubble AND stops propagation so a
   * tooltip inside a clickable parent (e.g. a card tile whose body opens a
   * drawer) does not also fire the parent's onClick. */
  trigger?: React.ReactNode;
  triggerClassName?: string;
}

/**
 * Small tap/click-to-toggle info popover (Last Orders' "what is this?").
 * Self-contained — no portal, no external lib: the bubble is a plain
 * `position: absolute` child of the trigger's own `position: relative`
 * wrapper (see `.info-tooltip`/`.info-tooltip__bubble` in styles.css).
 *
 * Click toggles open/closed; Escape and an outside click both close it —
 * same dismiss idiom as `LabelFilterPopover`, minus the backdrop (this is
 * an inline glyph, not a modal sheet, so it doesn't dim the page).
 */
function InfoTooltip({ label, children, trigger, triggerClassName }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement>(DEFAULT_PLACEMENT);
  const rootRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);

  // Keep the bubble on screen: measure it in its default place before paint
  // and flip whichever axis overflows. Measured once per open — the bubble
  // is short-lived and the page beneath it does not move while it shows.
  useLayoutEffect(() => {
    if (!open) {
      setPlacement(DEFAULT_PLACEMENT);
      return;
    }
    const bubble = bubbleRef.current;
    if (!bubble) return;
    const rect = bubble.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return; // not laid out (tests)
    const next: Placement = {
      align: rect.right > window.innerWidth - EDGE_GAP && rect.left > rect.width ? "end" : "start",
      side: rect.bottom > window.innerHeight - EDGE_GAP && rect.top > rect.height ? "top" : "bottom",
    };
    setPlacement((cur) => (next.align !== cur.align || next.side !== cur.side ? next : cur));
    // Runs on open only: re-running after the flip would measure the
    // already-flipped bubble and undo it.
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function handlePointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [open]);

  return (
    <span className="info-tooltip" ref={rootRef}>
      <button
        type="button"
        className={"info-tooltip__trigger" + (triggerClassName ? " " + triggerClassName : "")}
        aria-label={label}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
      >
        {trigger ?? <InfoIcon />}
      </button>
      {open && (
        <div
          role="tooltip"
          className="info-tooltip__bubble"
          ref={bubbleRef}
          data-align={placement.align}
          data-side={placement.side}
        >
          {children}
        </div>
      )}
    </span>
  );
}

export default InfoTooltip;
