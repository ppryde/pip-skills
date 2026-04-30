# Maizzle — Email Doctrine

## Purpose

Rules and gotchas for engineers building email templates with Maizzle — the Tailwind CSS email framework (stable: v5.5.0, February 2026). Maizzle applies the Tailwind CSS utility workflow to plain HTML email templates, compiling and inlining CSS at build time. Unlike MJML, it does not abstract table-based layout — developers write table HTML directly or use Maizzle's starter templates. Suited to teams already fluent in Tailwind who prefer full HTML control without learning a component DSL.

## Rule Catalog

---

**[MZL-001]** `transactional: mortal | marketing: mortal` — Run `maizzle build production` for all output intended for sending — not `maizzle serve` output.
> `maizzle serve` produces development builds: CSS is not inlined, images use localhost paths, minification is off. Sending a development build sends unstyled HTML with broken image URLs. Source: Maizzle documentation — build environments.
> `detect: contextual` — check CI/CD pipeline to confirm the production build command is used for ESP delivery

**[MZL-002]** `transactional: mortal | marketing: mortal` — Pin Maizzle and Tailwind CSS to exact versions in `package.json`.
> Tailwind v3 → v4 is a major breaking change affecting how Maizzle processes CSS. Maizzle v4 → v5 changed the build engine (Vite replaces Browsersync). Floating semver (`^5.5.0`, `^3.4.17`) causes undetected visual regressions on `npm install`. Source: Maizzle v5 changelog; Tailwind CSS v4 migration guide.
> `detect: contextual` — check package.json for caret/tilde ranges on `maizzle` and `tailwindcss`

**[MZL-003]** `transactional: mortal | marketing: mortal` — Do not use Tailwind `flex`, `grid`, `inline-flex`, or `inline-grid` utilities for structural layout.
> Flexbox and grid are not supported in Outlook 2007–2019 or Gmail (for non-Google accounts). Maizzle does not restrict these utilities — they compile and inline successfully but silently fail in major clients. Use table-based HTML for all structural layout. Use `flex` utilities only inside `@media` queries scoped to clients known to support it. Source: caniemail.com.
> `detect: contextual` — check if flex/grid utilities appear on layout-critical structural elements

**[MZL-004]** `transactional: mortal | marketing: mortal` — Do not use Tailwind CSS variable utilities (`bg-[var(--colour)]`, `text-[var(--colour)]`) in email templates.
> CSS Custom Properties are not supported in Outlook 2007–2019, Gmail, or Yahoo Mail (see GOTCHA-024). Maizzle's CSS inlining step resolves static Tailwind values at build time, but arbitrary `var()` references cannot be statically resolved — they are emitted as-is into inline styles. Source: caniemail.com.
> `detect: regex` — pattern: `\bvar\(--[^)]+\)`

**[MZL-005]** `transactional: mortal | marketing: mortal` — Add all dynamically composed class names to the Tailwind `safelist` in `tailwind.config.js`.
> Tailwind's content scanner detects class names as literal strings. Classes built via string interpolation in Nunjucks expressions (`"bg-" + colour`) or component props are invisible to the scanner and their CSS is purged. List dynamic classes in `safelist` with regex patterns if needed.
> `detect: contextual` — check if any class names are composed dynamically; verify `safelist` covers them

**[MZL-006]** `transactional: mortal | marketing: mortal` — Compiled output in `build/` or `dist/` must never be hand-edited.
> `maizzle build` overwrites compiled output entirely. Manual edits to compiled files are silently discarded by the next build, creating invisible drift between source and deployed HTML.
> `detect: contextual` — advisory; check if `build/` is committed as source-of-truth rather than generated artefact

**[MZL-007]** `transactional: mortal | marketing: mortal` — Test compiled HTML output in real email clients — not only the Maizzle dev browser preview.
> The Maizzle browser preview renders in a modern browser engine. Compiled HTML must be tested in Outlook (Word engine), Gmail, and Apple Mail for cross-client issues that are invisible in browser rendering.
> `detect: contextual` — advisory; verify QA process includes real email client testing

