// True for an absolute external URL (http/https) — such nav links open in a
// new tab so a visitor following one (e.g. an external blog) doesn't lose the site.
export const isExternal = (url: string) => /^https?:\/\//i.test(url);

export const resolvePath = (path: string) => {
  if (!path) return '';
  // Pass through absolute URLs, protocol-relative URLs, in-page anchors, and
  // non-http schemes (mailto:, tel:) unchanged — only true site paths get the
  // base prefix. This makes it safe to wrap every src/href indiscriminately.
  if (/^(https?:|\/\/|#|mailto:|tel:)/i.test(path)) return path;
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  // Idempotent: a path already carrying the base prefix is returned unchanged,
  // so a parent component passing an already-resolved href into a child that
  // resolves again (e.g. Button) never double-prefixes. With the default
  // base '/', `base` is '' and prefixing is a no-op anyway.
  if (base && (path === base || path.startsWith(`${base}/`))) return path;
  return `${base}${path.startsWith('/') ? '' : '/'}${path}`;
};
