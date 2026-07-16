"""Provision workspaces and run Sam (live or dry-run)."""
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _paths import bootstrap

# Must be set before any agent import (same pattern as cli.py)
os.environ.setdefault("ADMIN_USERNAME", "training_admin")
os.environ.setdefault("ADMIN_PASSWORD", "training_admin_password")
os.environ.setdefault("JWT_SECRET", "training_jwt_secret_placeholder_min_32_chars")

REPO_ROOT = bootstrap()   # sam repo root

GITIGNORE = "node_modules/\ndist/\n.astro/\n"


@dataclass
class SamRunResult:
    text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    infra: bool = False   # True: the LLM infrastructure failed, not Sam
    # Full conversation ({role, text} per entry) — the judge needs it to
    # assess sequencing in multi-turn scenarios.
    transcript: List[Dict[str, str]] = field(default_factory=list)


class HarnessStore:
    """Minimal in-memory stand-in for the api store, replicating exactly the
    contract site_editor uses (projects, session summaries, conversation log).
    Multi-turn scenarios need it so history and the pending publish request
    carry across turns the way production does."""

    def __init__(self):
        self.projects: Dict[str, Any] = {}
        self.sessions: Dict[str, Any] = {}
        self.logs: Dict[str, list] = {}

    async def save_project(self, project_id, data):
        self.projects[project_id] = data

    async def get_project(self, project_id):
        return self.projects.get(project_id)

    async def get_user_session(self, session_id):
        return self.sessions.get(session_id)

    async def save_user_session(self, session_id, data):
        self.sessions[session_id] = data

    async def get_conversation_log(self, session_id):
        return list(self.logs.get(session_id, []))

    async def append_conversation_log(self, session_id, role, text):
        self.logs.setdefault(session_id, []).append({"role": role, "text": text})

    async def is_locked(self, project_id):
        return False


def _is_infra_error(exc: BaseException) -> bool:
    """True when the exception is an infrastructure/credentials problem (dead or
    expired API key, missing access, wrong model id, exhausted quota/retries) —
    the harness's fault, not Sam's. These must surface as status 'error', never
    'fail': a 'fail' burns best-of-k confirmation runs and (with --fix) sends
    the fixer chasing an auth problem through Sam's prompt."""
    import openai
    from agent.llm.types import LLMTransientError
    return isinstance(exc, (
        openai.AuthenticationError,    # 401: dead/expired key
        openai.PermissionDeniedError,  # 403: key lacks access
        openai.NotFoundError,          # bad --model id (after client fallback)
        openai.RateLimitError,         # quota exhausted
        openai.APITimeoutError,
        openai.APIConnectionError,
        LLMTransientError,             # LLMClient exhausted its transient retries
    ))


def extract_tool_calls(tool_calls) -> List[Dict[str, Any]]:
    """Map LLMResult.tool_calls (list of agent.llm.types.ToolCall) to the
    {name, args} dicts the scenario vocabulary expects. Tool functions may be
    bound with a `_tool` suffix — strip it to match scenarios."""
    calls: List[Dict[str, Any]] = []
    for tc in tool_calls or []:
        name = tc.name
        if name.endswith("_tool"):
            name = name[: -len("_tool")]
        calls.append({"name": name, "args": dict(tc.args or {})})
    return calls


def _git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True, text=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "training", "GIT_AUTHOR_EMAIL": "training@local",
             "GIT_COMMITTER_NAME": "training", "GIT_COMMITTER_EMAIL": "training@local"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def init_baseline(workspace: Path) -> None:
    """git-init the workspace so Sam's changes are measurable as a diff.
    LocalGitProvider does not create a real git repo."""
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE)
    _git(workspace, "init", "-q")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-qm", "baseline")


def parse_porcelain_z(porcelain: str) -> set:
    """File paths from `git status --porcelain -z` output. Records are
    "XY path"; rename/copy records are followed by a bare old-path field
    with no status prefix — both paths count as changed."""
    files = set()
    fields = [f for f in porcelain.split("\0") if f.strip()]
    i = 0
    while i < len(fields):
        entry = fields[i]
        files.add(entry[3:])
        if entry[0] in ("R", "C"):
            i += 1
            if i < len(fields):
                files.add(fields[i])
        i += 1
    return files


def workspace_changes(workspace: Path) -> Dict[str, Any]:
    """Changed files + unified diff vs. the baseline commit. `add -N` makes
    new files appear in `git diff HEAD`."""
    _git(workspace, "add", "-N", ".")
    porcelain = _git(workspace, "status", "--porcelain", "-z")
    files = sorted(parse_porcelain_z(porcelain))
    diff = _git(workspace, "diff", "HEAD")
    return {"files": files, "diff": diff}


