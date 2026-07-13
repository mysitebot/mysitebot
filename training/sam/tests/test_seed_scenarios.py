from pathlib import Path

from scenario_schema import load_scenarios

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def test_seed_corpus_loads_and_is_well_formed():
    # exact-set assertions apply to the seed corpus only — generated/
    # grows over time and must not break this test
    scenarios = load_scenarios(SCENARIOS_DIR / "seed")
    ids = {s.id for s in scenarios}
    assert {"hero_title_001", "contact_email_001", "site_tagline_001",
            "about_page_001", "privacy_violation_001",
            "ambiguous_request_001"} <= ids
    negatives = {s.id for s in scenarios if s.negative}
    assert negatives == {"privacy_violation_001", "ambiguous_request_001"}


def test_full_corpus_well_formed():
    # invariant over seed + generated: positive scenarios must declare
    # at least one deterministic check
    for s in load_scenarios(SCENARIOS_DIR):
        if not s.negative:
            assert s.checks.expected_tools or s.checks.files_changed, s.id
