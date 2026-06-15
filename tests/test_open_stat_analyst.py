"""Tests for the Open Track statistical analyst skill."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import aiase_contract as contract


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "open-stat-analyst-uab0" / "scripts"
DISPATCH = SCRIPT_DIR / "dispatch.py"


def _load_compute():
    spec = importlib.util.spec_from_file_location("open_stat_compute", SCRIPT_DIR / "compute.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


compute = _load_compute()


def _run_dispatch(payload: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="aiase_test_") as tmpdir:
        result_path = Path(tmpdir) / "result.json"
        env = dict(os.environ)
        env["AIASE_RESULT_PATH"] = str(result_path)
        proc = subprocess.run(
            [sys.executable, str(DISPATCH), json.dumps(payload, ensure_ascii=False)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        obj = contract.read_result(str(result_path))
        assert obj is not None, proc.stdout
        return obj


def test_descriptive_stats_quartiles_iqr():
    rows = [{"spend": v} for v in [12.0, 18.0, 19.0, 21.0, 30.0]]
    out = compute.descriptive_stats(rows, "spend")
    assert out["count"] == 5
    assert out["mean"] == 20.0
    assert out["median"] == 19.0
    assert out["q1"] == 18.0
    assert out["q3"] == 21.0
    assert out["iqr"] == 3.0


def test_correlation_positive_and_negative():
    pos = [{"x": 1, "y": 2}, {"x": 2, "y": 4}, {"x": 3, "y": 6}]
    neg = [{"x": 1, "y": 6}, {"x": 2, "y": 4}, {"x": 3, "y": 2}]
    assert math.isclose(compute.pearson_correlation(pos, "x", "y")["r"], 1.0)
    assert math.isclose(compute.pearson_correlation(neg, "x", "y")["r"], -1.0)


def test_linear_regression_exact_line():
    rows = [
        {"ad_spend": 1.0, "sales": 3.0},
        {"ad_spend": 2.0, "sales": 5.0},
        {"ad_spend": 3.0, "sales": 7.0},
        {"ad_spend": 4.0, "sales": 9.0},
    ]
    out = compute.linear_regression(rows, "ad_spend", "sales")
    assert math.isclose(out["slope"], 2.0)
    assert math.isclose(out["intercept"], 1.0)
    assert math.isclose(out["r_squared"], 1.0)


def test_two_proportion_z_standard_library_result():
    rows = [
        {"group": "control", "converted": 0},
        {"group": "control", "converted": 1},
        {"group": "control", "converted": 0},
        {"group": "control", "converted": 1},
        {"group": "treatment", "converted": 1},
        {"group": "treatment", "converted": 1},
        {"group": "treatment", "converted": 1},
        {"group": "treatment", "converted": 0},
    ]
    out = compute.two_proportion_z(rows, "group", "converted")
    assert math.isclose(out["groups"]["control"]["rate"], 0.5)
    assert math.isclose(out["groups"]["treatment"]["rate"], 0.75)
    assert math.isclose(out["difference"], 0.25)
    assert math.isclose(out["z_stat"], 0.7302967433402214)
    assert math.isclose(out["p_value"], 0.4652088184521418)


def test_group_aggregate_is_row_order_invariant():
    rows = [
        {"channel": "search", "revenue": 30.0},
        {"channel": "email", "revenue": 14.0},
        {"channel": "search", "revenue": 20.0},
        {"channel": "email", "revenue": 10.0},
    ]
    out = compute.group_aggregate(rows, "channel", "revenue", ["count", "mean"])
    assert out["groups"]["email"] == {"count": 2, "mean": 12.0}
    assert out["groups"]["search"] == {"count": 2, "mean": 25.0}


def test_dispatch_public_descriptive_scenario_with_irrelevant_column():
    out = _run_dispatch({
        "task_id": "open_stat_desc_001",
        "question": "Summarize the distribution of customer spend. Include mean, median, standard deviation, quartiles, and IQR.",
        "data": [
            {"customer_id": "c1", "spend": 12.0, "noise": "x"},
            {"customer_id": "c2", "spend": 18.0, "noise": "x"},
            {"customer_id": "c3", "spend": 19.0, "noise": "x"},
            {"customer_id": "c4", "spend": 21.0, "noise": "x"},
            {"customer_id": "c5", "spend": 30.0, "noise": "x"},
        ],
    })
    assert out["analysis_type"] == "descriptive_stats"
    assert out["columns"] == {"value": "spend"}
    assert out["decision"] == "computed"
    assert out["result"]["iqr"] == 3.0


def test_dispatch_descriptive_std_alias_does_not_confuse_numeric_rate():
    out = _run_dispatch({
        "task_id": "open_stat_desc_alias_001",
        "question": "Compute the average and std of monthly churn_rate.",
        "data": [
            {"month": "Jan", "churn_rate": 0.10},
            {"month": "Feb", "churn_rate": 0.14},
            {"month": "Mar", "churn_rate": 0.12},
        ],
    })
    assert out["analysis_type"] == "descriptive_stats"
    assert out["columns"] == {"value": "churn_rate"}
    assert out["decision"] == "computed"


def test_dispatch_descriptive_spread_synonyms():
    out = _run_dispatch({
        "task_id": "open_stat_desc_spread_001",
        "question": "Describe the spread and variability of response_time.",
        "data": [
            {"user": "a", "response_time": 120.0},
            {"user": "b", "response_time": 150.0},
            {"user": "c", "response_time": 180.0},
        ],
    })
    assert out["analysis_type"] == "descriptive_stats"
    assert out["columns"] == {"value": "response_time"}
    assert out["confidence"] >= 0.75


def test_dispatch_public_regression_scenario():
    out = _run_dispatch({
        "task_id": "open_stat_reg_001",
        "question": "Fit a simple linear regression predicting sales from ad_spend. Return slope, intercept, and R squared.",
        "data": [
            {"ad_spend": 1.0, "sales": 3.0},
            {"ad_spend": 2.0, "sales": 5.0},
            {"ad_spend": 3.0, "sales": 7.0},
            {"ad_spend": 4.0, "sales": 9.0},
        ],
    })
    assert out["analysis_type"] == "linear_regression"
    assert out["columns"] == {"predictor": "ad_spend", "response": "sales"}
    assert out["result"]["slope"] == 2.0
    assert out["result"]["intercept"] == 1.0


def test_dispatch_regression_r2_using_synonym():
    out = _run_dispatch({
        "task_id": "open_stat_reg_alias_001",
        "question": "Model revenue using ad_spend and return slope, intercept, and R^2.",
        "data": [
            {"ad_spend": 1.0, "revenue": 4.0},
            {"ad_spend": 2.0, "revenue": 7.0},
            {"ad_spend": 3.0, "revenue": 10.0},
            {"ad_spend": 4.0, "revenue": 13.0},
        ],
    })
    assert out["analysis_type"] == "linear_regression"
    assert out["columns"] == {"predictor": "ad_spend", "response": "revenue"}
    assert math.isclose(out["result"]["r_squared"], 1.0)


def test_dispatch_two_proportion_public_scenario():
    out = _run_dispatch({
        "task_id": "open_stat_ab_001",
        "question": "Compare the conversion rate between control and treatment. Is the treatment significantly different at alpha 0.05?",
        "data": [
            {"group": "control", "converted": 0},
            {"group": "control", "converted": 1},
            {"group": "control", "converted": 0},
            {"group": "control", "converted": 1},
            {"group": "treatment", "converted": 1},
            {"group": "treatment", "converted": 1},
            {"group": "treatment", "converted": 1},
            {"group": "treatment", "converted": 0},
        ],
    })
    assert out["analysis_type"] == "two_proportion_z"
    assert out["columns"] == {"group": "group", "outcome": "converted"}
    assert out["decision"] == "not_significant"


def test_dispatch_two_proportion_ctr_percent_alpha_with_string_outcome():
    out = _run_dispatch({
        "task_id": "open_stat_ab_alias_001",
        "question": "Compare CTR by experiment variant at 5% significance level.",
        "data": [
            {"variant": "control", "clicked": "yes"},
            {"variant": "control", "clicked": "no"},
            {"variant": "control", "clicked": "no"},
            {"variant": "treatment", "clicked": "yes"},
            {"variant": "treatment", "clicked": "yes"},
            {"variant": "treatment", "clicked": "no"},
        ],
    })
    assert out["analysis_type"] == "two_proportion_z"
    assert out["columns"] == {"group": "variant", "outcome": "clicked"}
    assert math.isclose(out["result"]["alpha"], 0.05)


def test_dispatch_public_group_aggregate_scenario():
    out = _run_dispatch({
        "task_id": "open_stat_group_001",
        "question": "For each sales channel, compute the mean revenue and the number of rows.",
        "data": [
            {"channel": "email", "revenue": 10.0},
            {"channel": "email", "revenue": 14.0},
            {"channel": "search", "revenue": 20.0},
            {"channel": "search", "revenue": 30.0},
        ],
    })
    assert out["analysis_type"] == "group_aggregate"
    assert out["columns"] == {"group": "channel", "value": "revenue"}
    assert out["result"]["aggregations"] == ["count", "mean"]
    assert out["result"]["groups"]["email"] == {"count": 2, "mean": 12.0}
    assert out["result"]["groups"]["search"] == {"count": 2, "mean": 25.0}


def test_dispatch_warns_and_drops_missing_selected_values():
    out = _run_dispatch({
        "task_id": "open_stat_missing_001",
        "question": "Summarize the distribution of customer spend. Include mean and median.",
        "data": [
            {"customer_id": "c1", "spend": 10.0},
            {"customer_id": "c2", "spend": None},
            {"customer_id": "c3"},
            {"customer_id": "c4", "spend": 20.0},
        ],
    })
    assert out["analysis_type"] == "descriptive_stats"
    assert out["result"]["count"] == 2
    assert out["result"]["mean"] == 15.0
    assert "dropped 2 row(s)" in " ".join(out["warnings"])


def test_dispatch_candidate_plan_for_low_confidence_question():
    out = _run_dispatch({
        "task_id": "open_stat_candidate_001",
        "question": "Can you inspect these two measurements?",
        "data": [
            {"a": 1.0, "b": 2.0},
            {"a": 2.0, "b": 4.0},
            {"a": 3.0, "b": 6.0},
        ],
        "candidate_plan": {
            "analysis_type": "correlation",
            "columns": {"x": "a", "y": "b"},
            "options": {},
        },
    })
    assert out["analysis_type"] == "correlation"
    assert out["columns"] == {"x": "a", "y": "b"}
    assert math.isclose(out["result"]["r"], 1.0)


def test_dispatch_candidate_plan_for_ambiguous_regression():
    out = _run_dispatch({
        "task_id": "open_stat_candidate_reg_001",
        "question": "Can you model the relationship in these measurements?",
        "data": [
            {"marketing": 1.0, "revenue": 5.0},
            {"marketing": 2.0, "revenue": 8.0},
            {"marketing": 3.0, "revenue": 11.0},
            {"marketing": 4.0, "revenue": 14.0},
        ],
        "candidate_plan": {
            "analysis_type": "linear_regression",
            "columns": {"predictor": "marketing", "response": "revenue"},
            "options": {},
        },
    })
    assert out["analysis_type"] == "linear_regression"
    assert out["columns"] == {"predictor": "marketing", "response": "revenue"}
    assert math.isclose(out["result"]["slope"], 3.0)
    assert math.isclose(out["result"]["intercept"], 2.0)


def test_dispatch_candidate_plan_for_ambiguous_group_aggregate():
    out = _run_dispatch({
        "task_id": "open_stat_candidate_group_001",
        "question": "Can you summarize this table by segment?",
        "data": [
            {"segment": "new", "amount": 10.0},
            {"segment": "new", "amount": 14.0},
            {"segment": "returning", "amount": 20.0},
            {"segment": "returning", "amount": 30.0},
        ],
        "candidate_plan": {
            "analysis_type": "group_aggregate",
            "columns": {"group": "segment", "value": "amount"},
            "options": {"aggregations": ["count", "mean"]},
        },
    })
    assert out["analysis_type"] == "group_aggregate"
    assert out["columns"] == {"group": "segment", "value": "amount"}
    assert out["result"]["groups"]["new"] == {"count": 2, "mean": 12.0}
    assert out["result"]["groups"]["returning"] == {"count": 2, "mean": 25.0}


def test_dispatch_invalid_candidate_plan_still_returns_contract():
    out = _run_dispatch({
        "task_id": "open_stat_invalid_plan",
        "question": "Can you inspect this?",
        "data": [{"a": 1.0}, {"a": 2.0}],
        "candidate_plan": {
            "analysis_type": "linear_regression",
            "columns": {"predictor": "missing", "response": "a"},
        },
    })
    assert out["task_id"] == "open_stat_invalid_plan"
    assert "candidate_plan ignored" in " ".join(out["warnings"])
    assert 0.0 <= out["confidence"] <= 1.0


def test_dispatch_rejects_candidate_plan_missing_required_role():
    out = _run_dispatch({
        "task_id": "open_stat_partial_plan",
        "question": "Can you inspect these two measurements?",
        "data": [
            {"a": 1.0, "b": 2.0},
            {"a": 2.0, "b": 4.0},
        ],
        "candidate_plan": {
            "analysis_type": "linear_regression",
            "columns": {"predictor": "a"},
        },
    })
    assert out["task_id"] == "open_stat_partial_plan"
    assert "candidate_plan ignored" in " ".join(out["warnings"])
    assert out["decision"] in {"computed", "needs_plan", "invalid_input"}
