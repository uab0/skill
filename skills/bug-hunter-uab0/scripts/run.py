#!/usr/bin/env python3
"""bug-hunter skill — file-based final output wrapper."""

from __future__ import annotations

import json
import os
import sys
import argparse


ALLOWED_VERDICTS = {"buggy", "clean"}
ALLOWED_TYPES = {
    "off_by_one", "null_deref", "type_error", "logic_error",
    "edge_case", "api_misuse", "inefficient", "unhandled_input",
}
ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def _clamp_confidence(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _sanitize_bug(b: dict) -> dict | None:
    if not isinstance(b, dict):
        return None
    try:
        ls = int(b.get("line_start"))
        le = int(b.get("line_end", ls))
    except (TypeError, ValueError):
        return None
    if ls < 1 or le < ls:
        return None
    sev = str(b.get("severity", "")).strip().lower()
    typ = str(b.get("type", "")).strip().lower()
    if sev not in ALLOWED_SEVERITIES or typ not in ALLOWED_TYPES:
        return None
    return {
        "line_start": ls,
        "line_end": le,
        "severity": sev,
        "type": typ,
        "description": str(b.get("description", "")),
        "suggested_fix": str(b.get("suggested_fix", "")),
    }


def emit_contract(obj: dict) -> int:
    verdict = str(obj.get("verdict", "")).strip().lower()
    if verdict not in ALLOWED_VERDICTS:
        verdict = "clean"

    raw_bugs = obj.get("bugs") or []
    if not isinstance(raw_bugs, list):
        raw_bugs = []
    bugs = [b for b in (_sanitize_bug(x) for x in raw_bugs) if b is not None]

    # 規格:verdict=clean 時 bugs[] 必須是 []。
    if verdict == "clean":
        bugs = []
    # 若有 bugs 卻 verdict=clean 已被擋;反之有 bug 但 verdict=buggy ok。
    if verdict == "buggy" and not bugs:
        # buggy 但沒列任何 bug 是 contract 違規,但我們不自動翻為 clean — 留給評分器扣分。
        pass

    out = {
        "task_id": str(obj.get("task_id", "")),
        "verdict": verdict,
        "bugs": bugs,
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
        return emit_contract({"task_id": "", "verdict": "clean", "bugs": [], "confidence": 0.0})
    if argv[1].startswith("--"):
        try:
            payload = _parse_flag_payload(argv[1:])
        except (SystemExit, ValueError):
            return emit_contract({"task_id": "", "verdict": "clean", "bugs": [], "confidence": 0.0})
        return emit_contract(payload)
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload not an object")
    except (json.JSONDecodeError, ValueError):
        return emit_contract({"task_id": "", "verdict": "clean", "bugs": [], "confidence": 0.0})
    return emit_contract(payload)


def _parse_flag_payload(args: list[str]) -> dict:
    parser = argparse.ArgumentParser(description="Write Bug Hunter result JSON.")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--confidence", default=0.5)
    parser.add_argument("--bugs", default="[]")
    ns = parser.parse_args(args)
    try:
        bugs = json.loads(ns.bugs)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid --bugs JSON: {e}") from e
    if not isinstance(bugs, list):
        raise ValueError("--bugs must be a JSON array")
    return {
        "task_id": ns.task_id,
        "verdict": ns.verdict,
        "bugs": bugs,
        "confidence": ns.confidence,
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv))
