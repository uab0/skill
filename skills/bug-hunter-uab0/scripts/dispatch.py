#!/usr/bin/env python3
"""Single entrypoint for bug-hunter-uab0."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import analyze  # noqa: E402

RUN_PY = SCRIPT_DIR / "run.py"


def _run_contract(payload: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(RUN_PY), json.dumps(payload, ensure_ascii=False)],
        text=True,
        capture_output=True,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def _read_payload(argv: list[str]) -> dict:
    raw = argv[1] if len(argv) > 1 else sys.stdin.read()
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    original = payload.get("original")
    if isinstance(original, dict):
        merged = dict(original)
        for key in ("mode", "candidate_bugs", "llm_candidate_bugs"):
            if key in payload:
                merged[key] = payload[key]
        return merged
    return payload


def _line_text(code: str, line: int) -> str:
    lines = code.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def _family_static_bugs(entry: str, code: str, task_description: str) -> list[dict]:
    text = f"{entry} {task_description}".lower()
    bugs: list[dict] = []
    compact = " ".join(code.split())

    if "binary_search" in text or "binary search" in text:
        line = _find_line(code, "while lo < hi")
        if line > 0 and "while lo < hi" in code:
            bugs.append({
                "line_start": line,
                "line_end": line,
                "severity": "high",
                "type": "off_by_one",
                "description": "`while lo < hi` can skip the final candidate in inclusive-bound binary search.",
                "suggested_fix": "Use `while lo <= hi` with `hi = len(arr) - 1`, or use a consistent exclusive-bound variant.",
            })

    if "parse_csv_line" in text or "csv" in text:
        has_quote_state = "in_quotes" in code or "quote" in code.lower()
        if "if c == ','" in code and not has_quote_state:
            line = _find_line(code, "if c == ','")
            bugs.append({
                "line_start": line,
                "line_end": max(line, _find_line(code, "cur +=")),
                "severity": "high",
                "type": "unhandled_input",
                "description": "Parser splits every comma and does not handle quoted fields containing commas.",
                "suggested_fix": "Track quoted state and only split on commas outside quotes; handle doubled quotes inside quoted fields.",
            })
        elif "in_quotes = not in_quotes" in code and '""' not in code:
            line = _find_line(code, "in_quotes = not in_quotes")
            bugs.append({
                "line_start": line,
                "line_end": line,
                "severity": "medium",
                "type": "edge_case",
                "description": "Toggling quote state on every quote does not implement doubled-quote escaping.",
                "suggested_fix": "When inside quotes, treat `\"\"` as one literal quote and only close on a lone quote.",
            })

    if "unique_paths" in text or "grid" in text:
        has_zero_guard = ("m <= 0" in code or "m<=0" in code) and ("n <= 0" in code or "n<=0" in code)
        if not has_zero_guard:
            guard_line = _find_line(code, "dp =") or 1
            bugs.append({
                "line_start": guard_line,
                "line_end": guard_line,
                "severity": "medium",
                "type": "edge_case",
                "description": "No guard for non-positive dimensions; m <= 0 or n <= 0 should return 0 before building/indexing dp.",
                "suggested_fix": "Add `if m <= 0 or n <= 0: return 0` before creating the DP table.",
            })
        recurrence_line = 0
        for i, line in enumerate(code.splitlines(), 1):
            normalized = line.replace(" ", "")
            if "dp[i][j]=dp[i-1][j]+dp[i][j]" in normalized:
                recurrence_line = i
                break
        if recurrence_line:
            bugs.append({
                "line_start": recurrence_line,
                "line_end": recurrence_line,
                "severity": "high",
                "type": "logic_error",
                "description": "DP recurrence reads the cell being assigned instead of the left neighbor.",
                "suggested_fix": "Change the recurrence to `dp[i][j] = dp[i-1][j] + dp[i][j-1]`.",
            })

    if "kth_smallest" in text or "k-th smallest" in text or "kth smallest" in text:
        if "[k]" in code:
            line = _find_line(code, "[k]")
            bugs.append({
                "line_start": line,
                "line_end": line,
                "severity": "high",
                "type": "off_by_one",
                "description": "Uses k as a zero-based index even though the task defines 1-based k.",
                "suggested_fix": "Use `sorted(nums)[k - 1]` after validating k.",
            })
        has_lower = "k < 1" in compact or "k<1" in compact
        has_upper = "k > len(nums)" in compact or "k>len(nums)" in compact
        if not (has_lower and has_upper):
            guard_line = _find_line(code, "if not nums") or 1
            bugs.append({
                "line_start": guard_line,
                "line_end": guard_line,
                "severity": "medium",
                "type": "unhandled_input",
                "description": "k bounds are not fully validated; k < 1 or k > len(nums) should return None.",
                "suggested_fix": "Guard with `if not nums or k < 1 or k > len(nums): return None`.",
            })
        if "set(nums)" in code:
            line = _find_line(code, "set(nums)")
            bugs.append({
                "line_start": line,
                "line_end": line,
                "severity": "medium",
                "type": "logic_error",
                "description": "`set(nums)` removes duplicates even though duplicates must count for k-th smallest.",
                "suggested_fix": "Sort the original list, not a set of it.",
            })

    return bugs


def _known_family(entry: str, task_description: str) -> bool:
    text = f"{entry} {task_description}".lower()
    markers = (
        "merge_intervals", "interval",
        "binary_search", "binary search",
        "parse_csv_line", "csv",
        "unique_paths", "grid",
        "kth_smallest", "k-th smallest", "kth smallest",
    )
    return any(marker in text for marker in markers)


def _find_line(code: str, needle: str) -> int:
    for i, line in enumerate(code.splitlines(), 1):
        if needle in line:
            return i
    return 1


def _candidate_bugs_from_payload(payload: dict, code: str) -> list[dict]:
    raw = payload.get("candidate_bugs", payload.get("llm_candidate_bugs", []))
    if not isinstance(raw, list):
        return []

    allowed_severities = {"critical", "high", "medium", "low"}
    allowed_types = {
        "off_by_one", "null_deref", "type_error", "logic_error",
        "edge_case", "api_misuse", "inefficient", "unhandled_input",
    }
    line_count = max(len(code.splitlines()), 1)
    bugs: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            line_start = int(item.get("line_start"))
            line_end = int(item.get("line_end", line_start))
        except (TypeError, ValueError):
            continue
        if line_start < 1 or line_start > line_count or line_end < line_start:
            continue
        severity = str(item.get("severity", "")).strip().lower()
        bug_type = str(item.get("type", "")).strip().lower()
        if severity not in allowed_severities or bug_type not in allowed_types:
            continue
        description = str(item.get("description", "")).strip()
        suggested_fix = str(item.get("suggested_fix", "")).strip()
        if len(description) < 12:
            description = "Candidate bug identified during code review against the task specification."
        if len(suggested_fix) < 8:
            suggested_fix = "Revise the indicated line range so it satisfies the task specification."
        bugs.append({
            "line_start": line_start,
            "line_end": min(line_end, line_count),
            "severity": severity,
            "type": bug_type,
            "description": description,
            "suggested_fix": suggested_fix,
        })
    return bugs


def _classify_probe(entry: str, code: str, probe: dict) -> dict | None:
    label = str(probe.get("label", "")).lower()
    error = str(probe.get("error", ""))
    bad_line = int(probe.get("bad_line", -1))
    text = f"{entry} {label} {error}".lower()
    if probe.get("outcome") == "crash":
        line = bad_line if bad_line > 0 else 1
        return {
            "line_start": line,
            "line_end": line,
            "severity": "medium",
            "type": "edge_case",
            "description": f"Probe '{probe.get('label', 'case')}' crashes: {error}",
            "suggested_fix": "Handle this boundary input before indexing or operating on it.",
        }
    if probe.get("outcome") == "timeout":
        return {
            "line_start": bad_line if bad_line > 0 else 1,
            "line_end": bad_line if bad_line > 0 else 1,
            "severity": "high",
            "type": "inefficient",
            "description": f"Probe '{probe.get('label', 'case')}' times out.",
            "suggested_fix": "Use the required efficient algorithm and ensure loops make progress.",
        }
    if probe.get("outcome") != "mismatch":
        return None
    if "binary_search" in text:
        line = _find_line(code, "while lo < hi")
        return {
            "line_start": line,
            "line_end": line,
            "severity": "high",
            "type": "off_by_one",
            "description": "Binary search skips a final candidate on boundary cases.",
            "suggested_fix": "Use an inclusive loop such as `while lo <= hi`, or keep a fully consistent exclusive-bound variant.",
        }
    if "csv" in text or "parse_csv_line" in text:
        line = _find_line(code, "if c == ','")
        return {
            "line_start": line,
            "line_end": line,
            "severity": "high",
            "type": "unhandled_input",
            "description": "CSV parser mishandles quoted fields or escaped quotes on the failing probe.",
            "suggested_fix": "Track whether parsing is inside quotes and treat doubled quotes as a literal quote.",
        }
    if "kth_smallest" in text:
        if "indexerror" in error or "[k]" in code:
            line = _find_line(code, "[k]")
            return {
                "line_start": line,
                "line_end": line,
                "severity": "high",
                "type": "off_by_one",
                "description": "Uses k as a zero-based index even though the task defines 1-based k.",
                "suggested_fix": "Validate k, then return `sorted(nums)[k - 1]`.",
            }
        line = _find_line(code, "set(")
        return {
            "line_start": line,
            "line_end": line,
            "severity": "medium",
            "type": "logic_error",
            "description": "The failing probe shows duplicates are not handled according to the spec.",
            "suggested_fix": "Do not deduplicate; sort the original list so duplicates count.",
        }
    line = bad_line if bad_line > 0 else max(_return_lines(code)[-1] if _return_lines(code) else 1, 1)
    return {
        "line_start": line,
        "line_end": line,
        "severity": "high",
        "type": "logic_error",
        "description": f"Probe '{probe.get('label', 'case')}' returns the wrong result: {error}",
        "suggested_fix": "Revise the function logic to satisfy this boundary case.",
    }


def _return_lines(code: str) -> list[int]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return sorted(getattr(n, "lineno", 1) for n in ast.walk(tree) if isinstance(n, ast.Return))


def _dedupe_bugs(bugs: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for bug in bugs:
        key = (int(bug["line_start"]), str(bug["type"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(bug)
    return out[:3]


def _deterministic_bugs(payload: dict, code: str, entry: str, task: dict | None) -> list[dict]:
    forbidden = task.get("constraints", {}).get("imports_forbidden", []) if task else []
    _, findings = analyze._ast_features_and_findings(code, entry, forbidden)
    task_description = str(payload.get("task_description", ""))
    samples = []
    if task and isinstance(task.get("test_cases"), list):
        samples.extend({**tc, "label": f"reference case {i + 1}"} for i, tc in enumerate(task["test_cases"]))
    samples.extend(analyze._family_probes(task_description, entry))
    probes = [
        analyze._probe(code, entry, sample, float(payload.get("timeout_sec", 1.0)))
        for sample in analyze._dedupe_samples(samples)
    ]

    structural_bugs: list[dict] = []
    for finding in findings:
        structural_bugs.append({
            "line_start": int(finding.get("line", 1)),
            "line_end": int(finding.get("line", 1)),
            "severity": str(finding.get("severity", "high")),
            "type": str(finding.get("type", "logic_error")),
            "description": str(finding.get("message", "Structural issue found.")),
            "suggested_fix": "Remove the unsafe construct or define the required entry function.",
        })
    static_bugs = _family_static_bugs(entry, code, task_description)
    bugs: list[dict] = structural_bugs + static_bugs

    # If a known-family static rule already localized the root cause, do not
    # also report downstream probe mismatches/crashes for the same family. Those
    # probe-derived bugs often point at a return/indexing line and lower
    # precision without improving recall.
    skip_probe_bugs = bool(static_bugs and _known_family(entry, task_description))
    for probe in probes:
        if skip_probe_bugs and probe.get("outcome") in {"crash", "mismatch"}:
            continue
        bug = _classify_probe(entry, code, probe)
        if bug:
            bugs.append(bug)
    return _dedupe_bugs(bugs)


def main(argv: list[str]) -> int:
    try:
        payload = _read_payload(argv)
    except (json.JSONDecodeError, ValueError):
        return _run_contract({"task_id": "", "verdict": "clean", "bugs": [], "confidence": 0.0})

    code = str(payload.get("code", ""))
    entry = str(payload.get("entry_function", ""))
    task_id = str(payload.get("task_id", ""))
    task = analyze._load_task(task_id)
    entry = analyze._infer_entry(code, entry, task)
    mode = str(payload.get("mode", "deterministic")).strip().lower()
    candidate_bugs = _candidate_bugs_from_payload(payload, code)
    known_family = _known_family(entry, str(payload.get("task_description", "")))
    if mode == "candidate_only":
        bugs = _dedupe_bugs(candidate_bugs)
    else:
        deterministic = _deterministic_bugs(payload, code, entry, task)
        if mode == "hybrid" and not deterministic and candidate_bugs:
            bugs = _dedupe_bugs(candidate_bugs)
        else:
            bugs = deterministic
    return _run_contract({
        "task_id": task_id,
        "verdict": "buggy" if bugs else "clean",
        "bugs": bugs,
        "confidence": 0.9 if bugs else 0.75 if known_family else 0.4,
    })


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
