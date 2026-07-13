import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import mdx from '@astrojs/mdx';

// ASTRO_BASE lets the same build work on GitLab Pages project sites
// (/<project-name>/) and on local backend previews (/preview/<id>/).
const base = process.env.ASTRO_BASE || '/';

export default defineConfig({
  base,
  integrations: [tailwind(), mdx()],
  vite: {
    // On Cloud Run node_modules is a symlink into the read-only image; keep the
    // Vite cache in the writable workspace instead of node_modules/.vite.
    cacheDir: process.env.VITE_CACHE_DIR || 'node_modules/.vite',
  },
  // Agent MUST NOT touch src/. Content lives in content/ only.
});
