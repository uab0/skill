#!/usr/bin/env python3
"""
Deterministic SQL validator for text2sql-uab0.

Usage:
    python validate_sql.py '{"db_schema":"CREATE TABLE ...", "sql":"SELECT ..."}'

Also accepts the legacy/internal key `schema_ddl`.
Prints one fenced JSON block:
    {"ok": bool, "error": str, "warnings": [str]}
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from typing import Any


FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|DETACH|REPLACE|TRUNCATE|VACUUM|PRAGMA)\b",
    re.IGNORECASE,
)
CTE_OR_WINDOW = re.compile(r"^\s*WITH\b|\bOVER\s*\(", re.IGNORECASE | re.DOTALL)
LEFT_JOIN = re.compile(r"\bLEFT\s+(?:OUTER\s+)?JOIN\b", re.IGNORECASE)
COUNT_STAR = re.compile(r"\bCOUNT\s*\(\s*\*\s*\)", re.IGNORECASE)
LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)
ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
DISTINCT = re.compile(r"\bDISTINCT\b", re.IGNORECASE)
JOIN = re.compile(r"\bJOIN\b", re.IGNORECASE)
UNION_ALL = re.compile(r"\bUNION\s+ALL\b", re.IGNORECASE)
UNION = re.compile(r"\bUNION\b", re.IGNORECASE)


WRITE_ACTIONS = {
    name
    for name in (
        "SQLITE_INSERT",
        "SQLITE_UPDATE",
        "SQLITE_DELETE",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_ALTER_TABLE",
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
        "SQLITE_PRAGMA",
        "SQLITE_TRANSACTION",
    )
    if hasattr(sqlite3, name)
}
WRITE_ACTION_CODES = {getattr(sqlite3, name) for name in WRITE_ACTIONS}


def _emit(ok: bool, error: str = "", warnings: list[str] | None = None) -> int:
    out = {"ok": bool(ok), "error": error, "warnings": warnings or []}
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
    sys.stdout.write("\n```\n")
    return 0 if ok else 1


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def _authorizer(action: int, arg1: str | None, arg2: str | None,
                dbname: str | None, source: str | None) -> int:
    if action in WRITE_ACTION_CODES:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def semantic_warnings(sql: str) -> list[str]:
    warnings: list[str] = []
    upper = sql.upper()

    if LEFT_JOIN.search(sql) and COUNT_STAR.search(sql):
        warnings.append("LEFT JOIN with COUNT(*) can miscount zero-child rows; consider COUNT(child_id).")
    if LEFT_JOIN.search(sql) and re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        warnings.append("LEFT JOIN plus WHERE may filter away unmatched rows if WHERE references the right table.")
    if len(JOIN.findall(sql)) >= 2 and not DISTINCT.search(sql) and re.search(
        r"\b(name|title)\b", sql, re.IGNORECASE
    ):
        warnings.append("Multi-join entity listing without DISTINCT may produce duplicate rows.")
    if LIMIT.search(sql) and not ORDER_BY.search(sql):
        warnings.append("LIMIT without ORDER BY is nondeterministic unless the question permits any row.")
    if LIMIT.search(sql) and re.search(r"\b(top|most|highest|lowest|max|min|tie|ties)\b", upper, re.IGNORECASE):
        warnings.append("LIMIT may mishandle ties; ensure the question does not require all tied rows.")
    if UNION.search(sql) and not UNION_ALL.search(sql):
        warnings.append("UNION removes duplicates; ensure duplicate preservation is not required.")
    return warnings


def validate(schema_ddl: str, sql: str) -> tuple[bool, str]:
    ok, err, _ = validate_with_warnings(schema_ddl, sql)
    return ok, err


def validate_with_warnings(schema_ddl: str, sql: str) -> tuple[bool, str, list[str]]:
    sql_stripped = _strip_trailing_semicolon(sql)
    if not sql_stripped:
        return False, "empty SQL", []
    if ";" in sql_stripped:
        return False, "multiple SQL statements not allowed", []
    if CTE_OR_WINDOW.search(sql_stripped):
        return False, "CTE/WITH and window functions are out of scope", []
    if FORBIDDEN.search(sql_stripped):
        return False, "DDL/DML/PRAGMA not allowed; SELECT only", []
    if not re.match(r"^\s*SELECT\b", sql_stripped, re.IGNORECASE):
        return False, "SQL must start with SELECT", []

    warnings = semantic_warnings(sql_stripped)
    con = sqlite3.connect(":memory:")
    try:
        if schema_ddl:
            try:
                con.executescript(schema_ddl)
            except sqlite3.Error as e:
                return False, f"schema DDL did not parse: {e}", warnings
        con.execute("PRAGMA query_only = ON;")
        con.set_authorizer(_authorizer)
        try:
            con.execute(f"EXPLAIN {sql_stripped}")
        except sqlite3.Error as e:
            return False, f"SQL did not compile: {e}", warnings
        return True, "", warnings
    finally:
        con.close()


def _payload_schema(payload: dict[str, Any]) -> str:
    return str(payload.get("db_schema") or payload.get("schema_ddl") or "")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit(False, "usage: validate_sql.py '<json payload>'")
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        return _emit(False, f"argv JSON invalid: {e}")
    ok, err, warnings = validate_with_warnings(_payload_schema(payload), str(payload.get("sql", "")))
    return _emit(ok, err, warnings)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
