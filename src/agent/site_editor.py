import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol
from agent.llm import LLMClient, LLMTransientError, Usage, from_settings
from agent.prompts import base_system_instruction, onboarding_wizard_instruction
from agent.providers.git.base import GitProvider
from agent.media_search import MediaSearch
from agent.toolbox import READ_TRUNCATION_LIMIT, build_tools  # noqa: F401  (READ_TRUNCATION_LIMIT re-exported: the cap contract test imports it from here)
import logging

logger = logging.getLogger(__name__)

# How many trailing conversation-log entries are replayed into the model's
# message history each turn (the older tail lives in the rolling summary).
HISTORY_WINDOW = 20

# CURRENT SITE STATE prompt block caps: at most this many files are listed and
# settings.yaml is truncated beyond this many characters, so an oversized site
# cannot inflate the prompt (and LLM input cost) on every future turn.
MAX_LISTED_FILES = 50
SETTINGS_CHAR_CAP = 4000

# Attempts at producing an honest, non-empty final reply (the empty /
# fabricated-edit regeneration loop below — distinct from LLMClient's own
# transient-retry budget).
REPLY_ATTEMPTS = 3


class EditorStore(Protocol):
    """The store surface the editor duck-types against. Any object with these
    five async methods works (the api's Store facade, the Sam harness's
    in-memory store, ...); `store=None` means store-less (CLI) mode, where the
    publish flow is not offered at all."""

    async def get_project(self, project_id: str) -> Optional[Dict[str, Any]]: ...

    async def save_project(self, project_id: str, data: Dict[str, Any]) -> None: ...

    async def get_user_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...

    async def get_conversation_log(self, session_id: str) -> Optional[List[Dict[str, Any]]]: ...

    async def is_locked(self, project_id: str) -> bool: ...


@dataclass
class TurnContext:
    """Per-turn mutable state shared with subclass hooks/tools so SaaS tools can
    switch the active project mid-turn exactly as the inline closures did."""
    active_project_id: str
    active_provider_id: str
    turn_branch: str | None = None
    pipeline_triggered: bool = False
    # The files whose reads were truncated — a full-file rewrite of a partially
    # read file would silently delete the unseen tail.
    truncated_reads: set = field(default_factory=set)


# Phrases the model is scripted to say right after performing an edit (see the
# Edit Loop in prompts.py). Cheap models sometimes parrot them straight from the
# conversation history without calling any tool — a reply matching these while
# no tool ran this turn is a fabricated success. Future/progressive-tense
# announcements ("I'm adding...", "I'll add...") are the same failure mode:
# Sam narrates work it never started (seen live on newsletter_fields_001).
# "publish" is deliberately NOT in the verb lists — a publish confirmation
# legitimately promises future action before any tool runs.
_EDIT_VERB_CLAIMS = (
    r"\bI'?ve\s+(?:just\s+)?(?:updated|changed|added|removed|replaced|set|adjusted)\b"
    r"|\bI(?:'?m|\s+am)\s+(?:now\s+)?(?:updating|changing|adding|removing|replacing|setting|adjusting|creating|building)\b"
    r"|\bI(?:'?ll|\s+will)\s+(?:now\s+)?(?:update|change|add|remove|replace|set|adjust|create|build)\b"
)

# The scripted post-edit forms, anchored to first person so honest replies are
# never flagged: "I've double-checked — your number is correct" (a verification
# ANSWER) and "No changes are ready yet" (a negation) must not match; only the
# fresh-edit script ("I'm double-checking everything now", "your changes are
# ready") does.
_SCRIPTED_CLAIMS = (
    r"\bI(?:'?m|\s+am)\s+(?:now\s+)?double[-\s]?checking\b"
    r"|\bI'?ve\s+(?:just\s+)?double[-\s]?checked\s+and\s+(?:updated|changed|added|removed|replaced|set|adjusted|made|saved|applied)\b"
    r"|(?<!\bno )\b(?:your\s+|the\s+)?changes?\s+(?:are|is)\s+(?:now\s+)?ready\b"
)

_EDIT_CLAIM_RE = re.compile(_EDIT_VERB_CLAIMS + "|" + _SCRIPTED_CLAIMS, re.IGNORECASE)

# Edit-verb announcements alone: these stay a lie even on a turn that ran
# read-only tools (reading a file is not "adding a section").
_EDIT_VERB_CLAIM_RE = re.compile(_EDIT_VERB_CLAIMS, re.IGNORECASE)

# The narrow subset that ONLY legitimately appears immediately after a fresh
# edit — safe to treat as a hard lie when no tool ran (unlike "I've updated",
# which can truthfully recap a previous turn's work).
_SCRIPTED_EDIT_CLAIM_RE = re.compile(_SCRIPTED_CLAIMS, re.IGNORECASE)

