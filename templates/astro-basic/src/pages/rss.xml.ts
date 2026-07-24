import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

/**
 * The feed is deliberately built from the collection directly rather than from
 * getPublishedPosts(): a feed is a public, cacheable artifact, so unpublished
 * drafts must never appear in it even on the draft preview build.
 */
export async function GET(context) {
  const posts = (await getCollection('posts'))
    .filter((post) => !post.data.draft)
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());

  return rss({
    title: 'Blog',
    description: 'Latest posts and updates.',
    site: context.site ?? new URL(context.url.origin),
    items: posts.map((post) => ({
      title: post.data.title,
      pubDate: post.data.date,
      description: post.data.excerpt ?? post.data.description ?? '',
      link: `/blog/${post.slug}/`,
    })),
  });
}
