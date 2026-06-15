#!/usr/bin/env python3
"""text2sql skill — file-based final output wrapper."""

from __future__ import annotations

import json
import os
import sys
import argparse


CONTRACT_FIELDS = ("task_id", "sql", "rationale", "confidence")


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def emit_contract(obj: dict) -> int:
    out = {
        "task_id": str(obj.get("task_id", "")),
        "sql": str(obj.get("sql", "")).strip(),
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


def _clamp_confidence(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        # 失敗也要產出契約 JSON,不可只噴錯(規格書 §1.4 #7)。
        return emit_contract({
            "task_id": "",
            "sql": "",
            "rationale": "run.py invoked without argv payload",
            "confidence": 0.0,
        })

    if argv[1].startswith("--"):
        try:
            payload = _parse_flag_payload(argv[1:])
        except (SystemExit, ValueError) as e:
            return emit_contract({
                "task_id": "",
                "sql": "",
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
            "task_id": "",
            "sql": "",
            "rationale": f"invalid argv JSON: {e}",
            "confidence": 0.0,
        })

    return emit_contract(payload)


def _parse_flag_payload(args: list[str]) -> dict:
    parser = argparse.ArgumentParser(description="Write Text2SQL result JSON.")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--sql", required=True)
    parser.add_argument("--rationale", default="")
    parser.add_argument("--confidence", default=0.5)
    ns = parser.parse_args(args)
    return {
        "task_id": ns.task_id,
        "sql": ns.sql,
        "rationale": ns.rationale,
        "confidence": ns.confidence,
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv))