# Tools that only inspect state. A turn whose tool calls were all read-only did
# real (honest) work even though pipeline_triggered stays False — verification
# phrasing after an actual read must not be treated as a fabricated edit.
_READ_ONLY_TOOLS = frozenset({
    "check_project_availability",
    "list_content_files",
    "read_content_file",
    "search_media_library",
    "show_settings_page",
    "show_website_status",
    "get_section_reference",
})


class AgentSiteEditor:
    """
    Self-contained, reusable Astro site editor over any OpenAI-compatible LLM.
    Binds editing tools dynamically to any GitProvider (Local or GitLab).
    """
    def __init__(
        self,
        *,
        git_provider: GitProvider,
        session_id: str = "default_session",
        api_key: str | None = None,
        model: str | None = None,
        store: "EditorStore | None" = None,
        media_search: "MediaSearch | None" = None,
        llm: "LLMClient | None" = None,
    ):
        self.git_provider = git_provider
        self.session_id = session_id
        self.store = store
        self.media_search = media_search
        # Single source of truth for chat: an injected client (tests) wins;
        # otherwise build one from settings with this turn's model/key.
        self._llm = llm or from_settings(model=model, api_key=api_key)

    def _extra_tools(self, ctx: "TurnContext") -> list:
        """SaaS subclasses add their wizard-gated tools here (account management,
        multi-site, destructive). Base agent has none."""
        return []

    def _extra_always_tools(self, ctx: "TurnContext") -> list:
        """SaaS subclasses add tools here that must stay available in EVERY mode,
        including the onboarding wizard (e.g. email linking). Base agent has none."""
        return []

    async def _before_create_project(self, name: str, ctx: "TurnContext") -> Dict[str, Any] | None:
        """BEFORE provisioning. SaaS: entitlement cap + idempotent 'already exists → switch'.
        Returning a dict short-circuits create_project (no repo provisioned); None = proceed."""
        return None

    async def _after_create_project(self, name: str, result: Dict[str, Any], ctx: "TurnContext") -> Dict[str, Any] | None:
        """AFTER provisioning. SaaS: persist project + alias + switch active project.
        Returning a dict overrides the success return; None = base builds the standard reply."""
        return None

    async def _save_project_with_alias(self, store_project_id: str, project_data: Dict[str, Any]) -> None:
        """Persists a project and an alias record keyed by the provider's project id,
        so webhooks (which only know the provider id) can resolve back to the project."""
        if not self.store:
            return
        await self.store.save_project(store_project_id, project_data)
        provider_id = project_data.get("provider_project_id")
        if provider_id:
            await self.store.save_project(f"gl_{provider_id}", {
                "project_id": f"gl_{provider_id}",
                "alias_for": store_project_id
            })

    async def _pending_draft_branch(self, ctx: "TurnContext") -> str | None:
        """The branch of the open (unpublished) publish request, if any.
        All reads and edits target this branch until it is published, so
        consecutive edits stack instead of silently forking off main."""
        if not self.store:
            return None
        proj = (await self.store.get_project(ctx.active_project_id)) or {}
        if proj.get("pending_mr_iid") and proj.get("pending_mr_branch"):
            return proj["pending_mr_branch"]
        return None

    async def _read_ref(self, ctx: "TurnContext") -> str:
        # Same-turn edits must be visible to subsequent reads even before a
        # publish request pins the draft branch in the store.
        return (await self._pending_draft_branch(ctx)) or ctx.turn_branch or "main"

    async def run(self, prompt: str, project_id: str, is_init: bool = False, is_system: bool = False) -> Dict[str, Any]:
        # Internal Markers (protected from user spoofing)
        SYSTEM_MARKER = "[SYSTEM]"
        INIT_MARKER = "[INIT]"

        # Scrub user input of internal markers to prevent spoofing. Loop to a
        # fixpoint: a single pass lets nested spoofs ("[SYS[SYSTEM]TEM]")
        # reassemble a marker from the halves left behind.
        clean_prompt = prompt
        while SYSTEM_MARKER in clean_prompt or INIT_MARKER in clean_prompt:
            clean_prompt = clean_prompt.replace(SYSTEM_MARKER, "").replace(INIT_MARKER, "")
        clean_prompt = clean_prompt.strip()

        # Onboarding mode is decided by the caller (persisted "onboarded" flag),
        # never by log emptiness — the log is cleared after summarization.
        is_initial_wizard = is_init

        # Assemble the final prompt with privileged markers
        final_prompt = clean_prompt
        if is_system:
            final_prompt = f"{SYSTEM_MARKER} {final_prompt}"
        if is_init and not clean_prompt:
            final_prompt = INIT_MARKER

        # The store key of the active project and the id the git provider understands.
        # These are updated by create/switch tools so later calls in the same turn
        # target the right repository. Held on a per-turn context object so the
        # SaaS subclass's tools/hooks can switch the active project mid-turn.
        ctx = TurnContext(active_project_id=project_id, active_provider_id=project_id)
        if self.store:
            proj_record = await self.store.get_project(project_id)
            if proj_record and proj_record.get("provider_project_id"):
                ctx.active_provider_id = str(proj_record["provider_project_id"])

        # Build dynamic System Instruction. Without a store there is no
        # pending-draft record to publish from, so the publish narrative is
        # dropped along with the publish tools (see build_tools).
        publish_enabled = self.store is not None
        base_instruction = base_system_instruction(include_publish=publish_enabled)
        if is_initial_wizard:
            base_instruction += onboarding_wizard_instruction(include_publish=publish_enabled)

        # Volatile, per-turn context (the rolling summary + a live site snapshot)
        # is appended AFTER the stable base instruction + section reference,
        # never before it. Gemini 2.5 implicit prompt caching keys on the leading
        # token prefix and refunds 75% of the cached tokens, so the large block
        # that is byte-identical across every turn and every user
        # (BASE_SYSTEM_INSTRUCTION, which now ends with the compact SECTION_INDEX
        # rather than the full SECTIONS.md) must stay at the very front. A
        # per-session summary prepended here would shift that prefix and evict it
        # from the cache on every turn; keeping it last matches Google's guidance
        # to "keep the start of the request the same and put what changes at the
        # end".
        final_instruction = base_instruction
        context_block = ""
        if self.store:
            user_session = (await self.store.get_user_session(self.session_id)) or {}
            if user_session.get("conversation_summary"):
                context_block += (
                    "\n\n---\n\nSUMMARY OF PREVIOUS INTERACTION:\n"
                    + user_session["conversation_summary"]
                )

        # Inject the current site state so the agent never edits blind.
        site_state = await self._build_site_state(ctx.active_provider_id, draft_branch=await self._pending_draft_branch(ctx))
        if site_state:
            context_block += site_state
        final_instruction += context_block

        # Build the conversation history so the agent remembers previous turns.
        # The caller appends the current user message to the log before invoking us,
        # so we drop that trailing entry and pass the current message separately.
        history: list = []
        if self.store:
            log = (await self.store.get_conversation_log(self.session_id)) or []
            # The caller appends the current inbound message (user OR system turn)
            # before invoking us — drop it here, it is passed separately below.
            if log and log[-1].get("role") != "agent":
                log = log[:-1]
            for entry in log[-HISTORY_WINDOW:]:
                entry_text = (entry.get("text") or "").strip()
                if not entry_text:
                    continue
                role = "assistant" if entry.get("role") == "agent" else "user"
                # Internal turns (build failures etc.) share the "user" slot in
                # history — tag them so the model never mistakes a CI log
                # for something the customer typed.
                if entry.get("role") == "system" and not entry_text.startswith("[SYSTEM]"):
                    entry_text = f"[SYSTEM] {entry_text}"
                history.append({"role": role, "content": entry_text})

        messages = history + [{"role": "user", "content": final_prompt}]

        # Core tools available in every mode (the publish pair only when a
        # store exists — see build_tools).
        tools = build_tools(self, ctx)
        # SaaS subclasses contribute store-backed tools. Email-linking stays
        # available in every mode (a chat user can connect their account at any
        # point); account management, multi-site and destructive tools are
        # irrelevant during onboarding — withholding them keeps the wizard
        # focused and the prompt smaller.
        tools += self._extra_always_tools(ctx)
        if not is_initial_wizard:
            tools += self._extra_tools(ctx)

        # The endpoint intermittently sheds load (transient) and occasionally
        # returns empty text; retry/escalate before surfacing anything. Once a
        # tool has committed side effects (pipeline_triggered), degrade
        # gracefully instead of replaying — the work is done, only the closing
        # summary was lost. The manual tool loop + retry/escalation live in
        # LLMClient; here we own the empty/fabricated-reply regeneration.
        # The committed-work fallback is turn-aware: on a [SYSTEM] build-failure
        # turn the fix WAS an auto-correction, and "I've saved your changes"
        # would hide it from the user (flash returns empty text after the
        # repair edit — seen live 3/3 on sam_self_heal_001).
        committed_fallback = (
            "I noticed a small issue with the update, but I've corrected it "
            "automatically. I'll let you know the moment it's live!"
            if is_system else
            "I've saved your changes and everything is being prepared now — "
            "I'll let you know the moment it's ready!"
        )
        result = None
        force_thinking = False
        for attempt in range(REPLY_ATTEMPTS):
            try:
                # Any retry escalates to the thinking model: replaying identical
                # inputs on the same model at the same temperature mostly
                # reproduces the same empty reply.
                result = await self._llm.run_turn(
                    system_instruction=final_instruction,
                    messages=messages,
                    tools=tools,
                    force_thinking=force_thinking or attempt >= 1,
                )
            except LLMTransientError as e:
                if ctx.pipeline_triggered:
                    logger.info(f"[Agent] Model dropped after tools committed — finishing gracefully: {str(e)[:120]}")
                    return {
                        "text": committed_fallback,
                        "pipeline_triggered": True,
                        "usage": Usage(),
                        "tool_calls": [],
                    }
                # LLMClient already exhausted its own transient retries before
                # raising; don't replay the whole turn again (keeps the transient
                # budget at 3, not 3x3). The outer loop only regenerates empty /
                # fabricated-edit replies, which never raise.
                raise

            text_candidate = (result.text or "").strip()
            if ctx.pipeline_triggered:
                break
            # A turn whose tool calls were all read-only did honest inspection
            # work — verification phrasing ("I'm double-checking...") after a
            # real read is not a parroted post-edit script. Edit-verb
            # announcements stay a lie: nothing was written.
            tool_names = {tc.name for tc in (result.tool_calls or [])}
            read_only_turn = bool(tool_names) and tool_names <= _READ_ONLY_TOOLS
            claim_re = _EDIT_VERB_CLAIM_RE if read_only_turn else _EDIT_CLAIM_RE
            if text_candidate and not claim_re.search(text_candidate):
                break
            if text_candidate:
                # The reply narrates a successful edit but no tool ran this turn
                # (pipeline_triggered is False) — the model parroted the post-edit
                # script from history. No side effects happened, so regenerating
                # is safe; escalate to the stronger model.
                logger.info(f"[Agent] Reply claims an edit but no tool ran (attempt {attempt + 1}/{REPLY_ATTEMPTS}) — regenerating on the stronger model...")
                force_thinking = True
                continue
            logger.info(f"[Agent] Empty model response (attempt {attempt + 1}/{REPLY_ATTEMPTS}) — regenerating...")

        response_text = (result.text if result else "") or ""
        final_tool_names = {tc.name for tc in (result.tool_calls or [])} if result else set()
        final_read_only = bool(final_tool_names) and final_tool_names <= _READ_ONLY_TOOLS
        if not ctx.pipeline_triggered and not final_read_only and _SCRIPTED_EDIT_CLAIM_RE.search(response_text):
            # Every attempt produced a fabricated success — never relay it.
            logger.warning("[Agent] All attempts claimed an edit without running tools — replacing with an honest failure reply.")
            response_text = "I wasn't able to apply that change just now — could you ask me again in a moment?"
        if not response_text.strip():
            response_text = (
                committed_fallback
                if ctx.pipeline_triggered else
                "Sorry, I had trouble forming a reply just now — could you send that again?"
            )
        return {
            "text": response_text,
            "pipeline_triggered": ctx.pipeline_triggered,
            "usage": result.usage if result else Usage(),
            "tool_calls": result.tool_calls if result else [],
        }

    async def _build_site_state(self, provider_id: str, draft_branch: str | None = None) -> str:
        """Returns a CURRENT SITE STATE block (file list + settings.yaml) for the system prompt.
        When an unpublished draft is open, the snapshot reflects the draft branch so the
        agent always edits on top of its own pending changes."""
        ref = draft_branch or "main"
        try:
            files = await self.git_provider.list_files(provider_id, "content", ref=ref)
        except Exception:
            return ""
        if not files:
            return ""

        state = "\n\n### CURRENT SITE STATE (read-only snapshot)\nContent files of the active website:\n"
        state += "\n".join(f"- {f}" for f in files[:MAX_LISTED_FILES])
        try:
            settings_yaml = await self.git_provider.read_file(provider_id, "content/settings.yaml", ref=ref)
            snippet = settings_yaml.strip()
            # Cap the injected snapshot so an oversized settings.yaml cannot inflate the
            # prompt (and Gemini input cost) on every future turn.
            if len(snippet) > SETTINGS_CHAR_CAP:
                snippet = snippet[:SETTINGS_CHAR_CAP] + "\n# ...(truncated)..."
            state += f"\n\nCurrent content/settings.yaml:\n```yaml\n{snippet}\n```"
        except Exception:
            pass
        if draft_branch:
            state += (
                f"\n\nNOTE: There is an UNPUBLISHED DRAFT in progress (branch '{draft_branch}'). "
                "This snapshot and all file reads reflect that draft. Any further edits are "
                "added to it automatically; a publish request is already open, so do not "
                "create another one — just ask the user to say 'publish' when they are ready."
            )
        state += "\n\nUse read_content_file to inspect any page before changing it."
        return state
