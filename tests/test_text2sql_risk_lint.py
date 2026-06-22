"""Tests for Text2SQL semantic-risk lint warnings."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = ROOT / "skills" / "text2sql-uab0" / "scripts" / "validate_sql.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_sql_risk", VALIDATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


vs = _load()

SCHEMA = """
CREATE TABLE Authors (aid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE Books (bid INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE BookAuthors (bid INTEGER, aid INTEGER, PRIMARY KEY (bid, aid));
CREATE TABLE Loans (lid INTEGER PRIMARY KEY, bid INTEGER, returned INTEGER);
"""


def _warnings(sql: str, question: str = "") -> list[str]:
    ok, err, warnings = vs.validate_with_warnings_for_question(SCHEMA, sql, question)
    assert ok, err
    return warnings


def test_select_star_warns():
    warnings = _warnings("SELECT * FROM Authors;")
    assert any("SELECT *" in w for w in warnings)


def test_bridge_join_without_distinct_warns():
    warnings = _warnings(
        "SELECT a.name FROM Authors a JOIN BookAuthors ba ON a.aid = ba.aid JOIN Books b ON ba.bid = b.bid;"
    )
    assert any("duplicate" in w.lower() for w in warnings)


def test_tie_limit_warns():
    warnings = _warnings(
        "SELECT name FROM Authors ORDER BY aid DESC LIMIT 1;",
        "Return all tied authors with the most books.",
    )
    assert any("tied" in w.lower() or "tie" in w.lower() for w in warnings)


def test_not_in_null_hazard_warns():
    warnings = _warnings(
        "SELECT title FROM Books WHERE bid NOT IN (SELECT bid FROM Loans);",
        "Return books without loans.",
    )
    assert any("NOT IN" in w for w in warnings)
