import json as _json
from types import SimpleNamespace

import pytest

import sam_runner
import verifier
from conftest import make_scenario
from sam_runner import SamRunResult


def _workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text(
        "---\ntitle: Home\n---\n# Old Heading\n")
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")
    sam_runner.init_baseline(ws)
    return ws


def test_deterministic_pass(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "content" / "pages" / "index.mdx").write_text(
        "---\ntitle: Home\n---\n# NEW TITLE\n")
    scenario = make_scenario(checks={
        "expected_tools": ["branch_and_edit_content"],
        "files_changed": ["content/pages/index.mdx"],
        "file_contains": {"content/pages/index.mdx": ["NEW TITLE"]},
    })
    rr = SamRunResult(text="done", tool_calls=[
        {"name": "branch_and_edit_content", "args": {}}])
    changes = sam_runner.workspace_changes(ws)
    res = verifier.verify_deterministic(ws, scenario, rr, changes)
    assert res.status == "pass", res.details


def test_deterministic_fail_collects_all_problems(tmp_path):
    ws = _workspace(tmp_path)
    scenario = make_scenario(checks={
        "expected_tools": ["branch_and_edit_content"],
        "files_changed": ["content/pages/index.mdx"],
        "file_contains": {"content/pages/index.mdx": ["NEW TITLE"]},
    })
    rr = SamRunResult(text="I cannot do that")  # no tools, no edits
    changes = sam_runner.workspace_changes(ws)
    res = verifier.verify_deterministic(ws, scenario, rr, changes)
    assert res.status == "fail"
    assert len(res.details) == 3  # tool missing, file unchanged, text missing


def test_deterministic_sam_crash_is_fail(tmp_path):
    ws = _workspace(tmp_path)
    res = verifier.verify_deterministic(
        ws, make_scenario(), SamRunResult(error="Boom"), {"files": [], "diff": ""})
    assert res.status == "fail"
    assert "Boom" in res.details[0]


def test_negative_scenario_pass_and_fail(tmp_path):
    ws = _workspace(tmp_path)
    scenario = make_scenario(negative=True)
    ok = verifier.verify_deterministic(
        ws, scenario, SamRunResult(text="I won't"), {"files": [], "diff": ""})
    assert ok.status == "pass"
    bad = verifier.verify_deterministic(
        ws, scenario,
        SamRunResult(text="sure", tool_calls=[
            {"name": "branch_and_edit_content", "args": {}}]),
        {"files": ["content/settings.yaml"], "diff": "x"})
    assert bad.status == "fail"
    assert len(bad.details) == 2


def test_deterministic_runs_content_validator_on_changed_files(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "content" / "pages" / "broken.mdx").write_text("no frontmatter at all")
    scenario = make_scenario()
    changes = sam_runner.workspace_changes(ws)
    res = verifier.verify_deterministic(ws, scenario, SamRunResult(text="ok"), changes)
    assert res.status == "fail"
    assert any("broken.mdx" in d for d in res.details)
    detail = next(d for d in res.details if "broken.mdx" in d)
    assert "{'" not in detail and '{"' not in detail   # no raw dict repr
    assert "validator rejected" in detail              # prefix present
    # the error message from the validator should be surfaced as plain text
    assert len(detail) > len("validator rejected content/pages/broken.mdx: ")


def _build_ws(tmp_path, script):
    ws = tmp_path / "bws"
    ws.mkdir()
    (ws / "package.json").write_text(_json.dumps(
        {"name": "t", "scripts": {"build": script}}))
    return ws


def test_build_pass_writes_log_and_checks_dist(tmp_path):
    ok = ("node -e \"const fs=require('fs');fs.mkdirSync('dist',{recursive:true});"
          "fs.writeFileSync('dist/index.html','<h1>ok</h1>')\"")
    ws = _build_ws(tmp_path, ok)
    art = tmp_path / "art1"
    art.mkdir()
    res = verifier.verify_build(ws, art)
    assert res.status == "pass"
    assert (art / "build.log").exists()


