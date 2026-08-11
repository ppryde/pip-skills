import { useEffect, useRef, useState } from "react";
import { InfoIcon } from "./icons";

export interface InfoTooltipProps {
  /** `aria-label` on the trigger button — what a screen reader announces
   * for "what does this info glyph explain". */
  label: string;
  children: React.ReactNode;
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
function InfoTooltip({ label, children }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

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
        className="info-tooltip__trigger"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <InfoIcon />
      </button>
      {open && (
        <div role="tooltip" className="info-tooltip__bubble">
          {children}
        </div>
      )}
    </span>
  );
}

export default InfoTooltip;
