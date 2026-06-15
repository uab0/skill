#!/usr/bin/env python3
"""Deterministic evaluator for open-stat-analyst-uab0 result files."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import compute  # noqa: E402


SUPPORTED = {"descriptive_stats", "correlation", "linear_regression", "two_proportion_z", "group_aggregate"}
DEFAULT_TOLERANCE = 1e-6


def evaluate(scenario: dict, result: dict, expected: dict | None = None, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not isinstance(scenario, dict):
        return _summary(False, [{"name": "scenario_object", "passed": False, "detail": "scenario is not an object"}])
    if not isinstance(result, dict):
        return _summary(False, [{"name": "result_object", "passed": False, "detail": "result is not an object"}])

    task_id = str(scenario.get("task_id", ""))
    check("task_id", str(result.get("task_id", "")) == task_id, f"expected {task_id!r}")

    data = scenario.get("data", [])
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        check("input_data", False, "scenario.data must be a list of row objects")
        return _summary(all(c["passed"] for c in checks), checks)

    unsupported = _unsupported_analysis_reason(str(scenario.get("question", "")).lower())
    if unsupported:
        _evaluate_unsupported(result, unsupported, checks, check)
        return _summary(all(c["passed"] for c in checks), checks)

    if expected is not None:
        _evaluate_expected_subset(result, expected, tolerance, check)

    analysis_type = str(result.get("analysis_type", "unknown"))
    columns = result.get("columns", {})
    if analysis_type not in SUPPORTED:
        check("analysis_type_supported", False, f"unsupported or unknown analysis_type: {analysis_type}")
        return _summary(all(c["passed"] for c in checks), checks)
    if not isinstance(columns, dict):
        check("columns_object", False, "columns must be an object")
        return _summary(all(c["passed"] for c in checks), checks)

    try:
        expected_result, expected_columns, expected_decision = _recompute(analysis_type, columns, result, data)
    except compute.StatError as e:
        check("recompute", False, str(e))
        return _summary(all(c["passed"] for c in checks), checks)

    check("columns", _same_json_subset(expected_columns, columns, tolerance), f"expected roles {expected_columns!r}")
    check("result", _same_json(expected_result, result.get("result", {}), tolerance), "numeric result differs from recomputed ground truth")
    check("decision", str(result.get("decision", "")) == expected_decision, f"expected {expected_decision!r}")

    dropped = _dropped_selected_rows(data, expected_columns)
    if dropped:
        warning_text = " ".join(str(w) for w in result.get("warnings", []))
        check("missing_value_warning", f"dropped {dropped} row" in warning_text, f"expected warning for {dropped} dropped row(s)")

    return _summary(all(c["passed"] for c in checks), checks)


def _summary(passed: bool, checks: list[dict[str, Any]]) -> dict:
    return {"passed": bool(passed), "checks": checks}


def _evaluate_unsupported(result: dict, unsupported: str, checks: list[dict[str, Any]], check) -> None:
    warning_text = " ".join(str(w) for w in result.get("warnings", [])).lower()
    check("unsupported_analysis_type", str(result.get("analysis_type", "")) == "unknown", "unsupported tasks should not pick a supported type")
    check("unsupported_decision", str(result.get("decision", "")) in {"invalid_input", "needs_plan"}, "expected invalid_input or needs_plan")
    check("unsupported_empty_result", result.get("result", None) == {}, "unsupported tasks must not fabricate numeric output")
    check("unsupported_warning", "unsupported" in warning_text or unsupported in warning_text, "warning should explain unsupported method")


def _evaluate_expected_subset(result: dict, expected: dict, tolerance: float, check) -> None:
    if not isinstance(expected, dict):
        check("expected_object", False, "expected must be an object")
        return
    for key in ("analysis_type", "decision"):
        if key in expected:
            check(f"expected_{key}", result.get(key) == expected[key], f"expected {key}={expected[key]!r}")
    for key in ("columns", "result"):
        if key in expected:
            check(f"expected_{key}", _same_json_subset(expected[key], result.get(key), tolerance), f"expected {key} subset differs")
    if "warnings_contains" in expected:
        warning_text = " ".join(str(w) for w in result.get("warnings", [])).lower()
        needles = expected["warnings_contains"]
        if isinstance(needles, str):
            needles = [needles]
        ok = isinstance(needles, list) and all(str(n).lower() in warning_text for n in needles)
        check("expected_warnings_contains", ok, f"expected warning text to contain {needles!r}")
    confidence = result.get("confidence")
    if "confidence_min" in expected:
        check("expected_confidence_min", _to_float(confidence) >= float(expected["confidence_min"]), "confidence is too low")
    if "confidence_max" in expected:
        check("expected_confidence_max", _to_float(confidence) <= float(expected["confidence_max"]), "confidence is too high")


def _recompute(analysis_type: str, columns: dict, result: dict, rows: list[dict]) -> tuple[dict, dict, str]:
    if analysis_type == "descriptive_stats":
        value = _required_col(columns, "value")
        return compute.descriptive_stats(rows, value), {"value": value}, "computed"
    if analysis_type == "correlation":
        x_col = _required_col(columns, "x")
        y_col = _required_col(columns, "y")
        out = compute.pearson_correlation(rows, x_col, y_col)
        r = float(out["r"])
        decision = "positive_association" if r > 0 else ("negative_association" if r < 0 else "no_linear_association")
        return out, {"x": x_col, "y": y_col}, decision
    if analysis_type == "linear_regression":
        predictor = _required_col(columns, "predictor")
        response = _required_col(columns, "response")
        return compute.linear_regression(rows, predictor, response), {"predictor": predictor, "response": response}, "computed"
    if analysis_type == "two_proportion_z":
        group = _required_col(columns, "group")
        outcome = _required_col(columns, "outcome")
        alpha = _result_alpha(result)
        out = compute.two_proportion_z(rows, group, outcome, alpha=alpha)
        decision = "significant" if float(out["p_value"]) < alpha else "not_significant"
        return out, {"group": group, "outcome": outcome}, decision
    if analysis_type == "group_aggregate":
        group = _required_col(columns, "group")
        value = _required_col(columns, "value")
        aggs = _result_aggs(result)
        return compute.group_aggregate(rows, group, value, aggs), {"group": group, "value": value}, "computed"
    raise compute.StatError(f"unsupported analysis_type: {analysis_type}")


def _required_col(columns: dict, key: str) -> str:
    col = str(columns.get(key, "")).strip()
    if not col:
        raise compute.StatError(f"missing required column role: {key}")
    return col


def _result_alpha(result: dict) -> float:
    payload = result.get("result", {})
    if isinstance(payload, dict):
        try:
            alpha = float(payload.get("alpha", 0.05))
            if 0.0 < alpha < 1.0:
                return alpha
        except (TypeError, ValueError):
            pass
    return 0.05


def _result_aggs(result: dict) -> list[str]:
    payload = result.get("result", {})
    if isinstance(payload, dict):
        aggs = payload.get("aggregations", ["count", "mean"])
        if isinstance(aggs, str):
            return [aggs]
        if isinstance(aggs, list):
            return [str(a) for a in aggs]
    return ["count", "mean"]


def _dropped_selected_rows(rows: list[dict], columns: dict) -> int:
    selected = [str(col) for col in columns.values() if str(col).strip()]
    return sum(1 for row in rows if any(col not in row or row[col] is None for col in selected))


def _same_json(expected: Any, actual: Any, tolerance: float) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(expected) == set(actual) and all(
            _same_json(expected[key], actual[key], tolerance) for key in expected
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _same_json(e, a, tolerance) for e, a in zip(expected, actual)
        )
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isclose(
            float(expected), float(actual), abs_tol=tolerance, rel_tol=0.0
        )
    return expected == actual


def _same_json_subset(expected: Any, actual: Any, tolerance: float) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _same_json_subset(value, actual[key], tolerance) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return _same_json(expected, actual, tolerance)
    return _same_json(expected, actual, tolerance)


def _unsupported_analysis_reason(question: str) -> str:
    unsupported = (
        ("t-test", "t test", "ttest", "student's t", "student t"),
        ("chi-square", "chi square", "chisquare", "χ²", "chi-squared"),
        ("logistic regression", "logit"),
        ("anova", "analysis of variance"),
    )
    for aliases in unsupported:
        if any(alias in question for alias in aliases):
            return aliases[0]
    return ""


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an open-stat-analyst-uab0 result JSON.")
    parser.add_argument("--input", required=True, help="Scenario JSON path.")
    parser.add_argument("--result", required=True, help="Skill result JSON path.")
    parser.add_argument("--expected", help="Optional expected subset JSON path.")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)

    scenario = _read_json(args.input)
    result = _read_json(args.result)
    expected = _read_json(args.expected) if args.expected else None
    report = evaluate(scenario, result, expected, args.tolerance)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
