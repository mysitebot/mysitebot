You are reviewing a change that an automated website-editing assistant ("Sam")
made to a static Astro site, to decide whether it satisfied the user's request.

The current directory contains the evidence:

- scenario.json — the scenario definition and its checks
- response.txt — Sam's reply to the user (the LAST reply, for multi-turn runs)
- transcript.json — the full conversation, one {role, text} entry per turn
  (present only for multi-turn scenarios; roles: user / system / agent).
  For multi-turn criteria about SEQUENCING (e.g. "published only after the
  user's go-ahead"), judge from this transcript, not response.txt alone.
- tool_calls.json — the tools Sam invoked, in order (across ALL turns)
- diff.patch — every file change Sam made to the site workspace
- build.log — Astro build output (when a build ran)
- screenshot*.png — full-page screenshots of the built site after the change

USER REQUEST:
{{user_request}}

ACCEPTANCE CRITERIA:
{{judge_criteria}}

Read the evidence — including looking at the screenshots — and decide whether
the change satisfies the request AND makes sense: no broken layout, no
gibberish or placeholder content, no unrelated collateral edits.

Reply with ONLY a JSON object — no prose before or after, no markdown fences:

{"passed": true, "reasoning": "<one short paragraph>", "issues": ["<specific problem>"]}

Set "passed" to false if anything material is wrong; list each concrete
problem in "issues". An empty issues list is required when passed is true.
