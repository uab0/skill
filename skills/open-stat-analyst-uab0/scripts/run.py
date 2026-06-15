#!/usr/bin/env python3
"""File-based final output wrapper for open-stat-analyst-uab0."""

from __future__ import annotations

import json
import math
import os
import sys
import argparse
from typing import Any


ALLOWED_TYPES = {
    "descriptive_stats",
    "correlation",
    "linear_regression",
    "two_proportion_z",
    "group_aggregate",
    "unknown",
}


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def emit_contract(obj: dict) -> int:
    warnings = obj.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    columns = obj.get("columns", {})
    if not isinstance(columns, dict):
        columns = {}
    result = obj.get("result", {})
    if not isinstance(result, dict):
        result = {}
    analysis_type = str(obj.get("analysis_type", "unknown"))
    if analysis_type not in ALLOWED_TYPES:
        analysis_type = "unknown"
    out = {
        "task_id": str(obj.get("task_id", "")),
        "analysis_type": analysis_type,
        "columns": {str(k): str(v) for k, v in columns.items()},
        "result": _sanitize_json(result),
        "decision": str(obj.get("decision", "invalid_input")),
        "warnings": [str(w) for w in warnings],
        "confidence": _clamp_confidence(obj.get("confidence", 0.0)),
    }
    path = resolve_result_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)
    print(f"written ok -> {path}")
    return 0


def _clamp_confidence(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f):
        return 0.0
    return max(0.0, min(1.0, f))


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1].startswith("--"):
        try:
            payload = _parse_flag_payload(argv[1:])
        except (SystemExit, ValueError) as e:
            return emit_contract({
                "task_id": "",
                "analysis_type": "unknown",
                "columns": {},
                "result": {},
                "decision": "invalid_input",
                "warnings": [f"invalid flag arguments: {e}"],
                "confidence": 0.0,
            })
        return emit_contract(payload)

    raw = argv[1] if len(argv) > 1 else sys.stdin.read()
    if not raw:
        return emit_contract({
            "task_id": "",
            "analysis_type": "unknown",
            "columns": {},
            "result": {},
            "decision": "invalid_input",
            "warnings": ["run.py invoked without payload"],
            "confidence": 0.0,
        })
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload not an object")
    except (json.JSONDecodeError, ValueError) as e:
        return emit_contract({
            "task_id": "",
            "analysis_type": "unknown",
            "columns": {},
            "result": {},
            "decision": "invalid_input",
            "warnings": [f"invalid payload JSON: {e}"],
            "confidence": 0.0,
        })
    return emit_contract(payload)


def _parse_flag_payload(args: list[str]) -> dict:
    parser = argparse.ArgumentParser(description="Write Open Track statistics result JSON.")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--analysis_type", required=True)
    parser.add_argument("--columns", default="{}")
    parser.add_argument("--result", default="{}")
    parser.add_argument("--decision", default="computed")
    parser.add_argument("--warnings", default="[]")
    parser.add_argument("--confidence", default=0.5)
    ns = parser.parse_args(args)
    columns = _json_arg(ns.columns, dict, "--columns")
    result = _json_arg(ns.result, dict, "--result")
    warnings = _json_arg(ns.warnings, list, "--warnings")
    return {
        "task_id": ns.task_id,
        "analysis_type": ns.analysis_type,
        "columns": columns,
        "result": result,
        "decision": ns.decision,
        "warnings": warnings,
        "confidence": ns.confidence,
    }


def _json_arg(raw: str, expected_type: type, name: str) -> Any:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid {name} JSON: {e}") from e
    if not isinstance(obj, expected_type):
        raise ValueError(f"{name} must be a JSON {expected_type.__name__}")
    return obj


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
