import { defineCollection, z } from 'astro:content';

const cookieGuard = (val: string | undefined) => {
  if (!val) return true;
  const valLower = val.toLowerCase();
  // Block programmatic cookie/tracking patterns only; plain words like
  // "analytics" are legal in copy text.
  // Keep in sync with the cookie_indicators list in
  // projects/agent/src/agent/content_safety.py (the edit-time guard).
  const forbidden = [
    "document.cookie",
    "cookiestore",
    "set-cookie",
    "set_cookie",
    "cookies.set",
    "cookies.get",
    "cookies.delete",
    "gtag(",
    "gtag.js",
    "googletagmanager",
    "google-analytics.com"
  ];
  return !forbidden.some(indicator => valLower.includes(indicator));
};

const pagesCollection = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string().refine(cookieGuard, {
      message: "Privacy Constraint Violated: 'title' cannot contain cookie-collecting code or tracking references."
    }),
    description: z.string().optional().refine(cookieGuard, {
      message: "Privacy Constraint Violated: 'description' cannot contain cookie-collecting code or tracking references."
    }),
    image: z.string().optional(),
    pageLayout: z.string().optional(),
    // The [...slug] route forwards these to Layout.astro to suppress the
    // automatic settings-driven header/footer on a page that supplies its own
    // <Navbar>/<Footer> section. They MUST be declared here or Astro's
    // content-collection validation strips them from page.data, silently
    // turning the frontmatter flag into a no-op (two stacked headers/footers).
    hideHeader: z.boolean().optional(),
    hideFooter: z.boolean().optional(),
  }),
});

export const collections = {
  pages: pagesCollection,
};
