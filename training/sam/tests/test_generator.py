import json

import generate_scenarios
from conftest import make_claude_stub

SEED = [{"id": "hero_title_001", "name": "Update Hero Title",
         "prompt": "Change the main heading of my home page to 'The Future of AI'"}]


def test_jaccard_duplicate_detection():
    assert generate_scenarios.is_duplicate(
        "Change the main heading of my home page to 'The Future of AI'",
        ["Change the main heading of my home page to 'The Future of AI'"])
    assert not generate_scenarios.is_duplicate(
        "Add a pricing page with three plans",
        ["Change the main heading of my home page to 'The Future of AI'"])


def test_generator_writes_valid_skips_dupes_and_invalid(tmp_path, monkeypatch):
    scenarios_dir = tmp_path / "scenarios"
    seed_dir = scenarios_dir / "seed"
    seed_dir.mkdir(parents=True)
    (seed_dir / "seed.json").write_text(json.dumps(SEED))
    payload = {"scenarios": [
        {"id": "pricing_page_001", "name": "Add Pricing Page",
         "prompt": "Add a pricing page with three plans",
         "checks": {"expected_tools": ["branch_and_edit_content"],
                    "files_changed": ["content/pages/pricing.mdx"]},
         "dry_run": {"text": "done",
                     "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
                     "edits": {"content/pages/pricing.mdx": "---\ntitle: Pricing\n---\nPricing page\n"}}},
        {"id": "dupe_001", "name": "Dupe",
         "prompt": "Change the main heading of my home page to 'The Future of AI'"},
        {"id": "invalid_001", "name": "Invalid"},  # missing prompt
        "just a string",
    ]}
    body = f'print(json.dumps({{"result": json.dumps({json.dumps(payload)})}}))'
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    generate_scenarios.main(["--count", "3",
                             "--scenarios-dir", str(scenarios_dir)])
    written = sorted((scenarios_dir / "generated").glob("*.json"))
    assert [p.stem for p in written] == ["pricing_page_001"]


def test_generator_accepts_single_scenario_object_without_wrapper(tmp_path, monkeypatch):
    # A model reply that is ONE scenario object (no {"scenarios": [...]}
    # wrapper) used to yield [] silently — zero written, zero skipped, no clue.
    # A dict carrying an "id" is a scenario; treat it as a one-item batch.
    scenarios_dir = tmp_path / "scenarios"
    (scenarios_dir / "seed").mkdir(parents=True)
    (scenarios_dir / "seed" / "seed.json").write_text(json.dumps(SEED))
    payload = {
        "id": "solo_page_001", "name": "Add Solo Page",
        "prompt": "Add a team page introducing our staff",
        "checks": {"expected_tools": ["branch_and_edit_content"],
                   "files_changed": ["content/pages/team.mdx"]},
        "dry_run": {"text": "done",
                    "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
                    "edits": {"content/pages/team.mdx":
                              '---\ntitle: "Team"\n---\nOur staff\n'}}}
    body = f'print(json.dumps({{"result": json.dumps({json.dumps(payload)})}}))'
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    generate_scenarios.main(["--count", "1", "--scenarios-dir", str(scenarios_dir)])
    written = sorted((scenarios_dir / "generated").glob("*.json"))
    assert [p.stem for p in written] == ["solo_page_001"]


def test_structural_violation_multiturn_judge_needs_fail_clause_not_just_keyword():
    import generate_scenarios as gen
    from scenario_schema import parse_scenario_dict
    # The old check was the bare substring "transcript" — trivially satisfied
    # by naming the word while still judging only the final reply. The
    # directive mandates explicit "Fail if ..." clauses; require that cue too.
    raw = {
        "id": "mt_keyword_bypass_001", "name": "n",
        "turns": [{"prompt": "change the tagline to 'Hi'"},
                  {"prompt": "publish"}],
        "checks": {"expected_tools": ["branch_and_edit_content"],
                   "judge": "The transcript shows the tagline was updated."},
    }
    violation = gen.structural_violation(parse_scenario_dict(raw, "t"))
    assert violation and "fail" in violation.lower()
    raw["checks"]["judge"] = ("Read transcript.json. Turn 1: updated the "
                              "tagline. Turn 2: published. Fail if it "
                              "published in turn 1.")
    assert gen.structural_violation(parse_scenario_dict(raw, "t")) is None


