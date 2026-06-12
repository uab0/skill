#!/usr/bin/env python3
"""
code-author skill — final output wrapper.

Reads JSON from argv[1] with the fields needed by the contract, validates shape,
emits a single fenced JSON block.
"""

from __future__ import annotations

import json
import sys


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
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
    sys.stdout.write("\n```\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return emit_contract({
            "task_id": "", "code": "", "loc": 0,
            "self_test_results": {"passed": 0, "failed": 0},
            "rationale": "run.py invoked without argv payload",
            "confidence": 0.0,
        })
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
