"""Regression tests for the deterministic Text2SQL first-pass solver."""

import importlib.util
import json
from pathlib import Path

import pytest

from run_dev import bag_equal, run_sql


ROOT = Path(__file__).resolve().parents[1]
SOLVE_PATH = ROOT / "skills" / "text2sql-uab0" / "scripts" / "solve.py"


def _load_solve():
    spec = importlib.util.spec_from_file_location("text2sql_solve", SOLVE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.solve


def test_solver_covers_basic_dev_set():
    solve = _load_solve()
    tasks = sorted((ROOT / "dev_set" / "basic").glob("task_nl2sql_*.json"))
    assert tasks
    for path in tasks:
        task = json.loads(path.read_text(encoding="utf-8"))
        db_path = ROOT / task["db_path"]
        if not db_path.exists():
            pytest.skip("basic dev databases have not been generated")
        sql, _, confidence = solve(task["question"], task["db_schema"])
        assert confidence >= 0.85, task["task_id"]
        assert sql.strip(), task["task_id"]
        assert bag_equal(
            run_sql(db_path, sql),
            run_sql(db_path, task["gold_sql"]),
        ), task["task_id"]


def test_solver_does_not_high_confidence_match_count_perturbation():
    solve = _load_solve()
    task = json.loads((ROOT / "dev_set" / "basic" / "task_nl2sql_EXAMPLE.json").read_text(encoding="utf-8"))
    sql, _, confidence = solve(
        "How many students are in the CS department?",
        task["db_schema"],
    )
    assert sql == ""
    assert confidence < 0.85
