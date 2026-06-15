#!/usr/bin/env python3
"""Deterministic first-pass author for common Pairwise small-function tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from selftest import compute_sloc, generated_samples, run_sample, structural_violations  # noqa: E402


def _emit(obj: dict) -> int:
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.stdout.write("\n```\n")
    return 0


def _template(entry: str, description: str) -> tuple[str, str, float]:
    text = f"{entry} {description}".lower()
    if "merge_intervals" in text or "interval" in text:
        return f"""def {entry}(intervals):
    if not intervals:
        return []
    items = sorted(intervals, key=lambda x: x[0])
    merged = [list(items[0])]
    for cur in items[1:]:
        if cur[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], cur[1])
        else:
            merged.append(list(cur))
    return merged
""", "Sort intervals and sweep, merging overlapping or touching intervals; handle empty input first.", 0.9
    if "binary_search" in text or "binary search" in text:
        return f"""def {entry}(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""", "Use inclusive low/high bounds so singleton and endpoint targets are checked.", 0.9
    if "parse_csv_line" in text or "csv" in text:
        return f"""def {entry}(line):
    fields = []
    cur = []
    in_quotes = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_quotes:
            if c == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    cur.append('"')
                    i += 2
                    continue
                in_quotes = False
            else:
                cur.append(c)
        else:
            if c == '"':
                in_quotes = True
            elif c == ",":
                fields.append("".join(cur))
                cur = []
            else:
                cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields
""", "Parse CSV with quote state and doubled-quote escaping; preserve empty fields.", 0.85
    if "unique_paths" in text or "grid" in text:
        return f"""def {entry}(m, n):
    if m <= 0 or n <= 0:
        return 0
    steps = m + n - 2
    choose = min(m - 1, n - 1)
    result = 1
    for i in range(1, choose + 1):
        result = result * (steps - choose + i) // i
    return result
""", "Use the binomial coefficient C(m+n-2, m-1), avoiding large DP tables.", 0.9
    if "kth_smallest" in text or "k-th smallest" in text or "kth smallest" in text:
        return f"""def {entry}(nums, k):
    if not nums or k < 1 or k > len(nums):
        return None
    return sorted(nums)[k - 1]
""", "Validate 1-based k and use sorted list so duplicates count.", 0.9
    return f"""def {entry}(*args, **kwargs):
    return None
""", "Unknown task family; emitted a safe stub rather than unsafe guessed code.", 0.1


def _self_test(code: str, task_description: str, constraints: dict) -> dict:
    entry = str(constraints.get("entry_function", ""))
    samples = generated_samples(task_description, entry)
    passed = 0
    failed = 0
    errors: list[str] = []
    for sample in samples:
        ok, err = run_sample(code, entry, sample)
        if ok:
            passed += 1
        else:
            failed += 1
            label = sample.get("label", "")
            errors.append(f"{label}: {err}" if label else err)
    forbidden = constraints.get("imports_forbidden", []) or []
    security = structural_violations(code, entry, forbidden)
    return {
        "passed": passed,
        "failed": failed + len(security),
        "errors": (errors + security)[:20],
        "loc_violation": compute_sloc(code) > int(constraints.get("max_loc", 500)),
        "import_violations": [x for x in security if x.startswith("forbidden import:")],
        "security_violations": security,
        "generated_samples": len(samples),
    }


def main(argv: list[str]) -> int:
    raw = argv[1] if len(argv) > 1 else "{}"
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        return _emit({
            "task_id": "",
            "code": "",
            "loc": 0,
            "self_test_results": {"passed": 0, "failed": 1, "errors": [f"invalid argv JSON: {e}"]},
            "rationale": "author.py could not parse input",
            "confidence": 0.0,
        })

    constraints = payload.get("constraints", {}) or {}
    if not isinstance(constraints, dict):
        constraints = {}
    entry = str(constraints.get("entry_function", "solution"))
    desc = str(payload.get("task_description", ""))
    code, rationale, confidence = _template(entry, desc)
    self_test = _self_test(code, desc, constraints)
    if self_test["failed"]:
        confidence = min(confidence, 0.4)

    return _emit({
        "task_id": str(payload.get("task_id", "")),
        "code": code,
        "loc": compute_sloc(code),
        "self_test_results": self_test,
        "rationale": rationale,
        "confidence": confidence,
    })


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
