"""Tests for the Open Track deterministic evaluator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "open-stat-analyst-uab0" / "scripts"
EVALUATE = SCRIPT_DIR / "evaluate.py"


def _load_evaluator():
    spec = importlib.util.spec_from_file_location("open_stat_evaluate", EVALUATE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


evaluator = _load_evaluator()


def test_evaluator_passes_correct_descriptive_result():
    scenario = {
        "task_id": "open_stat_eval_desc",
        "question": "Summarize spend.",
        "data": [{"spend": 10.0}, {"spend": 20.0}, {"spend": 30.0}],
    }
    result = {
        "task_id": "open_stat_eval_desc",
        "analysis_type": "descriptive_stats",
        "columns": {"value": "spend"},
        "result": {
            "count": 3,
            "mean": 20.0,
            "median": 20.0,
            "stdev": 10.0,
            "min": 10.0,
            "max": 30.0,
            "q1": 15.0,
            "q3": 25.0,
            "iqr": 10.0,
        },
        "decision": "computed",
        "warnings": [],
        "confidence": 0.8,
    }
    report = evaluator.evaluate(scenario, result)
    assert report["passed"], report


def test_evaluator_fails_wrong_numeric_result():
    scenario = {
        "task_id": "open_stat_eval_desc_bad",
        "question": "Summarize spend.",
        "data": [{"spend": 10.0}, {"spend": 20.0}, {"spend": 30.0}],
    }
    result = {
        "task_id": "open_stat_eval_desc_bad",
        "analysis_type": "descriptive_stats",
        "columns": {"value": "spend"},
        "result": {
            "count": 3,
            "mean": 999.0,
            "median": 20.0,
            "stdev": 10.0,
            "min": 10.0,
            "max": 30.0,
            "q1": 15.0,
            "q3": 25.0,
            "iqr": 10.0,
        },
        "decision": "computed",
        "warnings": [],
        "confidence": 0.8,
    }
    report = evaluator.evaluate(scenario, result)
    assert not report["passed"]
    assert any(check["name"] == "result" and not check["passed"] for check in report["checks"])


def test_evaluator_passes_unsupported_t_test_rejection():
    scenario = {
        "task_id": "open_stat_unsupported_ttest_001",
        "question": "Run a two-sample t-test comparing score between group A and group B. Return the p-value.",
        "data": [
            {"group": "A", "score": 10.0},
            {"group": "A", "score": 12.0},
            {"group": "B", "score": 18.0},
            {"group": "B", "score": 17.0},
        ],
    }
    result = {
        "task_id": "open_stat_unsupported_ttest_001",
        "analysis_type": "unknown",
        "columns": {},
        "result": {},
        "decision": "invalid_input",
        "warnings": ["unsupported statistical method requested: t-test"],
        "confidence": 0.3,
    }
    report = evaluator.evaluate(scenario, result)
    assert report["passed"], report


def test_evaluator_cli_exit_codes(tmp_path: Path):
    scenario_path = tmp_path / "scenario.json"
    result_path = tmp_path / "result.json"
    scenario_path.write_text(json.dumps({
        "task_id": "open_stat_eval_cli",
        "question": "For each channel, compute the mean revenue and row count.",
        "data": [
            {"channel": "email", "revenue": 10.0},
            {"channel": "email", "revenue": 14.0},
        ],
    }), encoding="utf-8")
    result_path.write_text(json.dumps({
        "task_id": "open_stat_eval_cli",
        "analysis_type": "group_aggregate",
        "columns": {"group": "channel", "value": "revenue"},
        "result": {"groups": {"email": {"count": 2, "mean": 12.0}}, "aggregations": ["count", "mean"]},
        "decision": "computed",
        "warnings": [],
        "confidence": 0.8,
    }), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(EVALUATE), "--input", str(scenario_path), "--result", str(result_path)],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["passed"] is True
