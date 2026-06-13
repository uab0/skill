"""Regression tests for bug-hunter-uab0 deterministic dispatch."""

import json
import subprocess
import sys
from pathlib import Path

from run_dev import extract_last_json_block


ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "dev_set" / "pairwise" / "reference_tasks"
DISPATCH = ROOT / "skills" / "bug-hunter-uab0" / "scripts" / "dispatch.py"


def _run_dispatch(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(DISPATCH), json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    obj = extract_last_json_block(proc.stdout)
    assert obj is not None, proc.stdout
    return obj


def _load(task_id: str) -> dict:
    return json.loads((TASK_DIR / f"{task_id}.json").read_text(encoding="utf-8"))


def _bug_keys(obj: dict) -> set[tuple[int, str]]:
    return {(int(b["line_start"]), str(b["type"])) for b in obj.get("bugs", [])}


def _ground_truth_keys(task: dict) -> set[tuple[int, str]]:
    return {(int(b["line_start"]), str(b["type"])) for b in task.get("bugs_in_buggy", [])}


def test_dispatch_catches_reference_buggy_code():
    for path in sorted(TASK_DIR.glob("task_pair_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        out = _run_dispatch({
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "code": task["buggy_code"],
        })
        assert out["verdict"] == "buggy", task["task_id"]
        keys = _bug_keys(out)
        truth = _ground_truth_keys(task)
        assert keys & truth, (task["task_id"], keys, truth)


def test_dispatch_clean_on_reference_clean_code():
    for path in sorted(TASK_DIR.glob("task_pair_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        out = _run_dispatch({
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "code": task["clean_code"],
        })
        assert out["verdict"] == "clean", (task["task_id"], out)
        assert out["bugs"] == []


def test_dispatch_suppresses_known_family_probe_duplicates():
    for task_id in ("task_pair_004", "task_pair_005"):
        task = _load(task_id)
        out = _run_dispatch({
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "constraints": task["constraints"],
            "code": task["buggy_code"],
        })
        assert _bug_keys(out) == _ground_truth_keys(task)


def test_hybrid_uses_candidate_bugs_for_unknown_clean_low_confidence():
    payload = {
        "original": {
            "task_id": "custom_abs_001",
            "task_description": (
                "Implement absolute_value(x): return the non-negative absolute value "
                "of integer x. For negative x, return -x; otherwise return x."
            ),
            "constraints": {"entry_function": "absolute_value", "max_loc": 500, "imports_forbidden": []},
            "code": "def absolute_value(x):\n    return x\n",
        },
        "mode": "hybrid",
        "candidate_bugs": [
            {
                "line_start": 2,
                "line_end": 2,
                "severity": "high",
                "type": "logic_error",
                "description": "Returns negative inputs unchanged instead of negating them.",
                "suggested_fix": "Return -x for negative inputs.",
            }
        ],
    }
    out = _run_dispatch(payload)
    assert out["verdict"] == "buggy"
    assert _bug_keys(out) == {(2, "logic_error")}
