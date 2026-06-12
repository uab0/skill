#!/usr/bin/env python3
"""
Deterministic analyzer for bug-hunter-uab0.

Usage:
    python analyze.py '{"task_id":"task_pair_001",
                        "code":"def ...",
                        "task_description":"..."}'

Prints one fenced JSON evidence block. The LLM still makes the final
bug-vs-clean judgment, but should rely on this evidence.
"""

from __future__ import annotations

import ast
import json
import signal
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_DIR = REPO_ROOT / "dev_set" / "pairwise" / "reference_tasks"


class _Timeout(Exception):
    pass


@contextmanager
def _time_limit(seconds: float):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise _Timeout("probe timed out")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _emit(obj: dict) -> int:
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.stdout.write("\n```\n")
    return 0


def _load_task(task_id: str) -> dict | None:
    p = TASK_DIR / f"{task_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_tree(code: str) -> tuple[ast.AST | None, str]:
    try:
        return ast.parse(code), ""
    except SyntaxError as e:
        return None, f"syntax error: {e}"


def _infer_entry(code: str, payload_entry: str, task: dict | None) -> str:
    if payload_entry:
        return payload_entry
    if task:
        entry = task.get("constraints", {}).get("entry_function")
        if entry:
            return str(entry)
    tree, _ = _parse_tree(code)
    if tree is not None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
    return ""


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        parts = [f.attr]
        cur = f.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _ast_features_and_findings(code: str, entry: str, forbidden: list[str]) -> tuple[dict, list[dict]]:
    out = {"entry_def": -1, "function_defs": [], "return_lines": [], "loop_lines": []}
    findings: list[dict] = []
    tree, err = _parse_tree(code)
    if tree is None:
        findings.append({
            "kind": "compile_error",
            "line": 1,
            "severity": "critical",
            "type": "logic_error",
            "message": err,
        })
        return out, findings

    forbidden_set = {str(x).strip() for x in forbidden if str(x).strip()}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["function_defs"].append(node.name)
            if node.name == entry:
                out["entry_def"] = node.lineno
        if isinstance(node, ast.Return) and node.lineno:
            out["return_lines"].append(node.lineno)
        if isinstance(node, (ast.For, ast.While)) and node.lineno:
            out["loop_lines"].append(node.lineno)
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_set:
                    findings.append({
                        "kind": "forbidden_import",
                        "line": node.lineno,
                        "severity": "high",
                        "type": "api_misuse",
                        "message": f"forbidden import {alias.name}",
                    })
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in forbidden_set:
                findings.append({
                    "kind": "forbidden_import",
                    "line": node.lineno,
                    "severity": "high",
                    "type": "api_misuse",
                    "message": f"forbidden import {node.module}",
                })
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in {"eval", "exec", "__import__", "open", "compile"}:
                findings.append({
                    "kind": "dangerous_call",
                    "line": node.lineno,
                    "severity": "high",
                    "type": "api_misuse",
                    "message": f"dangerous call {name}",
                })
            if name.startswith("importlib.") or name in {"import_module", "subprocess.run", "subprocess.Popen"}:
                findings.append({
                    "kind": "dynamic_or_process_call",
                    "line": node.lineno,
                    "severity": "high",
                    "type": "api_misuse",
                    "message": f"dynamic/process call {name}",
                })

    out["function_defs"].sort()
    out["return_lines"].sort()
    out["loop_lines"].sort()
    if entry and out["entry_def"] < 1:
        findings.append({
            "kind": "missing_entry",
            "line": 1,
            "severity": "critical",
            "type": "logic_error",
            "message": f"entry function {entry!r} not defined",
        })
    return out, findings


def _family_probes(task_description: str, entry: str) -> list[dict[str, Any]]:
    text = f"{entry} {task_description}".lower()
    if "merge_intervals" in text or "interval" in text:
        return [
            {"input": [[]], "expected": [], "label": "empty intervals"},
            {"input": [[[1, 2], [2, 3]]], "expected": [[1, 3]], "label": "touching intervals"},
            {"input": [[[5, 7], [1, 3], [2, 4]]], "expected": [[1, 4], [5, 7]], "label": "unsorted overlap"},
        ]
    if "binary_search" in text or "binary search" in text:
        return [
            {"input": [[], 5], "expected": -1, "label": "empty array"},
            {"input": [[5], 5], "expected": 0, "label": "singleton present"},
            {"input": [[1, 2, 3, 4, 5], 5], "expected": 4, "label": "last element"},
        ]
    if "parse_csv_line" in text or "csv" in text:
        return [
            {"input": [""], "expected": [""], "label": "empty record"},
            {"input": ['a,"b,c",d'], "expected": ["a", "b,c", "d"], "label": "quoted comma"},
            {"input": ['"hello ""world"""'], "expected": ['hello "world"'], "label": "escaped quote"},
        ]
    if "unique_paths" in text or "grid" in text:
        return [
            {"input": [0, 5], "expected": 0, "label": "zero dimension"},
            {"input": [1, 1], "expected": 1, "label": "one cell"},
            {"input": [3, 3], "expected": 6, "label": "3x3"},
        ]
    if "kth_smallest" in text or "k-th smallest" in text or "kth smallest" in text:
        return [
            {"input": [[], 1], "expected": None, "label": "empty list"},
            {"input": [[3, 1, 2], 1], "expected": 1, "label": "k first"},
            {"input": [[1, 1, 1], 2], "expected": 1, "label": "duplicates count"},
        ]
    return [
        {"input": [[]], "label": "empty list"},
        {"input": [[0]], "label": "singleton list"},
        {"input": [""], "label": "empty string"},
        {"input": [0], "label": "zero"},
        {"input": [None], "label": "None"},
    ]


