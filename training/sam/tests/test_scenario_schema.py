import json

import pytest

from scenario_schema import (
    EDIT_TOOLS, ScenarioError, load_scenarios, parse_scenario_dict,
)


def test_parse_minimal_scenario():
    s = parse_scenario_dict({"id": "a", "name": "A", "prompt": "do a"}, "src.json")
    assert s.id == "a" and s.negative is False
    assert s.checks.expected_tools == [] and s.checks.judge is None


def test_parse_full_scenario():
    raw = {
        "id": "b", "name": "B", "prompt": "do b",
        "setup": [{"path": "content/x.md", "content": "hi"}],
        "checks": {
            "expected_tools": ["branch_and_edit_content"],
            "files_changed": ["content/x.md"],
            "file_contains": {"content/x.md": ["hi"]},
            "build": True,
            "dom": [{"page": "/", "selector": "h1", "contains": "Hi"}],
            "judge": "looks right",
        },
        "negative": False,
    }
    s = parse_scenario_dict(raw, "src.json")
    assert s.checks.build is True
    assert s.checks.dom[0].selector == "h1"


def test_missing_required_key_raises():
    with pytest.raises(ScenarioError, match="prompt"):
        parse_scenario_dict({"id": "c", "name": "C"}, "src.json")


def test_load_scenarios_accepts_object_and_array(tmp_path):
    d = tmp_path / "scenarios"
    (d / "seed").mkdir(parents=True)
    (d / "seed" / "one.json").write_text(json.dumps(
        {"id": "one", "name": "One", "prompt": "p1"}))
    (d / "seed" / "two.json").write_text(json.dumps(
        [{"id": "two", "name": "Two", "prompt": "p2"},
         {"id": "three", "name": "Three", "prompt": "p3"}]))
    ids = [s.id for s in load_scenarios(d)]
    # files are processed sorted by path; array entries keep file order
    assert ids == ["one", "two", "three"]


def test_load_scenarios_rejects_duplicate_ids(tmp_path):
    d = tmp_path / "scenarios"
    d.mkdir()
    (d / "a.json").write_text(json.dumps(
        [{"id": "dup", "name": "X", "prompt": "p"},
         {"id": "dup", "name": "Y", "prompt": "q"}]))
    with pytest.raises(ScenarioError, match="dup"):
        load_scenarios(d)


def test_edit_tools_vocabulary():
    assert "branch_and_edit_content" in EDIT_TOOLS
    assert "read_content_file" not in EDIT_TOOLS


def test_split_explicit_override_wins():
    from scenario_schema import parse_scenario_dict, is_holdout
    s = parse_scenario_dict(
        {"id": "x_001", "name": "n", "prompt": "p", "split": "holdout"}, "t")
    assert s.split == "holdout"
    assert is_holdout(s) is True


def test_split_defaults_to_deterministic_hash():
    from scenario_schema import parse_scenario_dict, is_holdout
    s = parse_scenario_dict({"id": "hero_title_001", "name": "n", "prompt": "p"}, "t")
    assert s.split is None
    # deterministic per id (sha1(id) % 5 != 0 for this id, so it's train, not
    # holdout) — a hard-coded expectation, not a tautological self-comparison
    assert is_holdout(s) is False


def test_split_invalid_value_rejected():
    import pytest
    from scenario_schema import parse_scenario_dict, ScenarioError
    with pytest.raises(ScenarioError, match="split"):
        parse_scenario_dict(
            {"id": "x", "name": "n", "prompt": "p", "split": "maybe"}, "t")


def test_load_scenarios_skips_rejected_quarantine(tmp_path):
    # Quarantined generator rejects (scenarios/.../rejected/*.json) must never be
    # loaded as corpus — even when malformed (else a bad reject breaks the loader
    # and would otherwise be evaluated as a real scenario).
    sdir = tmp_path / "scenarios" / "generated"
    sdir.mkdir(parents=True)
    (sdir / "good.json").write_text(json.dumps(
        {"id": "good_001", "name": "G", "prompt": "do g"}))
    rej = sdir / "rejected"
    rej.mkdir()
    (rej / "bad.json").write_text(json.dumps(
        {"id": "bad_001", "name": "B", "prompt": "do b",
         "setup": {"content/x.mdx": "x"}}))  # malformed; raises if ever loaded
    out = load_scenarios(tmp_path / "scenarios")
    assert [s.id for s in out] == ["good_001"]


def test_setup_as_dict_rejected():
    # Generator miss: `setup` authored as a path->content map (the dry_run.edits
    # shape) instead of a list of {path, content}. list(dict) would silently
    # become a list of path strings and crash provision_workspace; reject it.
    with pytest.raises(ScenarioError, match="setup"):
        parse_scenario_dict(
            {"id": "x", "name": "n", "prompt": "p",
             "setup": {"content/pages/services.mdx": "---\n---\nhi\n"}}, "t")