**[MZL-008]** `transactional: venial | marketing: venial` — Verify `inlineCSS: true` and `minifyHTML: true` are set in the production config environment.
> Production config (`config.production.js`) should have CSS inlining enabled (so Tailwind classes become inline styles) and HTML minification enabled (to reduce size and eliminate whitespace gaps). These are off in development — confirm production config explicitly.
> `detect: contextual` — check `config.production.js` for `css.inline` and `minify` settings

**[MZL-009]** `transactional: venial | marketing: venial` — Set `prettify: false` in production config.
> Pretty-printed output adds newlines and indentation between table elements. Whitespace text nodes between `<td>` elements cause 4px layout gaps in some email clients (see GOTCHA-011). Production output should be compact.
> `detect: contextual` — check production config for `prettify` setting

**[MZL-010]** `transactional: venial | marketing: venial` — Set explicit `width` and `height` HTML attributes on all `<img>` elements — Tailwind width utilities alone are not sufficient for Outlook 2007–2019.
> Outlook Windows ignores CSS `width` on images. The HTML `width` attribute is the only reliable size control. Use both: `<img width="600" class="w-full" alt="...">` — CSS for responsive scaling, attribute for Outlook. Source: Campaign Monitor CSS support guide.
> `detect: contextual` — check `<img>` elements for explicit `width` and `height` HTML attributes

**[MZL-011]** `transactional: venial | marketing: venial` — Use Tailwind's `!important` utilities (prefix `!`) to override email client default styles.
> Email clients inject their own CSS resets. `!bg-white` (compiles to `background-color: #ffffff !important`) overrides Outlook's default grey body background. Standard Tailwind utilities without `!important` can be overridden by client defaults.
> `detect: contextual` — advisory; when client-default overrides are needed, use `!` prefix

**[MZL-012]** `transactional: venial | marketing: venial` — For Outlook background images, use VML — either Maizzle's `<x-bg-image>` component or manually coded VML conditionals.
> Standard CSS `background-image` is not supported in Outlook 2007–2019 (see RENDER-015). Maizzle does not abstract this automatically. The VML approach must be explicitly implemented in templates that use background images. Source: Maizzle documentation; Campaign Monitor VML guide.
> `detect: contextual` — check templates using `bg-[url(...)]` Tailwind classes or CSS `background-image` for Outlook VML fallback