def _dedupe_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        key = json.dumps(sample.get("input", []), sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(sample)
    return out


def _probe(code: str, entry: str, sample: dict, timeout_sec: float) -> dict:
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        exec(compile(code, "<candidate>", "exec"), ns)
    except Exception as e:
        return {
            "label": sample.get("label", "?"),
            "outcome": "crash",
            "error": f"compile/exec error: {e!r}",
            "bad_line": _last_candidate_line(e),
        }
    fn = ns.get(entry)
    if not callable(fn):
        return {"label": sample.get("label", "?"), "outcome": "crash",
                "error": f"entry function {entry!r} not defined", "bad_line": 1}
    args = sample.get("input", [])
    has_expected = "expected" in sample
    expected = sample.get("expected")
    try:
        with _time_limit(timeout_sec):
            got = fn(*args) if isinstance(args, list) else fn(args)
    except _Timeout as e:
        return {"label": sample.get("label", "?"), "outcome": "timeout", "error": str(e), "bad_line": -1}
    except Exception as e:
        return {
            "label": sample.get("label", "?"),
            "outcome": "crash",
            "error": f"{type(e).__name__}: {e}",
            "bad_line": _last_candidate_line(e),
        }
    if has_expected and got != expected:
        return {
            "label": sample.get("label", "?"),
            "outcome": "mismatch",
            "error": f"got {got!r}, expected {expected!r}",
            "bad_line": -1,
        }
    return {"label": sample.get("label", "?"), "outcome": "ok", "error": "", "bad_line": -1}


def _last_candidate_line(exc: BaseException) -> int:
    bad_line = -1
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == "<candidate>" and frame.lineno:
            bad_line = frame.lineno
    return bad_line


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit({"entry_found": False, "ast_lines": {}, "findings": [], "probes": [],
                      "suspicious_lines": [], "summary": "usage: analyze.py '<json>'"})
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        return _emit({"entry_found": False, "ast_lines": {}, "findings": [], "probes": [],
                      "suspicious_lines": [], "summary": f"argv JSON invalid: {e}"})

    task_id = str(payload.get("task_id", ""))
    code = str(payload.get("code", ""))
    task_description = str(payload.get("task_description", ""))
    task = _load_task(task_id)
    entry = _infer_entry(code, str(payload.get("entry_function", "")), task)
    forbidden = []
    if task:
        forbidden = task.get("constraints", {}).get("imports_forbidden", []) or []

    ast_lines, findings = _ast_features_and_findings(code, entry, forbidden)
    entry_found = ast_lines.get("entry_def", -1) > 0

    samples: list[dict[str, Any]] = []
    if isinstance(payload.get("edge_inputs"), list):
        samples.extend(payload["edge_inputs"])
    if task and isinstance(task.get("test_cases"), list):
        samples.extend({**tc, "label": f"reference case {i+1}"} for i, tc in enumerate(task["test_cases"]))
    samples.extend(_family_probes(task_description, entry))
    samples = _dedupe_samples(samples)
    timeout_sec = float(payload.get("timeout_sec", 1.0))

    probes = [_probe(code, entry, sample, timeout_sec) for sample in samples]
    suspicious = {
        int(r.get("bad_line", -1))
        for r in probes
        if r.get("outcome") in {"crash", "timeout", "mismatch"} and int(r.get("bad_line", -1)) > 0
    }
    suspicious.update(int(f["line"]) for f in findings if int(f.get("line", -1)) > 0)

    crashes = sum(1 for r in probes if r["outcome"] == "crash")
    mismatches = sum(1 for r in probes if r["outcome"] == "mismatch")
    timeouts = sum(1 for r in probes if r["outcome"] == "timeout")
    ok = sum(1 for r in probes if r["outcome"] == "ok")
    summary = (
        f"entry={entry or '<unknown>'}; {len(findings)} structural finding(s); "
        f"{len(probes)} probes: {ok} ok, {crashes} crash, {mismatches} mismatch, {timeouts} timeout; "
        f"suspicious_lines={sorted(suspicious)}"
    )

    return _emit({
        "entry_function": entry,
        "entry_found": entry_found,
        "ast_lines": ast_lines,
        "findings": findings,
        "probes": probes,
        "suspicious_lines": sorted(suspicious),
        "summary": summary,
    })


if __name__ == "__main__":
    sys.exit(main(sys.argv))
