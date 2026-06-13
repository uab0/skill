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