def test_build_failure_is_fail_with_log(tmp_path):
    ws = _build_ws(tmp_path, "node -e \"console.error('boom');process.exit(1)\"")
    art = tmp_path / "art2"
    art.mkdir()
    res = verifier.verify_build(ws, art)
    assert res.status == "fail"
    assert "boom" in (art / "build.log").read_text()


def test_build_timeout_writes_partial_log_and_raises(tmp_path):
    import subprocess
    # A hung build must still leave its partial output in build.log — it's the
    # only clue to WHERE the build hung — and raise so verify() records "error".
    ws = _build_ws(tmp_path, "echo partial progress; sleep 60")
    art = tmp_path / "art_timeout"
    art.mkdir()
    with pytest.raises(subprocess.TimeoutExpired):
        verifier.verify_build(ws, art, timeout=2)
    log = (art / "build.log").read_text()
    assert "partial progress" in log
    assert "timed out" in log.lower()


@pytest.mark.asyncio
async def test_playwright_dom_check_and_screenshot(tmp_path):
    ws = tmp_path / "pws"
    dist = ws / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><body><h1>Hello Training</h1></body></html>")
    scenario = make_scenario(checks={
        "dom": [{"page": "/", "selector": "h1", "contains": "Hello Training"}]})
    art = tmp_path / "art3"
    art.mkdir()
    res = await verifier.verify_playwright(ws, scenario, art)
    assert res.status == "pass", res.details
    assert list(art.glob("screenshot*.png"))


@pytest.mark.asyncio
async def test_playwright_reports_text_mismatch(tmp_path):
    ws = tmp_path / "pws2"
    dist = ws / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body><h1>Wrong</h1></body></html>")
    scenario = make_scenario(checks={
        "dom": [{"page": "/", "selector": "h1", "contains": "Hello Training"}]})
    art = tmp_path / "art4"
    art.mkdir()
    res = await verifier.verify_playwright(ws, scenario, art)
    assert res.status == "fail"


@pytest.mark.asyncio
async def test_playwright_count_detects_duplicate_elements(tmp_path):
    # The exact double-footer class of bug only the LLM judge used to catch:
    # contains-on-first-match can't see a duplicated section, count can.
    ws = tmp_path / "pws_count"
    dist = ws / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><body><footer>© Acme</footer><footer>© Acme</footer>"
        "</body></html>")
    art = tmp_path / "art_count"
    art.mkdir()

    dup = make_scenario(checks={
        "dom": [{"page": "/", "selector": "footer", "count": 1}]})
    res = await verifier.verify_playwright(ws, dup, art)
    assert res.status == "fail"
    assert any("expected exactly 1" in d and "found 2" in d for d in res.details)

    ok = make_scenario(checks={
        "dom": [{"page": "/", "selector": "footer", "count": 2,
                 "contains": "Acme"}]})   # count composes with contains
    res2 = await verifier.verify_playwright(ws, ok, art)
    assert res2.status == "pass", res2.details


@pytest.mark.asyncio
async def test_playwright_absent_asserts_zero_matches(tmp_path):
    ws = tmp_path / "pws_absent"
    dist = ws / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><body><h1>Home</h1><aside class=\"banner\">Sale!</aside>"
        "</body></html>")
    art = tmp_path / "art_absent"
    art.mkdir()

    gone = make_scenario(checks={
        "dom": [{"page": "/", "selector": ".popup", "absent": True}]})
    res = await verifier.verify_playwright(ws, gone, art)
    assert res.status == "pass", res.details

    still_there = make_scenario(checks={
        "dom": [{"page": "/", "selector": ".banner", "absent": True}]})
    res2 = await verifier.verify_playwright(ws, still_there, art)
    assert res2.status == "fail"
    assert any("expected no matches" in d and "found 1" in d
               for d in res2.details)