async def provision_workspace(scen_dir: Path, scenario) -> Tuple[Any, Path]:
    """Fresh project from templates/astro-basic + scenario setup edits +
    git baseline. Returns (provider, project_dir)."""
    from agent.providers.git.base import LocalGitProvider
    workspace_root = scen_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    provider = LocalGitProvider(workspace_root=str(workspace_root))
    project_dir = workspace_root / scenario.id
    if scenario.is_init:
        # Onboarding scenarios start from NOTHING: in production a wizard user
        # has no site yet, and a pre-provisioned template would put a full
        # CURRENT SITE STATE in Sam's prompt and tempt it to edit instead of
        # create. An empty baselined dir keeps workspace_changes working.
        project_dir.mkdir(parents=True, exist_ok=True)
        for edit in scenario.setup:
            target = project_dir / edit["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit["content"])
        init_baseline(project_dir)
        return provider, project_dir
    await provider.create_project(scenario.id, "astro-basic")
    for edit in scenario.setup:
        target = project_dir / edit["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit["content"])
    init_baseline(project_dir)
    return provider, project_dir


async def run_sam(scenario, provider, model: str) -> SamRunResult:
    """Run Sam against the provisioned project — one editor.run per turn.
    EVERY scenario gets a HarnessStore: store=None now means store-less CLI
    mode, where the editor withholds the publish tools and prompt narrative —
    the eval must keep measuring the SaaS surface (publish flow included)
    exactly as every past ledger did. Multi-turn scenarios additionally rely
    on it so history and the pending publish request carry across turns,
    mirroring api/agent/core.py's contract (inbound message appended before
    the call, agent reply after)."""
    from agent.site_editor import AgentSiteEditor
    from stub_media_search import StubMediaSearch
    turns = scenario.turns or [{"prompt": scenario.prompt,
                                "is_system": scenario.is_system,
                                "is_init": scenario.is_init}]
    session_id = f"training_{scenario.id}"
    store = HarnessStore()
    # Production always has a project record (created at onboarding);
    # without one, create_publish_request cannot persist the pending MR.
    store.projects[scenario.id] = {"project_id": scenario.id,
                                   "name": scenario.id}
    editor = AgentSiteEditor(
        api_key=os.environ.get("LLM_API_KEY", ""),
        git_provider=provider,
        model=model,
        session_id=session_id,
        store=store,
        # Without a media backend search_media_library returns "not configured",
        # making image scenarios unwinnable. A deterministic offline stub lets
        # them be evaluated (no Postgres/embeddings/GCS).
        media_search=StubMediaSearch(),
    )
    tool_calls: List[Dict[str, Any]] = []
    transcript: List[Dict[str, str]] = []
    text = ""
    for turn in turns:
        role = "system" if turn["is_system"] else "user"
        if store is not None:
            await store.append_conversation_log(session_id, role, turn["prompt"])
        transcript.append({"role": role, "text": turn["prompt"]})
        try:
            result = await editor.run(turn["prompt"], scenario.id,
                                      is_init=turn["is_init"],
                                      is_system=turn["is_system"])
        except Exception as e:
            # A Sam crash is a scenario failure — but an LLM infra problem
            # (dead key, quota, endpoint down) is the harness's, and must not
            # be pinned on Sam.
            return SamRunResult(error=f"{type(e).__name__}: {e}",
                                infra=_is_infra_error(e),
                                tool_calls=tool_calls, transcript=transcript)
        text = result.get("text", "")
        if store is not None:
            await store.append_conversation_log(session_id, "agent", text)
        transcript.append({"role": "agent", "text": text})
        tool_calls.extend(extract_tool_calls(result.get("tool_calls")))
    return SamRunResult(text=text, tool_calls=tool_calls, transcript=transcript)


def run_sam_dry(scenario, project_dir: Path) -> SamRunResult:
    """Replay the scenario's recorded `dry_run` block instead of calling Sam.
    Lets the whole loop run offline in tests."""
    data = scenario.dry_run or {}
    for path, content in (data.get("edits") or {}).items():
        target = project_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for path in (data.get("deletes") or []):
        target = project_dir / path
        if target.is_file():
            target.unlink()
    transcript = []
    if scenario.turns:
        transcript = [{"role": "system" if t["is_system"] else "user",
                       "text": t["prompt"]} for t in scenario.turns]
        transcript.append({"role": "agent", "text": data.get("text", "(dry run)")})
    return SamRunResult(
        text=data.get("text", "(dry run)"),
        tool_calls=list(data.get("tool_calls") or []),
        transcript=transcript,
    )
