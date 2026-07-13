"""Persistent per-scenario state: pass history, fixes, flaky/needs-human flags."""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

WEAK_PASS_RATE = 0.8
PASS_RATE_WINDOW = 5  # only the last-N decisive runs decide weak vs. healthy:
                      # a scenario that failed long ago but is green now is solved.


def load(path: Path) -> Dict:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save(path: Path, registry: Dict) -> None:
    # Write to a sibling temp file and atomically replace, so a crash/SIGINT
    # mid-write can't truncate registry.json — the next --fix run's regression
    # gate and weak_scenario_ids depend on it being intact.
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(registry, indent=2) + "\n")
    os.replace(tmp, path)


class RegistryLockError(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # exists, owned by someone else
    return True


def acquire_lock(path: Path) -> Path:
    """Exclusive per-registry lock for a whole run. The registry is
    load-once/save-whole (run_loop loads at start and rewrites the full dict
    per scenario), so two overlapping runs silently clobber each other's
    records; the second run must fail fast instead. The lock is a pidfile next
    to registry.json created atomically (write-then-link); a lock whose holder
    pid is no longer alive is stale and reclaimed. Returns the lock path —
    pass it to release_lock on exit."""
    path = Path(path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    tmp = lock_path.with_suffix(lock_path.suffix + f".{os.getpid()}")
    tmp.write_text(f"{os.getpid()}\n")
    try:
        for _ in range(2):   # second pass retries once after a stale reclaim
            try:
                os.link(tmp, lock_path)   # atomic create WITH content
                return lock_path
            except FileExistsError:
                pass
            try:
                holder = int(lock_path.read_text().strip())
            except (FileNotFoundError, ValueError):
                holder = 0                # unreadable/garbage => stale
            if holder > 0 and _pid_alive(holder):
                raise RegistryLockError(
                    f"{path} is locked by a live run (pid {holder}, "
                    f"{lock_path}); a concurrent run would clobber its "
                    f"registry updates — wait for it to finish, or delete "
                    f"the lock file if that pid is not a sam run.")
            try:
                lock_path.unlink()        # stale: holder is dead
            except FileNotFoundError:
                pass
        raise RegistryLockError(f"could not acquire {lock_path}")
    finally:
        tmp.unlink()


def release_lock(lock_path: Path) -> None:
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        pass


def is_flaky(runs: List[Dict]) -> bool:
    """Mixed pass/fail within the 3 most recent runs."""
    recent = {r.get("result") for r in runs[-3:]} & {"pass", "fail"}
    return len(recent) > 1


def record_run(registry: Dict, scenario_id: str, run_id: str, result: str,
               fix: Optional[Dict] = None) -> None:
    entry = registry.setdefault(
        scenario_id, {"runs": [], "fixes": [], "flaky": False,
                      "needs_human": False})
    entry["runs"].append({"run": run_id, "result": result})
    if fix:
        entry["fixes"].append(fix)
    entry["flaky"] = is_flaky(entry["runs"])
    # A decisive pass clears needs_human: the scenario is no longer blocked on a
    # human. Non-decisive results ("error") and fails leave the flag untouched.
    if result == "pass":
        entry["needs_human"] = False


def set_needs_human(registry: Dict, scenario_id: str) -> None:
    entry = registry.setdefault(
        scenario_id, {"runs": [], "fixes": [], "flaky": False,
                      "needs_human": False})
    entry["needs_human"] = True


def pass_rate(runs: List[Dict], window: Optional[int] = None) -> float:
    """Calculate pass rate from runs. Returns 1.0 when no decisive runs.

    With window=None the rate is over ALL decisive runs (lifetime). With an int
    window, only the last `window` decisive runs count — so a recovered scenario
    is judged on its recent behaviour, not diluted by old failures forever.
    Errors are non-decisive and never consume a window slot.
    """
    decisive = [r for r in runs if r.get("result") in ("pass", "fail")]
    if not decisive:
        return 1.0
    if window is not None:
        decisive = decisive[-window:]
    return sum(1 for r in decisive if r.get("result") == "pass") / len(decisive)


def weak_scenario_ids(registry: Dict, threshold: float = WEAK_PASS_RATE) -> List[str]:
    """Scenarios worth generating harder variations around: flagged needs_human,
    most recent run failed, historical pass-rate below threshold, or ever fixed
    with a goalpost-class change."""
    weak = []
    for sid in sorted(registry):
        entry = registry[sid]
        runs = entry.get("runs", [])
        recent_fail = bool(runs) and runs[-1].get("result") == "fail"
        goalpost = any(f.get("provenance") == "goalpost"
                       for f in entry.get("fixes", []))
        if (entry.get("needs_human") or recent_fail
                or pass_rate(runs, window=PASS_RATE_WINDOW) < threshold or goalpost):
            weak.append(sid)
    return weak
