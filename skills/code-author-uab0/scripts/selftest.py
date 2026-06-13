#!/usr/bin/env python3
"""
Deterministic self-test harness for code-author-uab0.

Usage:
    python selftest.py '{"code":"def f(...): ...",
                         "task_description":"...",
                         "constraints":{"entry_function":"f", ...},
                         "sample_inputs":[{"input":[...],"expected":...}]}'

Prints one fenced JSON block with passed/failed counts, errors, SLOC, and
structural violations.
"""

from __future__ import annotations

import ast
import csv
import json
import math
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


DEFAULT_FORBIDDEN_IMPORTS = {
    "os", "sys", "subprocess", "multiprocessing", "threading", "socket",
    "requests", "urllib", "pathlib", "importlib",
}
DEFAULT_DANGEROUS_CALLS = {
    "eval", "exec", "__import__", "open", "compile", "input",
    "globals", "locals", "vars",
}


class _Timeout(Exception):
    pass


@contextmanager
def _time_limit(seconds: float):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise _Timeout("sample timed out")

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


def compute_sloc(code: str) -> int:
    return compute_sloc_detail(code)[0]


def compute_sloc_detail(code: str) -> tuple[int, str]:
    """Use `radon raw` when available; fallback to nonblank noncomment line count."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        path = Path(f.name)
    try:
        try:
            proc = subprocess.run(
                ["radon", "raw", str(path), "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, dict) and "sloc" in v:
                            return int(v["sloc"]), "radon"
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        count = 0
        for line in code.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                count += 1
        return count, "fallback"
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _parse_tree(code: str) -> tuple[ast.AST | None, str]:
    try:
        return ast.parse(code), ""
    except SyntaxError as e:
        return None, f"syntax error: {e}"


def find_import_violations(code: str, forbidden: list[str]) -> list[str]:
    tree, err = _parse_tree(code)
    if tree is None:
        return [err]
    forbidden_set = DEFAULT_FORBIDDEN_IMPORTS | {f.strip() for f in forbidden if f.strip()}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_set:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in forbidden_set:
                found.append(node.module)
    return sorted(set(found))


def structural_violations(code: str, entry: str, forbidden: list[str]) -> list[str]:
    tree, err = _parse_tree(code)
    if tree is None:
        return [err]

    violations: list[str] = []
    functions = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if entry and entry not in functions:
        violations.append(f"entry function {entry!r} not defined")

    for imp in find_import_violations(code, forbidden):
        violations.append(f"forbidden import: {imp}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in DEFAULT_DANGEROUS_CALLS:
                violations.append(f"dangerous call at line {node.lineno}: {name}")
            if name.startswith("importlib.") or name in {
                "import_module", "subprocess.run", "subprocess.Popen",
                "getattr", "setattr", "delattr",
            }:
                violations.append(f"dynamic/process call at line {node.lineno}: {name}")
        if isinstance(node, (ast.For, ast.While, ast.With, ast.Try)) and isinstance(getattr(node, "parent", None), ast.Module):
            violations.append(f"top-level executable block at line {node.lineno}: {type(node).__name__}")
    return sorted(set(violations))


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


def generated_samples(task_description: str, entry: str) -> list[dict[str, Any]]:
    text = f"{entry} {task_description}".lower()
    if "merge_intervals" in text or "interval" in text:
        base = [[5, 7], [1, 3], [2, 4], [4, 4], [-2, -1], [-1, 0]]
        merged_base = _merge_intervals_oracle(base)
        return [
            {"input": [[]], "expected": [], "label": "empty intervals"},
            {"input": [[[1, 3]]], "expected": [[1, 3]], "label": "singleton interval"},
            {"input": [[[1, 3], [2, 4]]], "expected": [[1, 4]], "label": "overlap"},
            {"input": [[[1, 2], [2, 3], [3, 5]]], "expected": [[1, 5]], "label": "touching"},
            {"input": [[[5, 7], [1, 3], [2, 4]]], "expected": [[1, 4], [5, 7]], "label": "unsorted"},
            {"input": [base], "expected": merged_base, "label": "negative endpoints and permutation"},
            {"input": [merged_base], "expected": merged_base, "label": "idempotence on merged output"},
            {"input": [[[1, 1], [1, 1], [2, 2]]], "expected": [[1, 1], [2, 2]], "label": "duplicate zero-width intervals"},
        ]
    if "binary_search" in text or "binary search" in text:
        return [
            {"input": [[], 5], "expected": -1, "label": "empty"},
            {"input": [[5], 5], "expected": 0, "label": "singleton present"},
            {"input": [[5], 7], "expected": -1, "label": "singleton missing"},
            {"input": [[1, 2, 3, 4, 5], 1], "expected": 0, "label": "first"},
            {"input": [[1, 2, 3, 4, 5], 5], "expected": 4, "label": "last"},
            {"input": [[1, 2, 4, 8, 16], 3], "expected": -1, "label": "middle absent"},
            {"input": [[-5, -2, 0, 4], -5], "expected": 0, "label": "negative first"},
            {"input": [[1, 2, 2, 2, 3], 2], "expected_any_index_value": 2, "label": "duplicates any matching index"},
        ]
    if "parse_csv_line" in text or "csv" in text:
        lines = [
            ("empty record", ""),
            ("empty field", "a,,b"),
            ("trailing comma", "a,b,"),
            ("quoted comma", 'a,"b,c",d'),
            ("escaped quote", '"hello ""world"""'),
            ("quoted empty", '"",x'),
            ("two quoted fields", '"a","b"'),
        ]
        return [{"input": [line], "expected": _csv_oracle(line), "label": label} for label, line in lines]
    if "unique_paths" in text or "grid" in text:
        dims = [
            ("zero m", 0, 5),
            ("zero n", 5, 0),
            ("one cell", 1, 1),
            ("one row", 1, 5),
            ("one column", 5, 1),
            ("2x2", 2, 2),
            ("3x3", 3, 3),
            ("3x7", 3, 7),
        ]
        return [
            {"input": [m, n], "expected": _unique_paths_oracle(m, n), "label": label}
            for label, m, n in dims
        ]
    if "kth_smallest" in text or "k-th smallest" in text or "kth smallest" in text:
        cases = [
            ("empty", [], 1),
            ("k zero", [1, 2, 3], 0),
            ("k negative", [1, 2, 3], -1),
            ("first", [3, 1, 2], 1),
            ("middle", [3, 1, 2], 2),
            ("last", [3, 1, 2], 3),
            ("duplicates count", [1, 1, 1], 2),
            ("negative numbers", [-1, -5, 3, 0], 2),
            ("reverse sorted", [5, 4, 3, 2, 1], 3),
            ("k too large", [5], 2),
        ]
        return [
            {"input": [nums, k], "expected": _kth_smallest_oracle(nums, k), "label": label}
            for label, nums, k in cases
        ]
    return []


