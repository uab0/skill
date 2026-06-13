#!/usr/bin/env python3
"""Single entrypoint for text2sql-uab0.

The LLM should call this script first. If it already has a candidate SQL, pass it
as `candidate_sql`; this script validates and emits the final Basic contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from solve import solve  # noqa: E402
from validate_sql import validate_with_warnings_for_question  # noqa: E402

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


def main(argv: list[str]) -> int:
    try:
        payload = _read_payload(argv)
    except (json.JSONDecodeError, ValueError) as e:
        return _run_contract({
            "task_id": "",
            "sql": "",
            "rationale": f"Invalid input JSON: {e}",
            "confidence": 0.0,
        })

    task_id = str(payload.get("task_id", ""))
    schema = str(payload.get("db_schema", payload.get("schema_ddl", "")))
    question = str(payload.get("question", ""))
    candidate = str(payload.get("candidate_sql", "")).strip()

    if candidate:
        ok, error, warnings = validate_with_warnings_for_question(schema, candidate, question)
        warning_text = "; ".join(warnings[:3])
        return _run_contract({
            "task_id": task_id,
            "sql": candidate if ok else "",
            "rationale": (
                "Validated LLM candidate SQL."
                if ok and not warnings else
                f"Validated candidate with semantic risk warnings: {warning_text}"
                if ok else
                f"Rejected candidate SQL: {error}"
            ),
            "confidence": 0.55 if ok and warnings else 0.7 if ok else 0.0,
        })

    sql, rationale, confidence = solve(question, schema)
    return _run_contract({
        "task_id": task_id,
        "sql": sql,
        "rationale": rationale,
        "confidence": confidence,
    })


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