**[MZL-013]** `transactional: venial | marketing: venial` — Use `x-component` (or Maizzle's component include syntax) for shared email parts.
> Duplicate header and footer HTML across templates creates divergence. Use Maizzle's component system to maintain a single source of truth for shared components.
> `detect: contextual` — check for duplicate HTML blocks (>10 lines) across templates without component includes

**[MZL-014]** `transactional: venial | marketing: venial` — Use front matter for per-template settings — subject, preheader, from name, and CSS overrides.
> Maizzle passes front matter fields into the template as `page.subject`, `page.preheader`, etc. This keeps send metadata alongside the template it describes and enables per-template `<title>` generation.
> `detect: contextual` — advisory; check if templates use front matter for metadata

**[MZL-015]** `transactional: venial | marketing: venial` — Configure `removeUnusedCSS: true` in production only. Leave it disabled in development to avoid false negatives when iterating.
> CSS removal is destructive — it strips classes not found in the template source. During development, temporarily commented-out classes or classes under construction are real and should not be removed. Source: Maizzle documentation — removeUnusedCSS.
> `detect: contextual` — check that `removeUnusedCSS` is false in local/development config and true in production

**[MZL-016]** `transactional: counsel | marketing: counsel` — Understand the layered build pipeline: Nunjucks (layout time) → Tailwind (CSS time) → inline (deploy time) → data injection (send time).
> Maizzle uses Nunjucks for template logic (`{% if %}`, `{% for %}`, `{% macro %}`). This handles layout-time logic when building the template. Per-recipient data injection (Handlebars placeholders, Liquid variables) happens at send time after Maizzle compilation. Nunjucks and Handlebars use conflicting `{{` syntax — use MJML-style approach: write Handlebars placeholders in Maizzle source and ensure Nunjucks does not evaluate them.
> `detect: contextual` — advisory; verify Handlebars/Liquid placeholders survive Maizzle compilation

**[MZL-017]** `transactional: counsel | marketing: counsel` — Start new email types from Maizzle starter templates rather than blank HTML.
> Maizzle starters include correct table structure, Outlook ghost table conditionals, meta tags (`x-apple-disable-message-reformatting`, `color-scheme`), and tested responsive patterns. Starting from blank HTML requires manually adding all these — a common source of omissions.
> `detect: contextual` — advisory

**[MZL-018]** `transactional: counsel | marketing: counsel` — PostCSS plugins that generate modern CSS (e.g. `postcss-preset-env` with CSS variable output) can introduce email-unsafe properties into the compiled output.
> PostCSS `postcss-preset-env` with `stage: 0` may transform properties in ways that produce CSS variables or calc() expressions. Audit your PostCSS plugin configuration to verify the compiled output contains only email-safe CSS. Source: PostCSS documentation.
> `detect: contextual` — review PostCSS config for plugins that may introduce CSS variables or modern transforms

---

## Patterns & Code Examples

### Production build configuration

```javascript
// config.production.js
module.exports = {
  build: {
    templates: { source: 'src/emails/', destination: { path: 'build/' } },
  },
  css: {
    inline: true,      // Inline Tailwind utilities into style attributes
    purge: true,       // Remove unused CSS classes
    shorthand: false,  // Do not merge CSS shorthands (padding: 0 8px breaks Outlook)
  },
  minify: true,        // Compact output — no whitespace between tags
  prettify: false,     // No indentation/newlines in output
  removeUnusedCSS: true,
};
```

### Table-based two-column layout (no flex/grid)

```html
<!-- Maizzle source: table layout, Tailwind for spacing and colour -->
<table width="600" cellpadding="0" cellspacing="0" border="0" class="w-full">
  <tr>
    <!--[if mso]>
    <td width="280" valign="top">
    <![endif]-->
    <td class="w-full sm:w-[280px] inline-block align-top px-3">
      <img src="https://cdn.example.com/product@2x.jpg" width="270" height="270"
           alt="Blue Widget" class="w-full block border-0" />
    </td>
    <!--[if mso]>
    </td>
    <td width="280" valign="top">
    <![endif]-->
    <td class="w-full sm:w-[280px] inline-block align-top px-3">
      <h2 class="text-lg font-bold text-gray-800 m-0 mb-2">Blue Widget</h2>
      <p class="text-sm text-gray-600 m-0 mb-4">Premium quality, 2-year warranty.</p>
      <p class="text-xl font-bold text-gray-900 m-0 mb-4">£24.99</p>
    </td>
    <!--[if mso]>
    </td>
    <![endif]-->
  </tr>
</table>
```

### VML background image with `<x-bg-image>` helper

```html
<!-- Maizzle x-bg-image component for Outlook background images -->
<x-bg-image src="https://cdn.example.com/hero@2x.jpg"
            width="600"
            height="300">
  <!-- Content here is visible in all clients; VML fills behind it in Outlook -->
  <td align="center" class="px-6 py-10">
    <h1 class="text-2xl font-bold text-white m-0">Spring Collection</h1>
  </td>
</x-bg-image>

<!-- Or manual VML for full control -->
<!--[if mso]>
<v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false"
        style="width: 600px; height: 300px;">
  <v:fill type="frame" src="https://cdn.example.com/hero@2x.jpg" />
  <v:textbox style="mso-fit-shape-to-text: true" inset="0,0,0,0">
<![endif]-->
<td align="center" style="background-image: url(https://cdn.example.com/hero@2x.jpg);
     background-size: cover; background-position: center; padding: 40px 24px;">
  <h1 style="color: #ffffff; font-family: Arial, sans-serif; font-size: 24px; margin: 0;">
    Spring Collection
  </h1>
</td>
<!--[if mso]>
  </v:textbox>
</v:rect>
<![endif]-->
```

### Tailwind safelist for dynamic classes

```javascript
// tailwind.config.js
module.exports = {
  content: ['./src/emails/**/*.html'],
  safelist: [
    // Dynamic background colours (e.g. status badges)
    'bg-green-100', 'bg-yellow-100', 'bg-red-100',
    'text-green-800', 'text-yellow-800', 'text-red-800',
    // Pattern: all text-* colour utilities used in status components
    { pattern: /^(bg|text)-(green|yellow|red|blue)-(100|800)$/ },
  ],
  theme: { /* ... */ },
};
```

### Front matter per-template metadata

```html
---
subject: "Your order #{{ orderId }} has shipped"
preheader: "Arriving Friday. Track your parcel."
from:
  name: "Acme Shipping"
  email: "shipping@acme.com"
---

<!DOCTYPE html>
<html lang="en">
<head>
  <title>{{ page.subject }}</title>
  <meta name="description" content="{{ page.preheader }}">
  ...
</head>
```

## Support Matrix

| Maizzle Feature | Gmail | Outlook 2007–19 | Outlook new | Apple Mail | Yahoo Mail |
|----------------|:---:|:---:|:---:|:---:|:---:|
| Table layout | ✅ | ✅ | ✅ | ✅ | ✅ |
| Inlined Tailwind CSS | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tailwind `flex`/`grid` | Partial | ❌ | ✅ | ✅ | ❌ |
| VML background image | N/A | ✅ | N/A | N/A | N/A |
| CSS background image (non-Outlook) | ✅ | ❌ | ✅ | ✅ | ✅ |
| `@media` responsive | ✅ | ❌ | ✅ | ✅ | Partial |
| Nunjucks template logic | N/A (compile-time) | N/A | N/A | N/A | N/A |

## Known Afflictions

**Tailwind JIT tree-shaking removes dynamic classes** — Tailwind's JIT compiler scans template source for class names. Classes composed dynamically in Nunjucks (`"bg-" + statusColour`) are invisible to the scanner and their CSS is purged. Always add dynamic class patterns to the `safelist` in `tailwind.config.js`.
Affects: All Maizzle versions using Tailwind JIT (v3+). Source: Tailwind CSS documentation — safelist.

**Nunjucks conflicts with Handlebars `{{` syntax** — Both Nunjucks and Handlebars use double-brace delimiters. If a Maizzle template contains Handlebars placeholders (`{{firstName}}`), Nunjucks attempts to evaluate them at compile time and emits empty string or an error. Use Nunjucks `{% raw %}` blocks around Handlebars placeholders, or switch to a different placeholder syntax (`<%= firstName %>`).
Affects: Projects using Maizzle + Handlebars hybrid pipeline. Source: Nunjucks documentation.

**Maizzle v5 Vite dev server differs from v4 Browsersync** — Maizzle v5 replaced Browsersync with Vite for the development server. Teams migrating from v4 may find local preview behaviour changed — notably, Vite's hot module replacement works differently from Browsersync's full-page reload. Test preview configuration after migration.
Affects: Maizzle v5, migrating from v4. Source: Maizzle v5 changelog.

**CSS shorthand merging breaks Outlook padding** — Some PostCSS plugins or Maizzle's `css.shorthand: true` setting merge `padding-top`, `padding-right`, etc. into `padding: 0 8px 0 8px`. Outlook 2007–2019 has inconsistent support for CSS padding shorthand (see RENDER-020). Keep `css.shorthand: false` in production config.
Affects: Maizzle with PostCSS shorthand plugins. Source: Campaign Monitor CSS support guide.

## Sources

1. **Maizzle Framework** — https://maizzle.com / https://github.com/maizzle/framework — Documentation, changelog, starter templates.
2. **Tailwind CSS** — https://tailwindcss.com — Safelist configuration, utility reference, v4 migration guide.
3. **caniemail.com** — https://www.caniemail.com — Email client CSS support data.
4. **Campaign Monitor CSS Guide** — https://www.campaignmonitor.com/css/ — Table layout, VML, Outlook padding.
5. **Nunjucks Documentation** — https://mozilla.github.io/nunjucks/ — Template logic, raw blocks, macros.
