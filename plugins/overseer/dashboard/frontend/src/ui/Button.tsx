import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual emphasis — "primary" for the one action that commits (e.g. a
   * drawer's Save), "neutral" (default) for everything else. Maps 1:1 onto
   * the `.qb-btn` / `.qb-btn--primary` Role-A recipe (styles.css "Design
   * library" section). */
  variant?: "primary" | "neutral";
}

/**
 * Design-library Button (v1) — a thin typed wrapper around the shared
 * `.qb-btn` Role-A button recipe. Forwards every native `<button>` prop
 * untouched; `className` composes with the primitive's own classes rather
 * than replacing them, so a caller can still layer on a genuinely
 * control-specific modifier alongside it — though the drawer buttons now
 * carry none, rendering as the bare shared button.
 * Defaults `type="button"` (a bare `.qb-btn` inside a `<form>` should never
 * accidentally submit it) — pass `type="submit"` explicitly to opt in.
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "neutral", className, type = "button", ...rest },
  ref
) {
  const classes = ["qb-btn", variant === "primary" ? "qb-btn--primary" : "", className]
    .filter(Boolean)
    .join(" ");
  return <button ref={ref} type={type} className={classes} {...rest} />;
});

export default Button;
