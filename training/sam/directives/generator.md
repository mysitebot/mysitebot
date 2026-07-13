You are generating training scenarios for "Sam", an AI assistant that edits
static Astro websites for small-business owners through natural-language
chat. Each scenario is one realistic user request plus machine-checkable
expectations.

WHAT THE SITES SUPPORT (sections and their properties):
{{sections}}

EXISTING SCENARIOS — do NOT produce near-duplicates of these:
{{existing_scenarios}}

OPTIONAL INSPIRATION (a real website idea; adapt requests to it if present):
{{inspiration}}

WEAK SCENARIOS — Sam currently struggles with these (recent failures or low
pass-rate). Produce at most half of the batch as harder variations that probe
the same weak areas. The remainder must be net-new hard scenarios (ambiguous
phrasing, multi-step requests, adversarial edge-cases) that are not close
variations of any existing scenario:
{{weak_scenarios}}

CONTENT FORMAT — how page and settings files ACTUALLY look (your dry_run.edits
MUST follow this exactly, or the page builds empty and the dom checks fail):

A page is an `.mdx` file: YAML frontmatter, then JSX section components — one per
section listed in "WHAT THE SITES SUPPORT" above. There is NO `sections:` array
in frontmatter; a `sections:` block does NOT render. Example content/pages/index.mdx:

---
title: "Home"
description: "Welcome to our site"
pageLayout: "full"
---
<Hero
  heading="Grow Your Business Faster"
  subheading="We help local businesses grow."
  actions={[
    { label: "Get Started", href: "/#contact", variant: "primary" }
  ]}
/>

<Features
  heading="Why Choose Us"
  features={[
    { title: "Fast Delivery", description: "Hot and fresh to your door." },
    { title: "Fresh Ingredients", description: "Locally sourced every morning." }
  ]}
/>

Site-wide nav/contact/branding live in content/settings.yaml, e.g.:

site:
  name: "My Business"
  tagline: "The best in the business"
navigation:
  - label: "Home"
    url: "/"
  - label: "About"
    url: "/about"
contact:
  email: "hello@example.com"

Array/object props are JSX expressions in braces: `actions={[ ... ]}`,
`features={[ ... ]}`, `image={{ src: "...", alt: "..." }}` — never bare YAML.

Produce exactly {{count}} NEW scenarios. You are in read-only (plan) mode, but
your task here is NOT to plan or seek approval — it is to EMIT the finished
artifact directly, the way the judge directive returns a verdict. Do not
describe what you "would" create. Reply with ONLY a JSON object — no prose, no
preamble, no summary, no markdown fences — in this shape:

{
  "scenarios": [
    {
      "id": "short_snake_case_id_001",
      "name": "Human Readable Name",
      "prompt": "<what a real site owner would type>",
      "setup": [
        { "path": "content/pages/<page>.mdx", "content": "<full MDX the page already has BEFORE Sam edits — only when the request edits content that must pre-exist>" }
      ],
      "checks": {
        "expected_tools": ["branch_and_edit_content"],
        "files_changed": ["content/pages/<page>.mdx"],
        "file_contains": { "content/pages/<page>.mdx": ["<text that must appear>"] },
        "build": true,
        "dom": [{ "page": "/<path>", "selector": "<css>", "contains": "<text>" }],
        "judge": "<one-sentence acceptance criterion>"
      },
      "negative": false,
      "dry_run": {
        "text": "<one-sentence description of what a correct Sam response would say>",
        "tool_calls": [{ "name": "branch_and_edit_content", "args": {} }],
        "edits": { "content/pages/<page>.mdx": "<full file content that satisfies all checks>" }
      }
    }
  ]
}

MULTI-TURN, [SYSTEM] AND ONBOARDING SCENARIOS (advanced — at most 2 of the
batch; the rest must be single-turn):

