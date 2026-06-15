#!/usr/bin/env python3
"""Dispatcher for open-stat-analyst-uab0."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import compute  # noqa: E402


RUN_PY = SCRIPT_DIR / "run.py"
SUPPORTED = {"descriptive_stats", "correlation", "linear_regression", "two_proportion_z", "group_aggregate"}


def main(argv: list[str]) -> int:
    try:
        payload = _read_payload(argv)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        return _emit({
            "task_id": "",
            "analysis_type": "unknown",
            "columns": {},
            "result": {},
            "decision": "invalid_input",
            "warnings": [f"invalid input: {e}"],
            "confidence": 0.0,
        })

    original = payload.get("original")
    if isinstance(original, dict):
        merged = dict(original)
        if "candidate_plan" in payload:
            merged["candidate_plan"] = payload["candidate_plan"]
        payload = merged

    task_id = str(payload.get("task_id", ""))
    question = str(payload.get("question", ""))
    data = payload.get("data", [])
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        return _emit(_invalid(task_id, "data must be a list of row objects"))
    if not data:
        return _emit(_invalid(task_id, "data must contain at least one row"))

    warnings: list[str] = []
    plan, confidence = _plan_from_payload(payload, question, data, warnings)
    analysis_type = str(plan.get("analysis_type", "unknown"))
    columns = plan.get("columns", {})
    options = plan.get("options", {})
    if not isinstance(columns, dict):
        columns = {}
    if not isinstance(options, dict):
        options = {}

    if plan.get("unsupported"):
        return _emit({
            "task_id": task_id,
            "analysis_type": "unknown",
            "columns": columns,
            "result": {},
            "decision": "invalid_input",
            "warnings": warnings + [str(plan.get("unsupported_reason", "unsupported statistical method requested"))],
            "confidence": min(confidence, 0.35),
        })

    if analysis_type not in SUPPORTED:
        return _emit({
            "task_id": task_id,
            "analysis_type": "unknown",
            "columns": columns,
            "result": {},
            "decision": "needs_plan",
            "warnings": warnings + ["could not infer a supported analysis_type"],
            "confidence": 0.35,
        })

    _append_missing_value_warning(warnings, data, columns)

    try:
        result, normalized_columns, decision = _compute_result(analysis_type, columns, options, data)
    except compute.StatError as e:
        return _emit({
            "task_id": task_id,
            "analysis_type": analysis_type,
            "columns": columns,
            "result": {},
            "decision": "invalid_input",
            "warnings": warnings + [str(e)],
            "confidence": min(confidence, 0.45),
        })

    return _emit({
        "task_id": task_id,
        "analysis_type": analysis_type,
        "columns": normalized_columns,
        "result": result,
        "decision": decision,
        "warnings": warnings,
        "confidence": confidence,
    })


def _read_payload(argv: list[str]) -> dict:
    raw = argv[1] if len(argv) > 1 else sys.stdin.read()
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return payload


def _emit(obj: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(RUN_PY), json.dumps(obj, ensure_ascii=False)],
        text=True,
        capture_output=True,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def _invalid(task_id: str, warning: str) -> dict:
    return {
        "task_id": task_id,
        "analysis_type": "unknown",
        "columns": {},
        "result": {},
        "decision": "invalid_input",
        "warnings": [warning],
        "confidence": 0.0,
    }


def _plan_from_payload(payload: dict, question: str, data: list[dict], warnings: list[str]) -> tuple[dict, float]:
    candidate = payload.get("candidate_plan")
    if isinstance(candidate, dict):
        plan = _normalize_candidate(candidate)
        if _plan_columns_exist(plan, data):
            return plan, 0.78
        warnings.append("candidate_plan ignored because it referenced missing or invalid columns")
    plan = _infer_plan(question, data)
    return plan, float(plan.pop("_confidence", 0.65))


def _normalize_candidate(candidate: dict) -> dict:
    analysis_type = str(candidate.get("analysis_type", "")).strip()
    columns = candidate.get("columns", {})
    options = candidate.get("options", {})
    return {
        "analysis_type": analysis_type,
        "columns": columns if isinstance(columns, dict) else {},
        "options": options if isinstance(options, dict) else {},
    }


def _plan_columns_exist(plan: dict, data: list[dict]) -> bool:
    columns = plan.get("columns", {})
    if plan.get("analysis_type") not in SUPPORTED or not isinstance(columns, dict):
        return False
    required_roles = {
        "descriptive_stats": ("value",),
        "correlation": ("x", "y"),
        "linear_regression": ("predictor", "response"),
        "two_proportion_z": ("group", "outcome"),
        "group_aggregate": ("group", "value"),
    }
    roles = required_roles.get(str(plan.get("analysis_type")), ())
    if any(not str(columns.get(role, "")).strip() for role in roles):
        return False
    available = set().union(*(row.keys() for row in data))
    return all(str(columns[role]) in available for role in roles)


def _append_missing_value_warning(warnings: list[str], data: list[dict], columns: dict) -> None:
    selected = [str(col) for col in columns.values() if str(col).strip()]
    if not selected:
        return
    dropped = 0
    for row in data:
        if any(col not in row or row[col] is None for col in selected):
            dropped += 1
    if dropped:
        warnings.append(
            f"dropped {dropped} row(s) with missing values in selected columns: {', '.join(selected)}"
        )


def _infer_plan(question: str, data: list[dict]) -> dict:
    q = question.lower()
    numeric = _numeric_columns(data)
    binary = _binary_columns(data)
    categorical = _categorical_columns(data)

    unsupported = _unsupported_analysis_reason(q)
    if unsupported:
        return {
            "analysis_type": "unknown",
            "columns": {},
            "options": {},
            "unsupported": True,
            "unsupported_reason": unsupported,
            "_confidence": 0.30,
        }

    two_prop_cue = _has_any(q, (
        "conversion", "converted", "success rate", "click-through rate", "click through rate",
        "ctr", "a/b", "ab test", "treatment", "control",
        "lift", "response rate", "signup rate", "purchase rate",
    )) or ("rate" in q and categorical and binary)
    if two_prop_cue:
        return {
            "analysis_type": "two_proportion_z",
            "columns": {
                "group": _best_column(q, categorical, ("group", "variant", "arm", "bucket", "segment", "cohort", "experiment")),
                "outcome": _best_column(q, binary, ("converted", "conversion", "success", "clicked", "click", "purchased", "responded", "subscribed", "outcome")),
            },
            "options": {"alpha": _extract_alpha(q)},
            "_confidence": 0.88,
        }
    if _has_any(q, (
        "linear regression", "regression", "fit", "model", "predict", "explain", "slope", "intercept",
        "r squared", "r-squared", "r^2", "r2", "coefficient of determination",
    )):
        x_col, y_col = _infer_xy(q, numeric, prefer_regression=True)
        return {
            "analysis_type": "linear_regression",
            "columns": {"predictor": x_col, "response": y_col},
            "options": {},
            "_confidence": 0.86,
        }
    if _has_any(q, (
        "correlation", "pearson", "relationship", "association", "correlate",
        "linear association", "linear relationship", "move together", "co-move",
    )):
        x_col, y_col = _infer_xy(q, numeric, prefer_regression=False)
        return {
            "analysis_type": "correlation",
            "columns": {"x": x_col, "y": y_col},
            "options": {},
            "_confidence": 0.84,
        }
    if _has_any(q, (
        "for each", "by ", "group", "per ", "aggregate", "channel",
        "break down", "breakdown", "split by", "within each", "across each",
    )) and categorical and numeric:
        return {
            "analysis_type": "group_aggregate",
            "columns": {
                "group": _best_column(q, categorical, ("group", "channel", "segment", "category", "cohort", "variant", "bucket")),
                "value": _best_column(q, numeric, ("revenue", "sales", "spend", "amount", "value", "metric", "score")),
            },
            "options": {"aggregations": _infer_aggs(q)},
            "_confidence": 0.83,
        }
    if numeric:
        return {
            "analysis_type": "descriptive_stats",
            "columns": {"value": _best_column(q, numeric, ("spend", "revenue", "sales", "value", "amount", "score"))},
            "options": {},
            "_confidence": 0.78 if _has_any(q, (
                "summarize", "summary", "distribution", "mean", "average", "median",
                "iqr", "quartile", "stdev", "std", "sd", "standard deviation",
                "spread", "variability", "dispersion", "range",
            )) else 0.58,
        }
    return {"analysis_type": "unknown", "columns": {}, "options": {}, "_confidence": 0.25}


def _compute_result(analysis_type: str, columns: dict, options: dict, data: list[dict]) -> tuple[dict, dict, str]:
    if analysis_type == "descriptive_stats":
        value = _required_col(columns, "value")
        return compute.descriptive_stats(data, value), {"value": value}, "computed"
    if analysis_type == "correlation":
        x_col = _required_col(columns, "x")
        y_col = _required_col(columns, "y")
        result = compute.pearson_correlation(data, x_col, y_col)
        r = float(result["r"])
        decision = "positive_association" if r > 0 else ("negative_association" if r < 0 else "no_linear_association")
        return result, {"x": x_col, "y": y_col}, decision
    if analysis_type == "linear_regression":
        predictor = _required_col(columns, "predictor")
        response = _required_col(columns, "response")
        return compute.linear_regression(data, predictor, response), {"predictor": predictor, "response": response}, "computed"
    if analysis_type == "two_proportion_z":
        group = _required_col(columns, "group")
        outcome = _required_col(columns, "outcome")
        alpha = float(options.get("alpha", 0.05))
        result = compute.two_proportion_z(data, group, outcome, alpha=alpha)
        decision = "significant" if float(result["p_value"]) < alpha else "not_significant"
        return result, {"group": group, "outcome": outcome}, decision
    if analysis_type == "group_aggregate":
        group = _required_col(columns, "group")
        value = _required_col(columns, "value")
        aggs = options.get("aggregations", ["count", "mean"])
        if isinstance(aggs, str):
            aggs = [aggs]
        if not isinstance(aggs, list):
            aggs = ["count", "mean"]
        return compute.group_aggregate(data, group, value, [str(a) for a in aggs]), {"group": group, "value": value}, "computed"
    raise compute.StatError(f"unsupported analysis_type: {analysis_type}")


def _required_col(columns: dict, key: str) -> str:
    col = str(columns.get(key, "")).strip()
    if not col:
        raise compute.StatError(f"missing required column role: {key}")
    return col


def _numeric_columns(data: list[dict]) -> list[str]:
    cols = sorted(set().union(*(row.keys() for row in data)))
    out: list[str] = []
    for col in cols:
        vals = [row[col] for row in data if col in row and row[col] is not None]
        if vals and all(compute.is_number(v) for v in vals):
            out.append(str(col))
    return out


def _binary_columns(data: list[dict]) -> list[str]:
    cols = sorted(set().union(*(row.keys() for row in data)))
    out: list[str] = []
    for col in cols:
        vals = [row[col] for row in data if col in row and row[col] is not None]
        if not vals:
            continue
        try:
            coerced = {compute.to_binary(v) for v in vals}
        except compute.StatError:
            continue
        if coerced <= {0, 1} and len(coerced) <= 2:
            out.append(str(col))
    return out


def _categorical_columns(data: list[dict]) -> list[str]:
    cols = sorted(set().union(*(row.keys() for row in data)))
    numeric = set(_numeric_columns(data))
    out: list[str] = []
    for col in cols:
        if str(col) in numeric:
            continue
        vals = [row[col] for row in data if col in row and row[col] is not None]
        if vals and len({str(v) for v in vals}) <= max(20, len(vals)):
            out.append(str(col))
    return out


def _best_column(question: str, candidates: list[str], preferred: tuple[str, ...]) -> str:
    if not candidates:
        return ""
    scored: list[tuple[int, str]] = []
    q_tokens = set(_tokens(question))
    for col in candidates:
        col_tokens = set(_tokens(col))
        score = len(q_tokens & col_tokens) * 5
        low = col.lower()
        for idx, word in enumerate(preferred):
            if word in low:
                score += max(1, 10 - idx)
            if word in question:
                score += 1
        if low in question:
            score += 8
        scored.append((score, col))
    return sorted(scored, key=lambda x: (-x[0], x[1]))[0][1]


def _infer_xy(question: str, numeric: list[str], *, prefer_regression: bool) -> tuple[str, str]:
    if len(numeric) < 2:
        return (_best_column(question, numeric, ()), "")
    q = question.lower()
    predictor = ""
    response = ""
    for col in numeric:
        low = col.lower()
        if re.search(rf"\bfrom\s+{re.escape(low)}\b", q):
            predictor = col
        if re.search(rf"\busing\s+{re.escape(low)}\b", q):
            predictor = col
        if re.search(rf"\bbased\s+on\s+{re.escape(low)}\b", q):
            predictor = col
        if re.search(rf"\bas\s+a\s+function\s+of\s+{re.escape(low)}\b", q):
            predictor = col
        if re.search(rf"\beffect\s+of\s+{re.escape(low)}\b", q):
            predictor = col
        if re.search(rf"\b(?:predicting|predict|predicts)\s+{re.escape(low)}\b", q):
            response = col
        if re.search(rf"\b{re.escape(low)}\s+as\s+a\s+function\s+of\b", q):
            response = col
        if re.search(rf"\bon\s+{re.escape(low)}\b", q):
            response = col
    if not predictor and prefer_regression:
        predictor = _best_column(q, numeric, ("ad_spend", "spend", "x", "input", "predictor"))
    if not response and prefer_regression:
        response = _best_column(q, [c for c in numeric if c != predictor], ("sales", "revenue", "y", "output", "response"))
    if not predictor:
        predictor = _best_column(q, numeric, ("x", "ad_spend", "spend"))
    if not response:
        response = _best_column(q, [c for c in numeric if c != predictor], ("y", "sales", "revenue"))
    if predictor == response:
        rest = [c for c in numeric if c != predictor]
        response = rest[0] if rest else ""
    return predictor, response


def _infer_aggs(question: str) -> list[str]:
    aggs: list[str] = []
    for name in ("count", "sum", "mean", "median", "min", "max"):
        if name in question or (name == "mean" and ("average" in question or "avg" in question)):
            aggs.append(name)
    count_phrases = (
        "number of rows",
        "row count",
        "rows",
        "number of records",
        "record count",
        "records",
        "observations",
        "sample size",
    )
    if any(phrase in question for phrase in count_phrases) or re.search(r"\bn\b", question):
        if "count" not in aggs:
            aggs.insert(0, "count")
    return aggs or ["count", "mean"]


def _extract_alpha(question: str) -> float:
    match = re.search(r"alpha\s*(?:=|is|at)?\s*([0-9]*\.?[0-9]+)\s*(%)?", question)
    if match:
        try:
            alpha = float(match.group(1))
            if match.group(2) == "%":
                alpha /= 100.0
            if 0.0 < alpha < 1.0:
                return alpha
        except ValueError:
            pass
    match = re.search(r"([0-9]*\.?[0-9]+)\s*%\s*(?:significance|alpha|level)", question)
    if match:
        try:
            alpha = float(match.group(1)) / 100.0
            if 0.0 < alpha < 1.0:
                return alpha
        except ValueError:
            pass
    match = re.search(r"(?:significance|alpha)\s+level\s+(?:of|at)?\s*([0-9]*\.?[0-9]+)\s*%", question)
    if match:
        try:
            alpha = float(match.group(1)) / 100.0
            if 0.0 < alpha < 1.0:
                return alpha
        except ValueError:
            pass
    return 0.05


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _unsupported_analysis_reason(question: str) -> str:
    unsupported = (
        ("t-test", "t test", "ttest", "student's t", "student t"),
        ("chi-square", "chi square", "chisquare", "χ²", "chi-squared"),
        ("logistic regression", "logit"),
        ("anova", "analysis of variance"),
    )
    for aliases in unsupported:
        if _has_any(question, aliases):
            return (
                "unsupported statistical method requested: "
                f"{aliases[0]}; supported methods are descriptive_stats, correlation, "
                "linear_regression, two_proportion_z, and group_aggregate"
            )
    return ""


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
