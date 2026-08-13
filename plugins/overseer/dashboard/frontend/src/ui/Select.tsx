import { forwardRef } from "react";
import type { ReactNode, SelectHTMLAttributes } from "react";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  /** Optional eyebrow caption rendered beside the select via `.qb-label`
   * (same "label span + select" shape as `.topbar__repo-select`). Omit for
   * a bare select — e.g. when the caller supplies its own `aria-label` and
   * doesn't want a visible caption at all. */
  label?: ReactNode;
}

/**
 * Design-library Select (v1) — a thin typed wrapper around the shared
 * `.qb-select` native-`<select>` recipe. Forwards every native `<select>`
 * prop untouched (including `children` for the `<option>`s); `className`
 * composes with `.qb-select` rather than replacing it.
 */
const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, className, children, ...rest },
  ref
) {
  const classes = ["qb-select", className].filter(Boolean).join(" ");
  const select = (
    <select ref={ref} className={classes} {...rest}>
      {children}
    </select>
  );
  if (!label) return select;
  return (
    <label>
      <span className="qb-label">{label}</span>
      {select}
    </label>
  );
});

export default Select;
