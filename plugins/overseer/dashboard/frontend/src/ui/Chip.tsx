import { forwardRef } from "react";
import type { HTMLAttributes } from "react";

export interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  /** Curated label-palette key (`board/labelColor.ts`'s `PALETTE_KEYS` — or
   * an F10 registry override, WF-067, which always resolves to one of the
   * same keys) — adds `label-chip--<tone>` alongside `.qb-chip`, picking up
   * that key's bg/text/border custom properties (styles.css's
   * `.label-chip--*` block). Omit for the plain neutral `.qb-chip` pill
   * (last-refreshed/rest-window badges etc.) — `tone` is purely additive,
   * never required.
   *
   * `tone` only ever adds the COLOUR modifier. The hand-drawn wobble SHAPE
   * that goes with it (`.label-chip` — smaller font/padding, wobble
   * border-radius, ellipsis clipping) is a caller-supplied `className`, same
   * as any other Chip variant — see `LabelChips.tsx`/`LabelEditor.tsx`,
   * which pass `className="label-chip"` alongside `tone`. That keeps a
   * plain `<Chip tone="sky"/>` (no `label-chip` className) a same-box
   * `.qb-chip` with just the colour swapped in, rather than baking the
   * label-specific shape into every toned chip. */
  tone?: string;
}

/**
 * Design-library Chip (v1) — a thin typed wrapper around the shared
 * `.qb-chip` small pill/badge recipe (styles.css "Design library" section,
 * factored from `.topbar__pill`). Forwards every native `<span>` prop
 * untouched; `className` composes with `.qb-chip` rather than replacing it.
 *
 * `tone` (label-chip migration) is the one non-passthrough prop — see
 * `ChipProps.tone`'s own comment for what it adds and why the wobble shape
 * stays a `className`, not part of the prop itself.
 */
const Chip = forwardRef<HTMLSpanElement, ChipProps>(function Chip(
  { className, tone, ...rest },
  ref
) {
  const classes = ["qb-chip", tone && `label-chip--${tone}`, className]
    .filter(Boolean)
    .join(" ");
  return <span ref={ref} className={classes} {...rest} />;
});

export default Chip;