def test_validate_candidate_rejects_unsatisfiable_reference():
    import generate_scenarios as gen
    # reference solution writes content that does NOT contain the required text
    raw = {
        "id": "cand_bad_001", "name": "n", "prompt": "add an about page",
        "checks": {"file_contains": {"content/pages/about.mdx": ["MUST APPEAR"]}},
        "dry_run": {"text": "done", "tool_calls": [],
                    "edits": {"content/pages/about.mdx": "---\n---\nwrong\n"}},
    }
    ok, reason = gen.validate_candidate(raw)
    assert ok is False
    assert "MUST APPEAR" in reason or "missing" in reason.lower()


def test_validate_candidate_rejects_malformed_tool_calls_without_crashing():
    import generate_scenarios as gen
    # A candidate whose dry_run.tool_calls are bare strings (a real generator
    # miss seen on the first live --count run) must be REJECTED with a reason,
    # never crash the whole batch. Regression: TypeError on c["name"] in
    # verify_deterministic propagated out of validate_candidate.
    raw = {
        "id": "cand_badtc_001", "name": "n", "prompt": "do something",
        "checks": {"expected_tools": ["branch_and_edit_content"]},
        "dry_run": {"text": "done",
                    "tool_calls": ["branch_and_edit_content"],
                    "edits": {"content/pages/index.mdx": '---\ntitle: "Home"\n---\nhi\n'}},
    }
    ok, reason = gen.validate_candidate(raw)
    assert ok is False
    assert reason  # a non-empty reason, not a raised exception


def test_validate_candidate_rejects_valid_frontmatter_wrong_body():
    import generate_scenarios as gen
    # Frontmatter is valid (clears the content validator), but the body omits
    # the required text — so the file_contains check is what rejects it, and the
    # reason actually names the missing needle. (The title-less fixture above is
    # rejected earlier by the validator, so its "MUST APPEAR" branch never runs.)
    raw = {
        "id": "cand_body_001", "name": "n", "prompt": "add an about page",
        "checks": {"file_contains": {"content/pages/about.mdx": ["MUST APPEAR"]}},
        "dry_run": {"text": "done", "tool_calls": [],
                    "edits": {"content/pages/about.mdx": '---\ntitle: "About"\n---\nwrong body\n'}},
    }
    ok, reason = gen.validate_candidate(raw)
    assert ok is False
    assert "MUST APPEAR" in reason


def test_validate_candidate_rejects_reference_that_fails_build(monkeypatch):
    import generate_scenarios as gen
    import verifier
    # A reference can clear the deterministic checks (file_contains/tools) yet use
    # a content format that never builds/renders. validate_candidate must run the
    # build+dom layers and reject it. Regression: the generator promoted 5
    # scenarios whose index.mdx used a non-rendering YAML `sections:` format —
    # they passed file_contains but rendered an empty page (dom failed at smoke).
    monkeypatch.setattr(verifier, "verify_build",
                        lambda ws, ad: verifier.LayerResult("fail", ["build boom"]))
    raw = {
        "id": "cand_nobuild_001", "name": "n", "prompt": "add a section",
        "checks": {"build": True,
                   "file_contains": {"content/pages/index.mdx": ["Why Choose Us"]}},
        "dry_run": {"text": "done", "tool_calls": [],
                    "edits": {"content/pages/index.mdx": '---\ntitle: "Home"\n---\nWhy Choose Us\n'}},
    }
    ok, reason = gen.validate_candidate(raw)
    assert ok is False
    assert "build" in reason.lower()


def test_validate_candidate_accepts_satisfiable_reference():
    import generate_scenarios as gen
    raw = {
        "id": "cand_ok_001", "name": "n", "prompt": "add an about page",
        "checks": {"file_contains": {"content/pages/about.mdx": ["MUST APPEAR"]}},
        "dry_run": {"text": "done", "tool_calls": [],
                    "edits": {"content/pages/about.mdx": '---\ntitle: "About"\n---\nMUST APPEAR\n'}},
    }
    ok, reason = gen.validate_candidate(raw)
    assert ok is True, reason


