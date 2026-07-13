#!/usr/bin/env python3
"""Judge-model calibration: re-run the vote panel with a CANDIDATE meta-model
over existing run artifact dirs and compare against each dir's RECORDED panel
verdict (judge.json).

The corpus pass-history is measured against the current panel
(claude_cli.DEFAULT_MODEL), so a candidate must agree with that panel — catch
the same fails, not start failing good runs — before DEFAULT_MODEL changes.
Only dirs where the judge actually rendered a boolean verdict can calibrate;
deterministic-layer failures never reached the judge and are skipped.

Usage:
    python calibrate_judge.py --candidate claude-sonnet-5 \
        --dirs runs/<run>/<scenario> [more dirs...] [--out report.json]
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from _paths import bootstrap

bootstrap()

import judge  # noqa: E402


def load_case(scen_dir: Path):
    """(scenario-like, baseline_passed) from a run artifact dir, or None when
    the dir carries no boolean judge verdict. judge_scenario only reads
    .prompt / .negative / .checks.judge, so a namespace stands in for the
    Scenario (re-parsing scenario.json would trip the prompt/turns
    mutual-exclusion rule — multi-turn dirs store the synthesized prompt)."""
    jpath = scen_dir / "judge.json"
    spath = scen_dir / "scenario.json"
    if not (jpath.exists() and spath.exists()):
        return None
    baseline = json.loads(jpath.read_text()).get("passed")
    if baseline is None:
        return None
    raw = json.loads(spath.read_text())
    scenario = SimpleNamespace(
        prompt=raw.get("prompt", ""),
        negative=bool(raw.get("negative")),
        checks=SimpleNamespace(judge=(raw.get("checks") or {}).get("judge")))
    return scenario, baseline


def calibrate(dirs, candidate_model: str):
    rows = []
    for d in dirs:
        d = Path(d)
        case = load_case(d)
        if case is None:
            rows.append({"dir": str(d),
                         "skipped": "no boolean judge verdict in this dir"})
            continue
        scenario, baseline = case
        verdict = judge.judge_scenario(scenario, d, model=candidate_model)
        rows.append({
            "dir": str(d),
            "baseline": baseline,
            "candidate": verdict["passed"],
            "agree": verdict["passed"] == baseline,
            "candidate_reasoning": (verdict.get("reasoning") or "")[:300],
            "candidate_issues": list(verdict.get("issues") or [])[:5],
        })
    judged = [r for r in rows if "agree" in r]
    fails = [r for r in judged if r["baseline"] is False]
    passes = [r for r in judged if r["baseline"] is True]
    summary = {
        "candidate": candidate_model,
        "cases": len(judged),
        "skipped": len(rows) - len(judged),
        "agreement": (round(sum(r["agree"] for r in judged) / len(judged), 3)
                      if judged else None),
        "fail_cases_caught": sum(r["agree"] for r in fails),
        "fail_cases": len(fails),
        "pass_cases_agreed": sum(r["agree"] for r in passes),
        "pass_cases": len(passes),
    }
    return {"summary": summary, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", required=True,
                    help="meta-model id to calibrate (e.g. claude-sonnet-5)")
    ap.add_argument("--dirs", nargs="+", required=True, type=Path,
                    help="scenario artifact dirs (each with scenario.json + judge.json)")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the full JSON report here")
    args = ap.parse_args(argv)
    report = calibrate(args.dirs, args.candidate)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    for r in report["rows"]:
        if "skipped" in r:
            print(f"[skip ] {r['dir']}: {r['skipped']}")
            continue
        mark = "agree" if r["agree"] else "DISAGREE"
        print(f"[{mark:8}] {r['dir']}: baseline={r['baseline']} "
              f"candidate={r['candidate']}")
    return report


if __name__ == "__main__":
    main()
