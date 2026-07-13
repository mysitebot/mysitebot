"""Layered verification of a Sam run: deterministic, build, playwright."""
import os
import subprocess
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

import procs
from scenario_schema import EDIT_TOOLS

# One build-env allowlist, owned by the agent package: npm/node need the
# basics; everything else (LLM_API_KEY etc.) must not reach the build
# subprocess — MDX/plugins execute at build time on scenario/agent-written
# content, so this is the trust boundary (shared with the api-side pipeline).
from agent.templates import BUILD_ENV_PASSTHROUGH


def _build_env() -> dict:
    return {k: os.environ[k] for k in BUILD_ENV_PASSTHROUGH if k in os.environ}


@dataclass
class LayerResult:
    status: str                                  # pass | fail | error | skipped
    details: List[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    layers: Dict[str, LayerResult] = field(default_factory=dict)

    @property
    def status(self) -> str:
        statuses = [layer.status for layer in self.layers.values()]
        if "error" in statuses:
            return "error"
        if "fail" in statuses:
            return "fail"
        return "pass"


def _not_contains_details(workspace: Path, scenario, text: str) -> List[str]:
    """Deterministic ABSENCE assertions (rename/removal leftovers): text the
    reply must not say, text a file must no longer hold. Applied to positive
    and negative scenarios alike."""
    details: List[str] = []
    for needle in scenario.checks.response_not_contains:
        if needle in text:
            details.append(f"response must not contain {needle!r} but does")
    for f, needles in scenario.checks.file_not_contains.items():
        target = workspace / f
        if not target.exists():
            # An absent file trivially lacks the text (files_absent is the
            # check that asserts absence itself).
            continue
        content = target.read_text()
        for needle in needles:
            if needle in content:
                details.append(f"{f}: must not contain {needle!r} but does")
    return details


def verify_deterministic(workspace: Path, scenario, run_result,
                         changes: Dict[str, Any]) -> LayerResult:
    details: List[str] = []
    if run_result.error:
        if run_result.infra:
            return LayerResult(
                "error", [f"LLM infra failure (not Sam): {run_result.error}"])
        return LayerResult("fail", [f"Sam raised: {run_result.error}"])
    called = [c["name"] for c in run_result.tool_calls]

    if scenario.negative:
        bad = sorted(set(called) & EDIT_TOOLS)
        if bad:
            details.append(f"negative scenario but editing tools called: {bad}")
        if changes["files"]:
            details.append(f"negative scenario but files changed: {changes['files']}")
        text = run_result.text or ""
        for needle in scenario.checks.response_contains:
            if needle not in text:
                details.append(
                    f"negative scenario: response missing expected text {needle!r}")
        details.extend(_not_contains_details(workspace, scenario, text))
        return LayerResult("fail" if details else "pass", details)

    text = run_result.text or ""
    details.extend(_not_contains_details(workspace, scenario, text))
    for needle in scenario.checks.response_contains:
        if needle not in text:
            details.append(f"response missing expected text {needle!r}")

    for tool in scenario.checks.expected_tools:
        if tool not in called:
            details.append(
                f"expected tool not called: {tool} (called: {sorted(set(called))})")
    for f in scenario.checks.files_changed:
        if f not in changes["files"]:
            details.append(
                f"expected file not changed: {f} (changed: {changes['files']})")
    for f, needles in scenario.checks.file_contains.items():
        target = workspace / f
        if not target.exists():
            details.append(f"file_contains target missing: {f}")
            continue
        text = target.read_text()
        for needle in needles:
            if needle not in text:
                details.append(f"{f}: missing expected text {needle!r}")
    for f in scenario.checks.files_absent:
        if (workspace / f).exists():
            details.append(f"files_absent: {f} still exists")

    # Local import on purpose: src modules need env vars set first (see conftest)
    from agent.content_validator import validate_content
    for f in changes["files"]:
        if not f.startswith("content/"):
            continue
        # A deleted file appears in changes but has no content to validate.
        if not (workspace / f).is_file():
            continue
        error = validate_content(f, (workspace / f).read_text())
        if error:
            msg = error.get("error", str(error)) if isinstance(error, dict) else str(error)
            hint = error.get("fix_hint") if isinstance(error, dict) else None
            detail = f"validator rejected {f}: {msg}"
            if hint:
                detail += f" (hint: {hint})"
            details.append(detail)

    return LayerResult("fail" if details else "pass", details)


def verify_build(workspace: Path, artifacts_dir: Path,
                 timeout: int = 600) -> LayerResult:
    try:
        # Own process group: on timeout the node grandchildren npm spawned die
        # with it instead of surviving to keep writing into the workspace.
        result = procs.run_group(["npm", "run", "build"], cwd=workspace,
                                 timeout=timeout, env=_build_env())
    except subprocess.TimeoutExpired as e:
        # Keep the partial output — it's the only clue to WHERE the build hung.
        (artifacts_dir / "build.log").write_text(
            f"{e.output or ''}\n{e.stderr or ''}\n"
            f"npm run build timed out after {timeout}s\n")
        raise
    (artifacts_dir / "build.log").write_text(result.stdout + "\n" + result.stderr)
    if result.returncode != 0:
        return LayerResult("fail",
                           [f"npm run build exited {result.returncode} (see build.log)"])
    if not (workspace / "dist" / "index.html").exists():
        return LayerResult("fail", ["build produced no dist/index.html"])
    return LayerResult("pass")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _serve_dist(dist: Path):
    handler = partial(_QuietHandler, directory=str(dist))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


async def verify_playwright(workspace: Path, scenario,
                            artifacts_dir: Path) -> LayerResult:
    from playwright.async_api import async_playwright
    dist = workspace / "dist"
    server, port = _serve_dist(dist)
    details: List[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            pages = sorted({d.page for d in scenario.checks.dom} or {"/"})
            for page_path in pages:
                await page.goto(f"http://127.0.0.1:{port}{page_path}",
                                wait_until="load")
                for check in [d for d in scenario.checks.dom if d.page == page_path]:
                    locator = page.locator(check.selector)
                    if check.count is not None or check.absent:
                        matches = await locator.count()
                        expected = 0 if check.absent else check.count
                        if matches != expected:
                            what = ("no matches" if check.absent
                                    else f"exactly {expected} match(es)")
                            details.append(
                                f"{page_path}: selector {check.selector!r} "
                                f"expected {what}, found {matches}")
                        if check.absent:
                            continue
                    if check.contains is None:
                        continue
                    try:
                        text = await locator.first.inner_text(timeout=5000)
                    except Exception:
                        details.append(
                            f"{page_path}: selector {check.selector!r} not found")
                        continue
                    if check.contains not in text:
                        details.append(
                            f"{page_path} {check.selector!r}: expected "
                            f"{check.contains!r}, got {text[:120]!r}")
                suffix = "_root" if page_path == "/" else page_path.replace("/", "_")
                shot = artifacts_dir / f"screenshot{suffix}.png"
                try:
                    await page.screenshot(path=str(shot), full_page=True)
                except Exception as e:
                    # The screenshot is a diagnostic artifact, not a check. A
                    # Chromium captureScreenshot flake must not error/fail a
                    # scenario whose DOM assertions already passed — record it
                    # as an artifact and carry on.
                    (artifacts_dir / f"screenshot{suffix}.error.txt").write_text(str(e))
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()   # shutdown() stops serving but leaks the socket
    return LayerResult("fail" if details else "pass", details)


async def verify(workspace: Path, scenario, run_result, artifacts_dir: Path,
                 changes: Dict[str, Any]) -> VerificationResult:
    """Layers 1-3, cheap to expensive, fail-fast. Layer 4 (judge) is invoked
    by the orchestrator because it costs an LLM call."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result = VerificationResult()
    result.layers["deterministic"] = verify_deterministic(
        workspace, scenario, run_result, changes)
    if scenario.negative or result.layers["deterministic"].status != "pass":
        return result
    if scenario.checks.build or scenario.checks.dom:
        try:
            result.layers["build"] = verify_build(workspace, artifacts_dir)
        except Exception as e:
            result.layers["build"] = LayerResult("error", [f"{type(e).__name__}: {e}"])
        if result.layers["build"].status != "pass":
            return result
    if scenario.checks.dom:
        try:
            result.layers["playwright"] = await verify_playwright(
                workspace, scenario, artifacts_dir)
        except Exception as e:
            result.layers["playwright"] = LayerResult(
                "error", [f"{type(e).__name__}: {e}"])
    return result