def test_structural_violation_multiturn_needs_transcript_aware_judge():
    import generate_scenarios as gen
    from scenario_schema import parse_scenario_dict
    # A multi-turn scenario's response.txt holds only the LAST reply, so a judge
    # criterion that never looks at transcript.json silently judges the wrong
    # evidence. validate_candidate can't catch this (the dry_run still passes
    # its deterministic checks), so it must be a structural reject.
    raw = {
        "id": "mt_bad_judge_001", "name": "n",
        "turns": [{"prompt": "change the tagline to 'Hi'"},
                  {"prompt": "publish"}],
        "checks": {"expected_tools": ["branch_and_edit_content"],
                   "judge": "The tagline was updated and published."},
    }
    violation = gen.structural_violation(parse_scenario_dict(raw, "t"))
    assert violation and "transcript" in violation.lower()
    raw["checks"]["judge"] = ("Read transcript.json. Turn 1: Sam updated the "
                              "tagline without publishing. Turn 2: Sam "
                              "published. Fail if it published in turn 1.")
    assert gen.structural_violation(parse_scenario_dict(raw, "t")) is None


def test_structural_violation_rejects_fake_turn_markers_in_prompt():
    import generate_scenarios as gen
    from scenario_schema import parse_scenario_dict
    # Live generator miss (wizard_impatient_multiturn_001): it pasted the
    # synthesized "[Turn 1 — user]: ..." rendering into a single prompt string.
    # site_editor scrubs such markers, so that's one weird message, not a
    # conversation — must be authored via 'turns'.
    raw = {"id": "fake_turns_001", "name": "n",
           "prompt": "[Turn 1 — user]: Hi.\n\n[Turn 2 — user]: Build my site.",
           "checks": {"expected_tools": ["branch_and_edit_content"]}}
    violation = gen.structural_violation(parse_scenario_dict(raw, "t"))
    assert violation and "turns" in violation.lower()
    raw_system = {"id": "fake_system_001", "name": "n",
                  "prompt": "[SYSTEM] The website build failed.",
                  "checks": {"expected_tools": ["branch_and_edit_content"]}}
    violation = gen.structural_violation(parse_scenario_dict(raw_system, "t"))
    assert violation and "is_system" in violation


def test_structural_violation_is_init_rejects_setup_and_file_checks():
    import generate_scenarios as gen
    from scenario_schema import parse_scenario_dict
    # is_init provisions an EMPTY workspace and live create_project writes a
    # NEW project dir outside the measured workspace — so setup and file/build/
    # dom checks can never pass live, even though a dry_run.edits reference can
    # fake-satisfy them offline (the exact class validate-before-promote misses).
    base = {"id": "init_bad_001", "name": "n", "is_init": True,
            "prompt": "I run a bakery called Crumb & Crust, build me a site",
            "checks": {"expected_tools": ["create_project"],
                       "judge": "Sam created the site."}}
    ok = parse_scenario_dict(base, "t")
    assert gen.structural_violation(ok) is None
    with_setup = dict(base, setup=[{"path": "content/settings.yaml",
                                    "content": "site:\n  name: x\n"}])
    violation = gen.structural_violation(parse_scenario_dict(with_setup, "t"))
    assert violation and "setup" in violation.lower()
    with_files = dict(base, checks={
        "expected_tools": ["create_project"],
        "file_contains": {"content/settings.yaml": ["Crumb & Crust"]},
        "judge": "Sam created the site."})
    violation = gen.structural_violation(parse_scenario_dict(with_files, "t"))
    assert violation and "create_project" in violation


def test_generator_quarantines_structural_violations(tmp_path, monkeypatch):
    scenarios_dir = tmp_path / "scenarios"
    (scenarios_dir / "seed").mkdir(parents=True)
    (scenarios_dir / "seed" / "seed.json").write_text(json.dumps(SEED))
    payload = {"scenarios": [
        {"id": "mt_no_transcript_001", "name": "Bad multi-turn judge",
         "turns": [{"prompt": "change the tagline to 'Hi there'"},
                   {"prompt": "publish"}],
         "checks": {"expected_tools": ["branch_and_edit_content"],
                    "judge": "Tagline updated and published."},
         "dry_run": {"text": "done",
                     "tool_calls": [{"name": "branch_and_edit_content",
                                     "args": {}}],
                     "edits": {"content/settings.yaml":
                               "site:\n  name: x\n  tagline: 'Hi there'\n"}}},
    ]}
    body = f'print(json.dumps({{"result": json.dumps({json.dumps(payload)})}}))'
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    generate_scenarios.main(["--count", "1", "--scenarios-dir", str(scenarios_dir)])
    assert not list((scenarios_dir / "generated").glob("mt_no_transcript_001.json"))
    assert (scenarios_dir / "generated" / "rejected"
            / "mt_no_transcript_001.json").exists()


