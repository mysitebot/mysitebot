import { getCollection, type CollectionEntry } from 'astro:content';

export type Post = CollectionEntry<'posts'>;

export const POSTS_PER_PAGE = 9;

/** Draft posts build only on the draft branch, where the pipeline sets this. */
const includeDrafts = () => process.env.MYSITEBOT_INCLUDE_DRAFTS === '1';

/** Every route reads posts through here so draft rules and ordering exist once. */
export async function getPublishedPosts(): Promise<Post[]> {
  const posts = await getCollection('posts');
  return posts
    .filter((post) => includeDrafts() || !post.data.draft)
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());
}

/** URL-safe form of a tag. `Web Design` and `web-design` collapse together. */
export function tagSlug(tag: string): string {
  return tag
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Groups posts by tag slug. Tags colliding after slugification share one entry;
 * the first spelling encountered (newest post first) supplies the label.
 */
export function groupByTag(posts: Post[]): Map<string, { label: string; posts: Post[] }> {
  const groups = new Map<string, { label: string; posts: Post[] }>();
  for (const post of posts) {
    for (const tag of post.data.tags) {
      const slug = tagSlug(tag);
      if (!slug) continue;
      const existing = groups.get(slug);
      if (existing) existing.posts.push(post);
      else groups.set(slug, { label: tag, posts: [post] });
    }
  }
  return groups;
}

export function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}
