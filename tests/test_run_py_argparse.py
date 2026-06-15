"""Compatibility tests for direct scripts/run.py flag invocation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import aiase_contract as contract


ROOT = Path(__file__).resolve().parents[1]


def _run_with_result(script: Path, args: list[str], tmp_path: Path) -> dict:
    result_path = tmp_path / "result.json"
    env = dict(os.environ)
    env["AIASE_RESULT_PATH"] = str(result_path)
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    obj = contract.read_result(str(result_path))
    assert obj is not None, proc.stdout
    return obj


def test_text2sql_run_py_accepts_flag_args(tmp_path):
    obj = _run_with_result(
        ROOT / "skills" / "text2sql-uab0" / "scripts" / "run.py",
        [
            "--task_id", "t1",
            "--sql", "SELECT 1;",
            "--rationale", "direct flag compatibility",
            "--confidence", "0.8",
        ],
        tmp_path,
    )
    assert obj == {
        "task_id": "t1",
        "sql": "SELECT 1;",
        "rationale": "direct flag compatibility",
        "confidence": 0.8,
    }


def test_code_author_run_py_accepts_flag_args(tmp_path):
    obj = _run_with_result(
        ROOT / "skills" / "code-author-uab0" / "scripts" / "run.py",
        [
            "--task_id", "p1",
            "--code", "def solution():\n    return 1\n",
            "--loc", "2",
            "--self_test_passed", "3",
            "--self_test_failed", "0",
            "--rationale", "direct flag compatibility",
            "--confidence", "0.9",
        ],
        tmp_path,
    )
    assert obj["task_id"] == "p1"
    assert obj["loc"] == 2
    assert obj["self_test_results"] == {"passed": 3, "failed": 0}
    assert obj["confidence"] == 0.9


def test_bug_hunter_run_py_accepts_flag_args(tmp_path):
    bugs = [{
        "line_start": 2,
        "line_end": 2,
        "severity": "high",
        "type": "logic_error",
        "description": "The return value contradicts the specification.",
        "suggested_fix": "Return the value required by the task.",
    }]
    obj = _run_with_result(
        ROOT / "skills" / "bug-hunter-uab0" / "scripts" / "run.py",
        [
            "--task_id", "p2",
            "--verdict", "buggy",
            "--confidence", "0.75",
            "--bugs", json.dumps(bugs),
        ],
        tmp_path,
    )
    assert obj["task_id"] == "p2"
    assert obj["verdict"] == "buggy"
    assert obj["bugs"] == bugs
    assert obj["confidence"] == 0.75


def test_open_stat_run_py_accepts_flag_args(tmp_path):
    obj = _run_with_result(
        ROOT / "skills" / "open-stat-analyst-uab0" / "scripts" / "run.py",
        [
            "--task_id", "o1",
            "--analysis_type", "descriptive_stats",
            "--columns", '{"value":"x"}',
            "--result", '{"count":2,"mean":1.5}',
            "--decision", "computed",
            "--warnings", '["ok"]',
            "--confidence", "0.8",
        ],
        tmp_path,
    )
    assert obj["task_id"] == "o1"
    assert obj["analysis_type"] == "descriptive_stats"
    assert obj["columns"] == {"value": "x"}
    assert obj["result"] == {"count": 2, "mean": 1.5}
    assert obj["warnings"] == ["ok"]
