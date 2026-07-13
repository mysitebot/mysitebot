# Atomic UI Components (`src/components/ui/`)

This directory contains the common, low-level atomic UI elements used to build high-level page sections in MYSITEBOT templates. These elements are designed to enforce design consistency across the site.

> [!NOTE]
> These components are strictly for internal section development. They are not exposed directly to MDX pages.

## Components List

### 1. `Button.astro`
Renders an anchor link (`<a>`) when `href` is supplied, or a `<button>` element otherwise. `href` values are passed through `resolvePath`, so callers must NOT pre-resolve them.

**Props:**
* `href?: string` - Destination URL. If set, renders as a link.
* `type?: 'button' | 'submit' | 'reset'` - Native button type attribute (default: `button`).
* `variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'unstyled'` - Button styling theme.
  * `primary`: Indigo background, white text, premium shadow.
  * `secondary`: White background, grey border, dark text.
  * `success`: Green background, white text.
  * `danger`: Red background, white text.
  * `unstyled`: Structural styles only (padding/rounded/font/transition), NO colors — supply your own complete color classes via `class`. Use this whenever you customize colors: appended classes cannot reliably override a variant's colors (Tailwind resolves conflicts by stylesheet order, not class order).
* `class?: string` - Extra Tailwind classes to append.

**Usage:**
```astro
import Button from './ui/Button.astro';

<Button href="/contact">Get Started</Button>
```

---

### 2. `Input.astro`
A wrapper around the standard HTML `<input>` tag, pre-styled for forms.

**Props:**
* `type?: string` - Standard input type (e.g. `text`, `email`, `tel`, etc., default: `text`).
* `placeholder?: string` - Input placeholder text.
* `required?: boolean` - Marks the input as required.
* `name?: string` - The form control name.
* `class?: string` - Extra Tailwind classes to append.

---

### 3. `Textarea.astro`
A wrapper around the standard HTML `<textarea>` tag, pre-styled for multiline text inputs.

**Props:**
* `rows?: number | string` - Number of visible text lines (default: `5`).
* `placeholder?: string` - Input placeholder text.
* `required?: boolean` - Marks the textarea as required.
* `name?: string` - The form control name.
* `class?: string` - Extra Tailwind classes to append.
