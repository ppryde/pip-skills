import { forwardRef } from "react";
import type { HTMLAttributes } from "react";

export type LabelProps = HTMLAttributes<HTMLSpanElement>;

/**
 * Design-library Label (v1) — a thin typed wrapper around the shared
 * `.qb-label` uppercase eyebrow/field-label recipe (styles.css "Design
 * library" section, factored from `.topbar__repo-select-label` /
 * `.filter-bar__eyebrow`). Forwards every native `<span>` prop untouched;
 * `className` composes with `.qb-label` rather than replacing it.
 */
const Label = forwardRef<HTMLSpanElement, LabelProps>(function Label(
  { className, ...rest },
  ref
) {
  const classes = ["qb-label", className].filter(Boolean).join(" ");
  return <span ref={ref} className={classes} {...rest} />;
});

export default Label;
