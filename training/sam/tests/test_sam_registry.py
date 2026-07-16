import os
import subprocess

import pytest

import sam_registry


def test_load_missing_registry_is_empty(tmp_path):
    assert sam_registry.load(tmp_path / "registry.json") == {}


def test_registry_lock_acquire_write_pid_and_release(tmp_path):
    path = tmp_path / "registry.json"
    lock = sam_registry.acquire_lock(path)
    assert lock.exists()
    assert lock.read_text().strip() == str(os.getpid())
    sam_registry.release_lock(lock)
    assert not lock.exists()


def test_registry_lock_conflict_with_live_holder_fails_fast(tmp_path):
    # The registry is load-once/save-whole per run: a second concurrent run
    # would silently clobber the first's records, so it must fail fast.
    path = tmp_path / "registry.json"
    lock = sam_registry.acquire_lock(path)      # held by THIS live process
    with pytest.raises(sam_registry.RegistryLockError, match=r"pid \d+"):
        sam_registry.acquire_lock(path)
    assert lock.exists()                         # loser must not break the lock
    sam_registry.release_lock(lock)


def test_registry_lock_stale_dead_holder_is_reclaimed(tmp_path):
    path = tmp_path / "registry.json"
    proc = subprocess.Popen(["true"])
    proc.wait()                                  # pid now dead (and reaped)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.write_text(str(proc.pid))
    lock = sam_registry.acquire_lock(path)       # stale: holder is gone
    assert lock.read_text().strip() == str(os.getpid())
    sam_registry.release_lock(lock)


def test_registry_lock_garbage_pidfile_is_reclaimed(tmp_path):
    path = tmp_path / "registry.json"
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.write_text("not-a-pid")
    lock = sam_registry.acquire_lock(path)
    assert lock.read_text().strip() == str(os.getpid())
    sam_registry.release_lock(lock)


def test_record_run_and_save_roundtrip(tmp_path):
    path = tmp_path / "registry.json"
    reg = sam_registry.load(path)
    sam_registry.record_run(reg, "s1", "2026-06-11T10-00", "fail")
    sam_registry.record_run(reg, "s1", "2026-06-11T11-00", "pass",
                            fix={"run": "2026-06-11T11-00",
                                 "files": ["src/agent/prompts.py"]})
    sam_registry.save(path, reg)
    reg2 = sam_registry.load(path)
    assert [r["result"] for r in reg2["s1"]["runs"]] == ["fail", "pass"]
    assert reg2["s1"]["fixes"][0]["files"] == ["src/agent/prompts.py"]


def test_flaky_detection():
    assert sam_registry.is_flaky(
        [{"run": "a", "result": "pass"}, {"run": "b", "result": "fail"}])
    assert not sam_registry.is_flaky(
        [{"run": "a", "result": "fail"}, {"run": "b", "result": "fail"}])
    assert not sam_registry.is_flaky([])
    # only the 3 most recent runs count
    assert not sam_registry.is_flaky(
        [{"run": "a", "result": "pass"},
         {"run": "b", "result": "fail"},
         {"run": "c", "result": "fail"},
         {"run": "d", "result": "fail"}])


def test_needs_human_flag():
    reg = {}
    sam_registry.record_run(reg, "s1", "r1", "fail")
    sam_registry.set_needs_human(reg, "s1")
    assert reg["s1"]["needs_human"] is True


def test_record_run_decisive_pass_clears_needs_human():
    # A scenario flagged needs_human that later passes decisively is no longer
    # blocked on a human — record_run clears the flag so the generator stops
    # treating a solved scenario as "weak".
    reg = {}
    sam_registry.record_run(reg, "s1", "r1", "fail")
    sam_registry.set_needs_human(reg, "s1")
    assert reg["s1"]["needs_human"] is True
    sam_registry.record_run(reg, "s1", "r2", "pass")
    assert reg["s1"]["needs_human"] is False


def test_record_run_fail_keeps_needs_human():
    # Only a decisive pass clears the flag; a fail leaves it set.
    reg = {}
    sam_registry.set_needs_human(reg, "s1")
    sam_registry.record_run(reg, "s1", "r2", "fail")
    assert reg["s1"]["needs_human"] is True


def test_record_run_error_keeps_needs_human():
    # An "error" outcome is harness/infra (non-decisive) and must not clear the
    # flag — Sam never got a clean pass.
    reg = {}
    sam_registry.set_needs_human(reg, "s1")
    sam_registry.record_run(reg, "s1", "r2", "error")
    assert reg["s1"]["needs_human"] is True


def test_weak_scenario_ids():
    registry = {
        "healthy": {"runs": [{"run": "r", "result": "pass"}] * 5,
                    "fixes": [], "needs_human": False},
        "needs_human": {"runs": [{"run": "r", "result": "pass"}],
                        "fixes": [], "needs_human": True},
        "recent_fail": {"runs": [{"run": "r", "result": "pass"},
                                 {"run": "r", "result": "fail"}],
                        "fixes": [], "needs_human": False},
        "low_rate": {"runs": [{"run": "r", "result": "fail"},
                              {"run": "r", "result": "fail"},
                              {"run": "r", "result": "pass"}],
                     "fixes": [], "needs_human": False},
        "goalpost_fixed": {"runs": [{"run": "r", "result": "pass"}],
                           "fixes": [{"run": "r", "files": ["x"],
                                      "provenance": "goalpost"}],
                           "needs_human": False},
    }
    weak = set(sam_registry.weak_scenario_ids(registry))
    assert weak == {"needs_human", "recent_fail", "low_rate", "goalpost_fixed"}


def test_pass_rate_window_only_counts_recent_decisive():
    # A scenario that failed 5 times long ago but has passed the last 5 runs:
    # lifetime rate is 0.5, but a last-5 window judges it on recent behaviour.
    runs = [{"run": "r", "result": "fail"}] * 5 + [{"run": "r", "result": "pass"}] * 5
    assert sam_registry.pass_rate(runs) == 0.5
    assert sam_registry.pass_rate(runs, window=5) == 1.0


def test_pass_rate_window_skips_errors_for_slot():
    # Errors are non-decisive and must not consume a window slot: the window
    # looks back through them to the last `window` pass/fail outcomes.
    runs = ([{"run": "r", "result": "fail"}]
            + [{"run": "r", "result": "pass"}] * 5
            + [{"run": "r", "result": "error"}] * 3)
    # last 5 decisive = the 5 passes (leading fail + trailing errors excluded)
    assert sam_registry.pass_rate(runs, window=5) == 1.0


def test_weak_scenario_ids_recovered_scenario_not_weak():
    # A "recovered" scenario — many old fails, then a clean recent streak — must
    # drop out of the weak set once the windowed rate is healthy, so the generator
    # stops over-targeting an already-solved scenario. (Lifetime rate 0.5 < 0.8
    # would wrongly keep it weak forever.)
    registry = {
        "recovered": {
            "runs": [{"run": "r", "result": "fail"}] * 5
                    + [{"run": "r", "result": "pass"}] * 5,
            "fixes": [], "needs_human": False},
    }
    assert sam_registry.weak_scenario_ids(registry) == []


def test_weak_scenario_ids_tolerates_malformed_run_entry():
    # A run entry missing "result" (truncated/legacy registry) must not crash
    # the weak-scenario scan — it's treated as non-decisive, not a failure.
    registry = {
        "partial": {"runs": [{"run": "r", "result": "pass"}, {"run": "r2"}],
                    "fixes": [], "needs_human": False},
    }
    assert sam_registry.weak_scenario_ids(registry) == []
