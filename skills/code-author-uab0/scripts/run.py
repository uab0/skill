#!/usr/bin/env python3
"""code-author skill — file-based final output wrapper."""

from __future__ import annotations

import json
import os
import sys
import argparse


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def _clamp_confidence(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def emit_contract(obj: dict) -> int:
    self_test = obj.get("self_test_results") or {}
    if not isinstance(self_test, dict):
        self_test = {"passed": 0, "failed": 0, "_warning": "non-object coerced"}
    self_test.setdefault("passed", 0)
    self_test.setdefault("failed", 0)

    out = {
        "task_id": str(obj.get("task_id", "")),
        "code": str(obj.get("code", "")),
        "loc": int(obj.get("loc", 0)) if str(obj.get("loc", "0")).lstrip("-").isdigit() else 0,
        "self_test_results": self_test,
        "rationale": str(obj.get("rationale", "")),
        "confidence": _clamp_confidence(obj.get("confidence", 0.5)),
    }
    path = resolve_result_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, path)
    print(f"written ok -> {path}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return emit_contract({
            "task_id": "", "code": "", "loc": 0,
            "self_test_results": {"passed": 0, "failed": 0},
            "rationale": "run.py invoked without argv payload",
            "confidence": 0.0,
        })
    if argv[1].startswith("--"):
        try:
            payload = _parse_flag_payload(argv[1:])
        except (SystemExit, ValueError) as e:
            return emit_contract({
                "task_id": "", "code": "", "loc": 0,
                "self_test_results": {"passed": 0, "failed": 0},
                "rationale": f"invalid flag arguments: {e}",
                "confidence": 0.0,
            })
        return emit_contract(payload)
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload not an object")
    except (json.JSONDecodeError, ValueError) as e:
        return emit_contract({
            "task_id": "", "code": "", "loc": 0,
            "self_test_results": {"passed": 0, "failed": 0},
            "rationale": f"invalid argv JSON: {e}",
            "confidence": 0.0,
        })
    return emit_contract(payload)


def _parse_flag_payload(args: list[str]) -> dict:
    parser = argparse.ArgumentParser(description="Write Code Author result JSON.")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--loc", default=0)
    parser.add_argument("--self_test_passed", default=0)
    parser.add_argument("--self_test_failed", default=0)
    parser.add_argument("--self_test_results", default="")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--confidence", default=0.5)
    ns = parser.parse_args(args)
    if ns.self_test_results:
        try:
            self_test = json.loads(ns.self_test_results)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid --self_test_results JSON: {e}") from e
        if not isinstance(self_test, dict):
            raise ValueError("--self_test_results must be a JSON object")
    else:
        self_test = {
            "passed": _int_or_zero(ns.self_test_passed),
            "failed": _int_or_zero(ns.self_test_failed),
        }
    return {
        "task_id": ns.task_id,
        "code": ns.code,
        "loc": ns.loc,
        "self_test_results": self_test,
        "rationale": ns.rationale,
        "confidence": ns.confidence,
    }


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