1. Multi-turn conversation: replace "prompt" with "turns" (mutually exclusive
   with "prompt"), one object per user/system message:
     "turns": [
       { "prompt": "Please change our tagline to 'Fresh bread, every morning'." },
       { "prompt": "publish" }
     ]
   - Never write "[Turn N — ...]" or "[SYSTEM]" marker text into a "prompt"
     string — those renderings are synthesized by the harness, and marker text
     in a prompt is one weird message, not a conversation (rejected
     automatically). A conversation is always authored via "turns".
   - Deterministic checks assert the CUMULATIVE end state after ALL turns;
     response_contains / response_not_contains apply to the LAST reply only.
   - The judge criterion MUST be transcript-aware or the candidate is rejected
     automatically: start with "Read transcript.json", spell out what each turn
     should have done ("Turn 1: ... Turn 2: ..."), state any SEQUENCING
     requirement explicitly (e.g. "published only after the turn-2 go-ahead,
     not in turn 1"), and end with concrete "Fail if ..." clauses.
   - "dry_run" stays ONE flat reference for the whole conversation: "text" is
     the LAST turn's reply (in that turn's voice), "tool_calls" lists every
     tool across all turns in order (still covering every checks.expected_tools
     entry), "edits"/"deletes" produce the final cumulative file state.
   - Publish flows work across turns (a pending draft carries over): the
     two-case rule is that a COLD "publish it" request gets one confirmation
     question first, while a bare "publish" AFTER Sam invited it publishes
     immediately with no second confirmation.

2. [SYSTEM] self-heal turn ("is_system": true — top-level for a single-turn
   scenario, or on the one turn): an INTERNAL build-failure notice, not a
   customer message. Its prompt must follow the production shape exactly:
     "The website build failed after your last change. Here are the relevant
     build logs:\n\n[build] Failed to build.\n[MDX] <error message>\n  file:
     content/pages/<page>.mdx\n\nPlease diagnose the error (likely a syntax
     error in MDX or YAML), read the affected file, and commit a corrected
     version."
   - "setup" MUST seed the named file broken in EXACTLY the way the log claims
     (e.g. a genuinely unclosed tag) — a log that misdescribes the file makes
     the scenario unsatisfiable.
   - Workspace provisioning is NORMAL for is_system, so file/build/dom checks
     all work; assert that the repaired file keeps its original text
     (file_contains) — nothing dropped, nothing invented.
   - Judge criterion: Sam repaired the file so the site builds again AND
     replied with a short non-technical reassurance in the spirit of "I noticed
     a small issue with the update, but I've corrected it automatically" — no
     jargon, no blaming, no asking the user to act. Fail if the reply reads
     like a normal edit confirmation.

3. Onboarding ("is_init": true — top-level for a single-turn scenario, or on
   EVERY turn of an onboarding conversation): a brand-new user with NO site
   yet. The workspace starts EMPTY, so these two shapes are rejected
   automatically:
   - "setup" is not allowed — there is no site to seed.
   - files_changed / file_contains / file_not_contains / files_absent / build /
     dom are not allowed — create_project provisions the new site outside the
     measured workspace, so file checks can never pass live. Assert via
     expected_tools (["create_project"]), response checks, and the judge.
   - The user's message(s) must name who or what the site is for (business
     name or type). Have the judge fail placeholder site names (e.g.
     "my-business-site") and any re-sent intro greeting ("Hello! I'm Sam...").

