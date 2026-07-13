"""Scenario definitions for the Sam training loop."""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

HOLDOUT_EVERY = 5  # ~20% of scenarios land in the eval-only holdout

# Tools that mutate the site. Names are normalized (no `_tool` suffix).
EDIT_TOOLS = {
    "create_project",
    "branch_and_edit_content",
    "delete_content_file",
    "create_publish_request",
    "publish_changes",
    "delete_project",
}


class ScenarioError(ValueError):
    pass


@dataclass
class DomCheck:
    page: str
    selector: str
    contains: Optional[str] = None  # text the FIRST match must contain
    count: Optional[int] = None     # exact number of matches (catches e.g. a
                                    # duplicated footer that contains-on-first
                                    # can never see); composable with contains
    absent: bool = False            # the selector must match NOTHING

    def __post_init__(self):
        if self.absent and (self.contains is not None or self.count is not None):
            raise ScenarioError(
                f"dom check {self.selector!r}: 'absent' cannot combine with "
                f"'contains'/'count' (zero matches have no text or count)")
        if not self.absent and self.contains is None and self.count is None:
            raise ScenarioError(
                f"dom check {self.selector!r} asserts nothing: give it "
                f"'contains', 'count', or 'absent'")


@dataclass
class Checks:
    expected_tools: List[str] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    file_contains: Dict[str, List[str]] = field(default_factory=dict)
    file_not_contains: Dict[str, List[str]] = field(default_factory=dict)
    files_absent: List[str] = field(default_factory=list)
    build: bool = False
    dom: List[DomCheck] = field(default_factory=list)
    judge: Optional[str] = None
    response_contains: List[str] = field(default_factory=list)
    response_not_contains: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    id: str
    name: str
    prompt: str
    # Multi-turn conversations: a list of {prompt, is_system, is_init} dicts,
    # one per user/system turn. When present, `prompt` is SYNTHESIZED (a
    # rendered transcript of the turns) so the judge/fixer directives keep
    # working; the runner drives editor.run once per turn over a shared store.
    turns: List[Dict[str, Any]] = field(default_factory=list)
    setup: List[Dict[str, str]] = field(default_factory=list)
    checks: Checks = field(default_factory=Checks)
    negative: bool = False
    # Turn type: is_system marks an internal [SYSTEM] turn (build-failure
    # self-heal), is_init an onboarding-wizard turn. site_editor scrubs the
    # markers from user input, so scenarios must declare these explicitly.
    is_system: bool = False
    is_init: bool = False
    split: Optional[str] = None      # "train" | "holdout"; None => derive by hash
    dry_run: Optional[Dict[str, Any]] = None
    source_file: str = ""


def _parse_turns(raw: Dict[str, Any], source: str) -> List[Dict[str, Any]]:
    raw_turns = raw.get("turns")
    if raw_turns is None:
        return []
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ScenarioError(
            f"{source}: 'turns' must be a non-empty list of turn objects")
    if raw.get("prompt"):
        raise ScenarioError(
            f"{source}: 'prompt' and 'turns' are mutually exclusive — a "
            f"multi-turn scenario's prompt is derived from its turns")
    turns = []
    for item in raw_turns:
        if not (isinstance(item, dict) and item.get("prompt")):
            raise ScenarioError(
                f"{source}: each 'turns' item must be an object with a "
                f"non-empty 'prompt', got {item!r}")
        turns.append({"prompt": item["prompt"],
                      "is_system": bool(item.get("is_system", False)),
                      "is_init": bool(item.get("is_init", False))})
    return turns


def parse_scenario_dict(raw: Dict[str, Any], source: str) -> Scenario:
    turns = _parse_turns(raw, source)
    required = ("id", "name") if turns else ("id", "name", "prompt")
    for key in required:
        if not raw.get(key):
            raise ScenarioError(f"{source}: scenario missing required key '{key}'")
    prompt = raw.get("prompt") or "\n\n".join(
        f"[Turn {i} — {'SYSTEM' if t['is_system'] else 'user'}]: {t['prompt']}"
        for i, t in enumerate(turns, 1))
    raw_checks = raw.get("checks") or {}
    checks = Checks(
        expected_tools=list(raw_checks.get("expected_tools") or []),
        files_changed=list(raw_checks.get("files_changed") or []),
        file_contains={k: list(v) for k, v in (raw_checks.get("file_contains") or {}).items()},
        file_not_contains={k: list(v) for k, v in (raw_checks.get("file_not_contains") or {}).items()},
        files_absent=list(raw_checks.get("files_absent") or []),
        build=bool(raw_checks.get("build", False)),
        dom=[DomCheck(**d) for d in (raw_checks.get("dom") or [])],
        judge=raw_checks.get("judge"),
        response_contains=list(raw_checks.get("response_contains") or []),
        response_not_contains=list(raw_checks.get("response_not_contains") or []),
    )
    split = raw.get("split")
    if split is not None and split not in ("train", "holdout"):
        raise ScenarioError(f"{source}: split must be 'train' or 'holdout', got {split!r}")
    # setup is a LIST of {path, content} objects (seeded baseline files). A common
    # generator miss is authoring it as a path->content map (the dry_run.edits
    # shape); list(dict) would silently degrade to a list of path strings and
    # crash provision_workspace with a cryptic TypeError, so reject it here.
    raw_setup = raw.get("setup") or []
    if not isinstance(raw_setup, list):
        raise ScenarioError(
            f"{source}: 'setup' must be a list of {{path, content}} objects, "
            f"got {type(raw_setup).__name__} (the path->content map shape is only "
            f"for dry_run.edits)")
    for item in raw_setup:
        if not (isinstance(item, dict) and "path" in item and "content" in item):
            raise ScenarioError(
                f"{source}: each 'setup' item must be an object with 'path' and "
                f"'content', got {item!r}")
    return Scenario(
        id=raw["id"], name=raw["name"], prompt=prompt, turns=turns,
        setup=[dict(item) for item in raw_setup], checks=checks,
        negative=bool(raw.get("negative", False)),
        is_system=bool(raw.get("is_system", False)),
        # An onboarding conversation starts uninitialized: workspace
        # provisioning keys on is_init, so derive it from the first turn.
        is_init=bool(raw.get("is_init", False)) or bool(turns and turns[0]["is_init"]),
        split=split,
        dry_run=raw.get("dry_run"), source_file=source,
    )


def load_scenarios(scenarios_dir: Path) -> List[Scenario]:
    out: List[Scenario] = []
    for path in sorted(Path(scenarios_dir).rglob("*.json")):
        # Skip the generator's quarantine: rejected candidates are kept for
        # inspection, never loaded as corpus (and never evaluated).
        if "rejected" in path.parts:
            continue
        data = json.loads(path.read_text())
        items = data if isinstance(data, list) else [data]
        for raw in items:
            out.append(parse_scenario_dict(raw, str(path)))
    ids = [s.id for s in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ScenarioError(f"Duplicate scenario ids: {dupes}")
    return out


def is_holdout(scenario) -> bool:
    """True if the scenario is eval-only (the fixer never reacts to it).
    Honors an explicit split; otherwise derives deterministically from the id
    so the ~20% holdout is stable per-id and auto-scales as the corpus grows."""
    if scenario.split in ("train", "holdout"):
        return scenario.split == "holdout"
    digest = int(hashlib.sha1(scenario.id.encode()).hexdigest(), 16)
    return digest % HOLDOUT_EVERY == 0