def test_generator_promotes_valid_multiturn_and_init_candidates(tmp_path, monkeypatch):
    # End-to-end through validate_candidate: a transcript-aware multi-turn
    # candidate replays its dry_run over the turns, and an is_init candidate
    # validates on an EMPTY workspace (expected_tools satisfied by tool_calls).
    scenarios_dir = tmp_path / "scenarios"
    (scenarios_dir / "seed").mkdir(parents=True)
    (scenarios_dir / "seed" / "seed.json").write_text(json.dumps(SEED))
    payload = {"scenarios": [
        {"id": "mt_ok_001", "name": "Tagline then publish",
         "turns": [{"prompt": "change the tagline to 'Hi there'"},
                   {"prompt": "publish"}],
         "checks": {"expected_tools": ["branch_and_edit_content"],
                    "file_contains": {"content/settings.yaml": ["Hi there"]},
                    "judge": "Read transcript.json. Turn 1: updated tagline, "
                             "no publish. Turn 2: published. Fail if turn 1 "
                             "published."},
         "dry_run": {"text": "Going live now!",
                     "tool_calls": [{"name": "branch_and_edit_content",
                                     "args": {}}],
                     "edits": {"content/settings.yaml":
                               'site:\n  name: "x"\n  tagline: "Hi there"\n'}}},
        {"id": "init_ok_001", "name": "Bakery onboarding",
         "prompt": "I run a bakery called Crumb Line, can you build me a site?",
         "is_init": True,
         "checks": {"expected_tools": ["create_project"],
                    "judge": "Sam created the site with a bakery-appropriate "
                             "name, no placeholder."},
         "dry_run": {"text": "Your site is being prepared!",
                     "tool_calls": [{"name": "create_project", "args": {}}],
                     "edits": {}}},
    ]}
    # json.dumps twice: the payload contains JSON booleans (true), which are
    # not valid Python literals inside the stub's source — embed as a string.
    body = f'print(json.dumps({{"result": {json.dumps(json.dumps(payload))}}}))'
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    generate_scenarios.main(["--count", "2", "--scenarios-dir", str(scenarios_dir)])
    written = sorted(p.stem for p in (scenarios_dir / "generated").glob("*.json"))
    assert written == ["init_ok_001", "mt_ok_001"]


def test_generator_quarantines_discovery_expected_tools(tmp_path, monkeypatch):
    # expected_tools must assert the OUTCOME (edit tools), never the discovery
    # path: mandating list/read false-fails a correct solution that skipped
    # discovery (e.g. the site snapshot already showed the file).
    scenarios_dir = tmp_path / "scenarios"
    (scenarios_dir / "seed").mkdir(parents=True)
    (scenarios_dir / "seed" / "seed.json").write_text(json.dumps(SEED))
    payload = {"scenarios": [
        {"id": "discovery_tools_001", "name": "Bad expected_tools",
         "prompt": "Add a pricing page with three plans",
         "checks": {"expected_tools": ["list_content_files",
                                       "branch_and_edit_content"],
                    "files_changed": ["content/pages/pricing.mdx"]},
         "dry_run": {"text": "done",
                     "tool_calls": [{"name": "list_content_files", "args": {}},
                                    {"name": "branch_and_edit_content", "args": {}}],
                     "edits": {"content/pages/pricing.mdx":
                               "---\ntitle: Pricing\n---\nPricing page\n"}}},
    ]}
    body = f'print(json.dumps({{"result": json.dumps({json.dumps(payload)})}}))'
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    generate_scenarios.main(["--count", "1", "--scenarios-dir", str(scenarios_dir)])
    assert not list((scenarios_dir / "generated").glob("discovery_tools_001.json"))
    rejected = scenarios_dir / "generated" / "rejected" / "discovery_tools_001.json"
    assert rejected.exists()