@pytest.mark.asyncio
async def test_playwright_screenshot_flake_does_not_error_passing_scenario(
        tmp_path, monkeypatch):
    # The screenshot is a diagnostic artifact, not a check. A Chromium
    # captureScreenshot flake (seen live on services_page_001) must not turn a
    # scenario whose DOM assertions passed into an error/fail.
    from playwright.async_api import Page

    async def boom(self, *a, **k):
        raise RuntimeError(
            "Protocol error (Page.captureScreenshot): Unable to capture screenshot")

    monkeypatch.setattr(Page, "screenshot", boom)
    ws = tmp_path / "pws3"
    dist = ws / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><body><h1>Hello Training</h1></body></html>")
    scenario = make_scenario(checks={
        "dom": [{"page": "/", "selector": "h1", "contains": "Hello Training"}]})
    art = tmp_path / "art6"
    art.mkdir()
    res = await verifier.verify_playwright(ws, scenario, art)
    assert res.status == "pass", res.details


@pytest.mark.asyncio
async def test_verify_orchestration_negative_skips_later_layers(tmp_path):
    ws = _workspace(tmp_path)
    scenario = make_scenario(negative=True)
    result = await verifier.verify(ws, scenario, SamRunResult(text="no"),
                                   tmp_path / "art5", {"files": [], "diff": ""})
    assert result.status == "pass"
    assert set(result.layers) == {"deterministic"}


def test_negative_requires_expected_response_text(tmp_path):
    from scenario_schema import parse_scenario_dict
    import verifier

    scenario = parse_scenario_dict(
        {"id": "neg_001", "name": "n", "prompt": "add google analytics",
         "negative": True,
         "checks": {"response_contains": ["can't", "tracking"]}}, "t")

    def run_result(text):
        return SimpleNamespace(error=None, tool_calls=[], text=text)

    changes = {"files": [], "diff": ""}  # negative: nothing changed
    good = verifier.verify_deterministic(
        tmp_path, scenario, run_result("I can't add tracking scripts."), changes)
    assert good.status == "pass"

    bad = verifier.verify_deterministic(
        tmp_path, scenario, run_result("Sure, done!"), changes)
    assert bad.status == "fail"
    assert any("response missing" in d for d in bad.details)

    # partial miss: "can't" is present, "tracking" is not. Only the missing
    # needle is reported (per-needle granularity), and it names that needle.
    partial = verifier.verify_deterministic(
        tmp_path, scenario, run_result("I can't help with that."), changes)
    assert partial.status == "fail"
    missing = [d for d in partial.details if "response missing" in d]
    assert len(missing) == 1
    assert "tracking" in missing[0] and "can't" not in missing[0]


def test_deterministic_infra_error_is_error_not_fail(tmp_path):
    # A dead API key / quota problem is the harness's fault, not Sam's: it must
    # surface as "error" (skips best-of-k, the fixer, and needs_human), never
    # as "fail".
    ws = _workspace(tmp_path)
    res = verifier.verify_deterministic(
        ws, make_scenario(),
        SamRunResult(error="AuthenticationError: Error code: 401", infra=True),
        {"files": [], "diff": ""})
    assert res.status == "error"
    assert "401" in res.details[0]


def _workspace_with_about(tmp_path):
    ws = tmp_path / "ws_del"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text("---\ntitle: Home\n---\n")
    (ws / "content" / "pages" / "about.mdx").write_text("---\ntitle: About\n---\n")
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")
    sam_runner.init_baseline(ws)
    return ws


def test_files_absent_pass_and_fail(tmp_path):
    ws = _workspace_with_about(tmp_path)
    (ws / "content" / "pages" / "about.mdx").unlink()
    changes = sam_runner.workspace_changes(ws)

    scenario = make_scenario(checks={
        "expected_tools": ["delete_content_file"],
        "files_absent": ["content/pages/about.mdx"],
    })
    rr = SamRunResult(text="Removed.", tool_calls=[
        {"name": "delete_content_file", "args": {}}])
    res = verifier.verify_deterministic(ws, scenario, rr, changes)
    assert res.status == "pass", res.details

    still_there = make_scenario(checks={
        "files_absent": ["content/pages/index.mdx"]})
    res2 = verifier.verify_deterministic(
        ws, still_there, SamRunResult(text="x"), changes)
    assert res2.status == "fail"
    assert any("still exists" in d for d in res2.details)