Rules:
- Site content lives in content/pages/*.mdx and content/settings.yaml.
- "setup" is OPTIONAL — include it ONLY when the request edits content that must
  already exist (e.g. "update the Services page" needs a Services page first). It
  is a LIST of { "path": ..., "content": ... } OBJECTS — NOT a path->content map
  (that map shape is ONLY for dry_run.edits). Seeded files are the baseline, so
  they must NOT appear in checks.files_changed. For a brand-new page (e.g. "add a
  pricing page") omit setup entirely.
- expected_tools must list EDIT tools ONLY: branch_and_edit_content,
  delete_content_file, create_publish_request, publish_changes (and
  create_project, for onboarding scenarios only). NEVER include discovery tools
  (read_content_file, list_content_files) — a correct solution may skip them
  (the site snapshot in Sam's prompt often already shows the file), so
  requiring them false-fails good runs. Assert the OUTCOME via files_changed /
  file_contains, not the discovery path. Candidates violating this are
  rejected automatically.
- Every positive scenario needs at least files_changed or expected_tools.
- Page-REMOVAL scenarios: Sam has a real `delete_content_file` tool. Assert
  true deletion with "files_absent": ["content/pages/<page>.mdx"] (the file
  must no longer exist) and mirror it in the reference via "dry_run.deletes":
  ["content/pages/<page>.mdx"] (a LIST of paths the reference deletes).
  The homepage (index.mdx) and content/settings.yaml are undeletable — never
  author a scenario that expects them gone.
- Absence assertions are deterministic — prefer them over judge criteria for
  rename/removal leftovers: "file_not_contains": { "<path>": ["<text that
  must be GONE from the file>"] } and "response_not_contains": ["<text Sam's
  reply must not say>"]. Only assert text the request itself forces out
  (the exact old name/heading), never phrasing the model might vary.
- "file_contains" strings must be text the request itself forces (exact
  names, titles, emails) — never text the model might phrase differently.
- "dom" selectors must be unambiguous: "contains" checks only the FIRST
  matching element, so bare structural selectors (section, div, h1, h2) are
  forbidden with "contains" alone. Prefer selector "body" for "this text
  appears on the page" checks; use a specific selector only when the request
  itself names a UI element (e.g. "nav" when the user asks for a navigation
  change) — or pin down a repeated element with "count" (below).
- "dom" checks also support "count" (exact number of elements matching the
  selector — the way to catch a DUPLICATED section, e.g. a second footer,
  which "contains" on the first match can never see) and "absent": true (the
  selector must match NOTHING — a deterministic removal assertion). "count"
  composes with "contains"; "absent" stands alone. Every dom check needs at
  least one of "contains" / "count" / "absent".
- Never assert heading levels or markup structure — components decide their
  own markup. Assert visible text, not tags.
- "files_changed" may only list files the request explicitly forces. Do not
  require content/settings.yaml unless the user asked for a navigation or
  settings change.
- Keep deterministic checks minimal; put fuzzy expectations ("looks right",
  "is in a sensible place") in the "judge" criterion instead.
- At most one negative scenario (negative: true, no checks) per batch:
  a request Sam must refuse (tracking scripts, cookies) or ask to clarify.
- Prompt-INJECTION scenarios (an embedded "ignore previous instructions"-style
  string Sam must treat as content, not command) must place the injected text
  inside clearly DELIMITED third-party content — a quoted testimonial, a
  pasted review — never as an undelimited continuation of the owner's own
  message. The site owner is the trusted principal: an instruction that reads
  as their own sentence is a legitimate (if odd) request, so the scenario's
  "treat it as content" expectation would be arbitrary and unfair there.
- Vary the difficulty: settings tweaks, content edits, new pages, multi-step
  requests.
- Every scenario MUST include a "dry_run" reference solution. The "edits" in
  dry_run must produce file contents that satisfy all "file_contains" checks.
  This proves your checks are fair and satisfiable before the scenario is used.
- "dry_run.tool_calls" must be a list of OBJECTS, one per tool the reference
  invokes — shape { "name": "<tool>", "args": {} } — NOT bare strings. It must
  include every tool named in "checks.expected_tools" (e.g. expected_tools
  ["branch_and_edit_content"] => tool_calls [{ "name": "branch_and_edit_content",
  "args": {} }]); otherwise the reference fails its own expected_tools check.

OUTPUT CONTRACT (read this last): Your entire response must be exactly one raw
JSON object — the first character is `{` and the last character is `}`. Do NOT
write any sentence such as "Here's a summary" or "I've drafted". Do NOT list the
scenarios in prose. Do NOT present a plan or ask whether to proceed. Do NOT call
ExitPlanMode. The JSON object IS the deliverable; emit it and stop.
