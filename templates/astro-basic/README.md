# mysite.bot Astro Template

This is the **AI-managed static site template** used by the mysite.bot agent.

## Structure

```
content/          ← AI agent edits ONLY these files
  home.md         ← Page content (markdown)
  settings.yaml   ← Site config (name, tagline, colors, contact)

src/              ← SEALED — do not edit
  content/
    config.ts     ← Astro Content Collection schemas
  pages/
    index.astro   ← Renders content/ data, not editable by agent

.gitlab-ci.yml    ← Builds on push to main, deploys to GitLab Pages
```

## Rules

- The AI agent may **only** create/edit files inside `content/`.
- `src/` is off-limits and must not be modified by any automated process.
- Merging to `main` triggers an automatic GitLab Pages deploy.
