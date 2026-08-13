import { forwardRef } from "react";
import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;
export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Design-library Input (v1) — a thin typed wrapper around the shared
 * `.qb-input` bordered-field recipe (styles.css "Design library" section,
 * factored from `.filter-bar__search` + the card drawer's title/body edit
 * fields). Forwards every native `<input>` prop untouched; `className`
 * composes with `.qb-input` rather than replacing it.
 */
const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref
) {
  const classes = ["qb-input", className].filter(Boolean).join(" ");
  return <input ref={ref} className={classes} {...rest} />;
});

/**
 * Textarea sibling of {@link Input} — same `.qb-input` recipe, applied to a
 * `<textarea>` instead. A caller that needs the drawer's bigger monospace
 * body-edit look still layers its own modifier class on top via
 * `className`, same as `Button`/`Select` do for their own bespoke variants.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ className, ...rest }, ref) {
    const classes = ["qb-input", className].filter(Boolean).join(" ");
    return <textarea ref={ref} className={classes} {...rest} />;
  }
);

export default Input;
