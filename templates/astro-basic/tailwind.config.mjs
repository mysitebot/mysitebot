/** @type {import('tailwindcss').Config} */
import { readFileSync, existsSync } from 'fs';
import { parse as parseYaml } from 'yaml';

// The site's primaryColor (content/settings.yaml) re-themes the template at
// build time by regenerating the indigo palette the components use: shade 600
// is the exact brand color and the other steps are derived in HSL space, so
// every hover/focus/ring/opacity variant follows the brand automatically.
// Missing or invalid settings keep Tailwind's default indigo palette.
const DEFAULT_PRIMARY = '#4f46e5';

function hexToHsl(hex) {
  let c = hex.replace('#', '');
  if (c.length === 3) c = c.split('').map((ch) => ch + ch).join('');
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  switch (max) {
    case r: h = ((g - b) / d + (g < b ? 6 : 0)); break;
    case g: h = (b - r) / d + 2; break;
    default: h = (r - g) / d + 4;
  }
  return [h * 60, s * 100, l * 100];
}

function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const v = l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return Math.round(255 * v).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function buildPalette(hex) {
  const [h, s] = hexToHsl(hex);
  const ladder = { 50: 97, 100: 94, 200: 86, 300: 76, 400: 65, 500: 55, 600: 47, 700: 39, 800: 32, 900: 26, 950: 16 };
  const palette = {};
  for (const [shade, l] of Object.entries(ladder)) palette[shade] = hslToHex(h, s, l);
  palette[600] = hex; // the components' primary shade renders the exact brand color
  return palette;
}

let brandPalette = null;
try {
  if (existsSync('./content/settings.yaml')) {
    const settings = parseYaml(readFileSync('./content/settings.yaml', 'utf-8'));
    const value = settings?.site?.primaryColor;
    if (
      typeof value === 'string' &&
      /^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/.test(value) &&
      value.toLowerCase() !== DEFAULT_PRIMARY
    ) {
      brandPalette = buildPalette(value);
    }
  }
} catch {
  // A malformed settings.yaml must never break the build — keep the defaults.
}

export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: brandPalette ? { colors: { indigo: brandPalette } } : {},
  },
  plugins: [],
}
