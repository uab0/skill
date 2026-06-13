#!/usr/bin/env python3
"""Single entrypoint for code-author-uab0."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from author import _template  # noqa: E402
from selftest import compute_sloc, generated_samples, run_sample, structural_violations  # noqa: E402

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
    return payload


def _self_test(code: str, desc: str, constraints: dict) -> dict:
    entry = str(constraints.get("entry_function", ""))
    samples = generated_samples(desc, entry)
    passed = 0
    failed = 0
    errors: list[str] = []
    for sample in samples:
        ok, err = run_sample(code, entry, sample)
        if ok:
            passed += 1
        else:
            failed += 1
            errors.append(f"{sample.get('label', 'sample')}: {err}")
    forbidden = constraints.get("imports_forbidden", []) or []
    security = structural_violations(code, entry, forbidden)
    loc = compute_sloc(code)
    if loc > int(constraints.get("max_loc", 500)):
        security.append(f"loc violation: {loc} > {constraints.get('max_loc', 500)}")
    return {
        "passed": passed,
        "failed": failed + len(security),
        "errors": (errors + security)[:20],
        "loc_violation": loc > int(constraints.get("max_loc", 500)),
        "import_violations": [x for x in security if x.startswith("forbidden import:")],
        "security_violations": security,
        "generated_samples": len(samples),
    }


def main(argv: list[str]) -> int:
    try:
        payload = _read_payload(argv)
    except (json.JSONDecodeError, ValueError) as e:
        return _run_contract({
            "task_id": "",
            "code": "",
            "loc": 0,
            "self_test_results": {"passed": 0, "failed": 1, "errors": [f"Invalid input JSON: {e}"]},
            "rationale": "Invalid input.",
            "confidence": 0.0,
        })

    constraints = payload.get("constraints", {}) or {}
    if not isinstance(constraints, dict):
        constraints = {}
    desc = str(payload.get("task_description", ""))
    entry = str(constraints.get("entry_function", "solution"))
    code = str(payload.get("candidate_code", "")).strip()
    if code:
        rationale = "Validated LLM candidate code with deterministic self-tests."
        confidence = 0.65
    else:
        code, rationale, confidence = _template(entry, desc)

    self_test = _self_test(code, desc, constraints)
    if self_test["failed"]:
        confidence = min(confidence, 0.35)

    return _run_contract({
        "task_id": str(payload.get("task_id", "")),
        "code": code,
        "loc": compute_sloc(code),
        "self_test_results": self_test,
        "rationale": rationale,
        "confidence": confidence,
    })


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