def test_setup_item_missing_keys_rejected():
    with pytest.raises(ScenarioError, match="setup"):
        parse_scenario_dict(
            {"id": "x", "name": "n", "prompt": "p",
             "setup": [{"path": "content/x.mdx"}]}, "t")  # no 'content'


def test_files_absent_parsed_and_delete_tool_is_edit_tool():
    from scenario_schema import EDIT_TOOLS
    s = parse_scenario_dict(
        {"id": "d1", "name": "n", "prompt": "p",
         "checks": {"files_absent": ["content/pages/about.mdx"]}}, "t")
    assert s.checks.files_absent == ["content/pages/about.mdx"]
    # delete_content_file mutates the site: negative scenarios must flag it.
    assert "delete_content_file" in EDIT_TOOLS


def test_is_system_and_is_init_flags_parsed():
    # The self-heal ([SYSTEM]) and onboarding-wizard prompt sections are only
    # reachable through these flags — site_editor scrubs the markers from user
    # input, so scenarios must declare the turn type explicitly.
    s = parse_scenario_dict(
        {"id": "x", "name": "n", "prompt": "p", "is_system": True}, "t")
    assert s.is_system is True and s.is_init is False
    s2 = parse_scenario_dict(
        {"id": "y", "name": "n", "prompt": "p", "is_init": True}, "t")
    assert s2.is_init is True and s2.is_system is False
    s3 = parse_scenario_dict({"id": "z", "name": "n", "prompt": "p"}, "t")
    assert s3.is_system is False and s3.is_init is False


def test_turns_parsed_normalized_and_prompt_synthesized():
    raw = {"id": "mt", "name": "n",
           "turns": [{"prompt": "change tagline"},
                     {"prompt": "publish"},
                     {"prompt": "build logs...", "is_system": True}]}
    s = parse_scenario_dict(raw, "t")
    assert s.turns[0] == {"prompt": "change tagline",
                          "is_system": False, "is_init": False}
    assert s.turns[2]["is_system"] is True
    # judge/fixer read scenario.prompt — it must render the whole conversation
    assert "change tagline" in s.prompt and "publish" in s.prompt


def test_turns_first_turn_is_init_drives_provisioning_flag():
    s = parse_scenario_dict(
        {"id": "mt2", "name": "n",
         "turns": [{"prompt": "hi", "is_init": True},
                   {"prompt": "a bakery", "is_init": True}]}, "t")
    assert s.is_init is True   # workspace provisioning keys on this


def test_turns_and_prompt_are_mutually_exclusive():
    with pytest.raises(ScenarioError, match="turns"):
        parse_scenario_dict(
            {"id": "x", "name": "n", "prompt": "p",
             "turns": [{"prompt": "q"}]}, "t")


def test_malformed_or_empty_turns_rejected():
    with pytest.raises(ScenarioError, match="turns"):
        parse_scenario_dict({"id": "x", "name": "n", "turns": ["a string"]}, "t")
    with pytest.raises(ScenarioError, match="turns"):
        parse_scenario_dict({"id": "x", "name": "n", "turns": []}, "t")
    with pytest.raises(ScenarioError, match="turns"):
        parse_scenario_dict(
            {"id": "x", "name": "n", "turns": [{"is_system": True}]}, "t")


def test_dom_check_count_and_absent_parsed():
    s = parse_scenario_dict(
        {"id": "dc", "name": "n", "prompt": "p",
         "checks": {"dom": [
             {"page": "/", "selector": "footer", "count": 1,
              "contains": "©"},
             {"page": "/", "selector": ".popup", "absent": True}]}}, "t")
    first, second = s.checks.dom
    assert first.count == 1 and first.contains == "©" and first.absent is False
    assert second.absent is True and second.contains is None


def test_dom_check_must_assert_something():
    # A dom check with neither contains nor count nor absent verifies nothing.
    with pytest.raises(ScenarioError, match="asserts nothing"):
        parse_scenario_dict(
            {"id": "dc2", "name": "n", "prompt": "p",
             "checks": {"dom": [{"page": "/", "selector": "h1"}]}}, "t")


def test_dom_check_absent_conflicts_with_contains_and_count():
    with pytest.raises(ScenarioError, match="absent"):
        parse_scenario_dict(
            {"id": "dc3", "name": "n", "prompt": "p",
             "checks": {"dom": [{"page": "/", "selector": "h1",
                                 "absent": True, "contains": "x"}]}}, "t")
    with pytest.raises(ScenarioError, match="absent"):
        parse_scenario_dict(
            {"id": "dc4", "name": "n", "prompt": "p",
             "checks": {"dom": [{"page": "/", "selector": "h1",
                                 "absent": True, "count": 2}]}}, "t")


def test_not_contains_checks_parsed():
    s = parse_scenario_dict(
        {"id": "nc", "name": "n", "prompt": "p",
         "checks": {"file_not_contains": {"content/settings.yaml": ["Old Name"]},
                    "response_not_contains": ["may still see an empty page"]}}, "t")
    assert s.checks.file_not_contains == {"content/settings.yaml": ["Old Name"]}
    assert s.checks.response_not_contains == ["may still see an empty page"]
