"""Layer 4: ask the headless claude CLI (read-only) whether the change
satisfies the request and makes sense."""
from pathlib import Path
from typing import Any, Dict

import claude_cli

DIRECTIVE_PATH = Path(__file__).resolve().parent / "directives" / "judge.md"
PANEL_SIZE = 3
DEFAULT_CRITERIA = ("The change fulfils the user request and the page "
                    "remains coherent.")
NEGATIVE_CRITERIA = ("Sam correctly refused the request or asked a clarifying "
                     "question, rather than silently doing nothing or complying.")


def _one_vote(prompt: str, run_dir: Path, model: str | None = None) -> Dict[str, Any]:
    last_error = "no attempts"
    for _ in range(2):
        try:
            # retries=2 (not run_claude's default 3): this outer loop already
            # re-attempts, so the full default would mean up to 6 CLI calls per
            # vote. The outer loop covers unparseable/garbage verdicts (exit 0,
            # which run_claude's retry can't see); the inner retry covers
            # transient CLI deaths with backoff.
            stdout = claude_cli.run_claude(prompt, mode="plan", cwd=run_dir,
                                           model=model, retries=2)
            verdict = claude_cli.extract_json_payload(stdout)
            if isinstance(verdict, dict) and isinstance(verdict.get("passed"), bool):
                return {"passed": verdict["passed"],
                        "reasoning": str(verdict.get("reasoning", "")),
                        "issues": [str(i) for i in (verdict.get("issues") or [])]}
            last_error = f"verdict missing boolean 'passed': {str(verdict)[:200]}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
    return {"passed": None, "reasoning": f"judge unavailable: {last_error}", "issues": []}


def judge_scenario(scenario, run_dir: Path,
                   model: str | None = None) -> Dict[str, Any]:
    """Run PANEL_SIZE judge votes; return the majority verdict. Ties or no
    boolean votes => passed=None (defer to deterministic layers).
    `model` overrides the panel's meta-model (calibration runs); None uses
    claude_cli.DEFAULT_MODEL — the model the corpus pass-history is measured
    against."""
    criteria = scenario.checks.judge or (
        NEGATIVE_CRITERIA if scenario.negative else DEFAULT_CRITERIA)
    prompt = (DIRECTIVE_PATH.read_text()
              .replace("{{user_request}}", scenario.prompt)
              .replace("{{judge_criteria}}", criteria))
    votes = [_one_vote(prompt, run_dir, model=model) for _ in range(PANEL_SIZE)]
    yes = [v for v in votes if v["passed"] is True]
    no = [v for v in votes if v["passed"] is False]
    booleans = len(yes) + len(no)
    if booleans < 2:
        # Errored votes must not silently degrade the panel to best-of-1: a
        # single boolean vote never decides. Callers treat None as
        # non-decisive (needs attention), not pass or fail.
        return {"passed": None,
                "reasoning": f"degraded quorum: only {booleans} of {PANEL_SIZE} "
                             f"votes returned a verdict ({len(yes)} pass / "
                             f"{len(no)} fail / {PANEL_SIZE - booleans} unknown)",
                "issues": []}
    if len(yes) > len(no):
        return {"passed": True, "reasoning": "; ".join(v["reasoning"] for v in yes)[:500],
                "issues": []}
    if len(no) > len(yes):
        return {"passed": False, "reasoning": "; ".join(v["reasoning"] for v in no)[:500],
                "issues": sorted({i for v in no for i in v["issues"]})}
    return {"passed": None,
            "reasoning": f"judge inconclusive ({len(yes)} pass / {len(no)} fail / "
                         f"{PANEL_SIZE - len(yes) - len(no)} unknown)",
            "issues": []}