def _merge_intervals_oracle(intervals: list[list[int]]) -> list[list[int]]:
    if not intervals:
        return []
    items = sorted([list(x) for x in intervals], key=lambda x: x[0])
    merged = [items[0]]
    for cur in items[1:]:
        if cur[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], cur[1])
        else:
            merged.append(cur)
    return merged


def _csv_oracle(line: str) -> list[str]:
    return next(csv.reader([line]))


def _unique_paths_oracle(m: int, n: int) -> int:
    if m <= 0 or n <= 0:
        return 0
    return math.comb(m + n - 2, m - 1)


def _kth_smallest_oracle(nums: list[int], k: int) -> Any:
    if not nums or k < 1 or k > len(nums):
        return None
    return sorted(nums)[k - 1]


def _dedupe_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        key = json.dumps(_sample_args(sample), sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(sample)
    return out


def _sample_args(sample: dict) -> Any:
    if "args" in sample:
        return sample.get("args", [])
    if "target" in sample:
        return [sample.get("input", []), sample.get("target")]
    return sample.get("input", [])


def run_sample(code: str, entry: str, sample: dict, timeout_sec: float = 1.0) -> tuple[bool, str]:
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        exec(compile(code, "<candidate>", "exec"), ns)
    except Exception as e:
        return False, f"compile/exec error: {e!r}"
    fn = ns.get(entry)
    if not callable(fn):
        return False, f"entry function {entry!r} not defined"
    args = _sample_args(sample)
    expected = sample.get("expected")
    try:
        with _time_limit(timeout_sec):
            got = fn(*args) if isinstance(args, list) else fn(args)
    except _Timeout as e:
        return False, f"timeout on input {args!r}: {e}"
    except Exception as e:
        return False, f"runtime error on input {args!r}: {e!r}"
    if "expected_any_index_value" in sample:
        arr = args[0] if isinstance(args, list) and args else []
        target = sample["expected_any_index_value"]
        if not isinstance(got, int) or got < 0 or got >= len(arr) or arr[got] != target:
            return False, f"expected any valid index for {target!r}, got {got!r}"
        return True, ""
    if got != expected:
        return False, f"mismatch on {args!r}: got {got!r}, expected {expected!r}"
    return True, ""


def main(argv: list[str]) -> int:
    empty = {
        "passed": 0,
        "failed": 0,
        "errors": [],
        "sloc": 0,
        "sloc_source": "fallback",
        "loc_violation": False,
        "import_violations": [],
        "security_violations": [],
    }
    if len(argv) < 2:
        empty["errors"] = ["usage: selftest.py '<json>'"]
        return _emit(empty)
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        empty["errors"] = [f"argv JSON invalid: {e}"]
        return _emit(empty)

    code = str(payload.get("code", ""))
    task_description = str(payload.get("task_description", ""))
    constraints = payload.get("constraints", {}) or {}
    if not isinstance(constraints, dict):
        constraints = {}
    entry = str(constraints.get("entry_function", ""))
    forbidden = constraints.get("imports_forbidden", []) or []
    if not isinstance(forbidden, list):
        forbidden = []

    provided = payload.get("sample_inputs", []) or []
    if not isinstance(provided, list):
        provided = []
    samples = _dedupe_samples(provided + generated_samples(task_description, entry))

    sloc, sloc_source = compute_sloc_detail(code)
    try:
        max_loc = int(constraints.get("max_loc", 500))
    except (TypeError, ValueError):
        max_loc = 500
    loc_violation = sloc > max_loc
    import_violations = find_import_violations(code, forbidden)
    security_violations = structural_violations(code, entry, forbidden)

    passed = 0
    failed = 0
    errors: list[str] = []
    if not entry:
        errors.append("constraints.entry_function not provided")
    if not samples:
        errors.append("no sample_inputs and no generated task-family samples")

    if entry:
        for s in samples:
            ok, err = run_sample(code, entry, s)
            if ok:
                passed += 1
            else:
                failed += 1
                label = s.get("label")
                errors.append(f"{label}: {err}" if label else err)

    return _emit({
        "passed": passed,
        "failed": failed,
        "errors": errors[:20],
        "sloc": sloc,
        "sloc_source": sloc_source,
        "loc_violation": loc_violation,
        "import_violations": import_violations,
        "security_violations": security_violations,
        "generated_samples": len(samples) - len(provided),
    })


if __name__ == "__main__":
    sys.exit(main(sys.argv))
