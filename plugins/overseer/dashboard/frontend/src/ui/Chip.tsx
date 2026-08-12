import { forwardRef } from "react";
import type { HTMLAttributes } from "react";

export type ChipProps = HTMLAttributes<HTMLSpanElement>;

/**
 * Design-library Chip (v1) — a thin typed wrapper around the shared
 * `.qb-chip` small pill/badge recipe (styles.css "Design library" section,
 * factored from `.topbar__pill`). Forwards every native `<span>` prop
 * untouched; `className` composes with `.qb-chip` rather than replacing it.
 */
const Chip = forwardRef<HTMLSpanElement, ChipProps>(function Chip(
  { className, ...rest },
  ref
) {
  const classes = ["qb-chip", className].filter(Boolean).join(" ");
  return <span ref={ref} className={classes} {...rest} />;
});

export default Chip;