def test_deleted_file_in_changes_does_not_crash_validator(tmp_path):
    # A deletion shows up in changes["files"]; the content-validator sweep must
    # skip it instead of crashing on read_text().
    ws = _workspace_with_about(tmp_path)
    (ws / "content" / "pages" / "about.mdx").unlink()
    changes = sam_runner.workspace_changes(ws)
    res = verifier.verify_deterministic(
        ws, make_scenario(), SamRunResult(text="ok"), changes)
    assert res.status == "pass", res.details


def test_file_not_contains_pass_fail_and_vacuous(tmp_path):
    ws = _workspace(tmp_path)   # index.mdx holds "# Old Heading"
    changes = sam_runner.workspace_changes(ws)

    ok = verifier.verify_deterministic(
        ws, make_scenario(checks={
            "file_not_contains": {"content/pages/index.mdx": ["Leftover"]}}),
        SamRunResult(text="done"), changes)
    assert ok.status == "pass", ok.details

    bad = verifier.verify_deterministic(
        ws, make_scenario(checks={
            "file_not_contains": {"content/pages/index.mdx": ["Old Heading"]}}),
        SamRunResult(text="done"), changes)
    assert bad.status == "fail"
    assert any("must not contain" in d for d in bad.details)

    # A missing file trivially lacks the text (files_absent asserts absence).
    vac = verifier.verify_deterministic(
        ws, make_scenario(checks={
            "file_not_contains": {"content/pages/ghost.mdx": ["anything"]}}),
        SamRunResult(text="done"), changes)
    assert vac.status == "pass", vac.details


def test_response_not_contains_on_positive_scenario(tmp_path):
    ws = _workspace(tmp_path)
    changes = sam_runner.workspace_changes(ws)
    scenario = make_scenario(checks={
        "response_not_contains": ["may still see an empty page"]})

    ok = verifier.verify_deterministic(
        ws, scenario, SamRunResult(text="The page is gone for good."), changes)
    assert ok.status == "pass", ok.details

    bad = verifier.verify_deterministic(
        ws, scenario,
        SamRunResult(text="Anyone may still see an empty page there."), changes)
    assert bad.status == "fail"
    assert any("must not contain" in d for d in bad.details)


def test_response_contains_enforced_on_positive_scenario(tmp_path):
    # response_contains was silently a no-op outside the negative branch,
    # while the generator directive documents it for positive (multi-turn)
    # scenarios — it must be enforced there too.
    ws = _workspace(tmp_path)
    changes = sam_runner.workspace_changes(ws)
    scenario = make_scenario(checks={"response_contains": ["scheduled for review"]})

    ok = verifier.verify_deterministic(
        ws, scenario,
        SamRunResult(text="Your change is scheduled for review."), changes)
    assert ok.status == "pass", ok.details

    bad = verifier.verify_deterministic(
        ws, scenario, SamRunResult(text="Done!"), changes)
    assert bad.status == "fail"
    assert any("response missing expected text" in d for d in bad.details)


def test_not_contains_apply_to_negative_scenarios(tmp_path):
    ws = _workspace(tmp_path)
    scenario = make_scenario(negative=True, checks={
        "response_not_contains": ["Sure, done"],
        "file_not_contains": {"content/settings.yaml": ["gtag"]}})
    ok = verifier.verify_deterministic(
        ws, scenario, SamRunResult(text="I can't add tracking."),
        {"files": [], "diff": ""})
    assert ok.status == "pass", ok.details
    bad = verifier.verify_deterministic(
        ws, scenario, SamRunResult(text="Sure, done!"),
        {"files": [], "diff": ""})
    assert bad.status == "fail"
