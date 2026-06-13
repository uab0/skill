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
SELECT_STAR = re.compile(r"\bSELECT\s+(?:DISTINCT\s+)?\*", re.IGNORECASE)
NOT_IN = re.compile(r"\bNOT\s+IN\s*\(", re.IGNORECASE)
GROUP_BY = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
AGGREGATE = re.compile(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)


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


def _schema_summary(schema_ddl: str) -> dict[str, Any]:
    tables: dict[str, list[str]] = {}
    bridge_tables: set[str] = set()
    for m in re.finditer(
        r"CREATE\s+TABLE\s+([A-Za-z_][\w]*)\s*\((.*?)\)\s*;?",
        schema_ddl,
        re.IGNORECASE | re.DOTALL,
    ):
        table = m.group(1)
        body = m.group(2)
        columns: list[str] = []
        for part in body.split(","):
            token = part.strip().split()
            if not token:
                continue
            col = token[0].strip('"`[]')
            if col.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
                continue
            columns.append(col)
        tables[table.lower()] = columns
        id_like = [c for c in columns if c.lower().endswith("id") or c.lower().endswith("_id")]
        if len(id_like) >= 2 or re.search(r"PRIMARY\s+KEY\s*\([^)]*,[^)]*\)", body, re.IGNORECASE):
            bridge_tables.add(table.lower())
    return {"tables": tables, "bridge_tables": bridge_tables}


def _select_list(sql: str) -> str:
    m = re.search(r"\bSELECT\b\s+(.*?)\s+\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else ""


def semantic_warnings(sql: str, question: str = "", schema_ddl: str = "") -> list[str]:
    warnings: list[str] = []
    upper = sql.upper()
    q = question.lower()
    summary = _schema_summary(schema_ddl)

    if SELECT_STAR.search(sql):
        warnings.append("SELECT * risks extra columns or wrong column order under tuple-based grading.")
    if LEFT_JOIN.search(sql) and COUNT_STAR.search(sql):
        warnings.append("LEFT JOIN with COUNT(*) can miscount zero-child rows; consider COUNT(child_id).")
    for alias in re.findall(
        r"\bLEFT\s+(?:OUTER\s+)?JOIN\s+\w+(?:\s+(?:AS\s+)?(\w+))?",
        sql,
        re.IGNORECASE,
    ):
        if alias and re.search(r"\bWHERE\b.*\b" + re.escape(alias) + r"\.", sql, re.IGNORECASE | re.DOTALL):
            if not re.search(r"\b" + re.escape(alias) + r"\.\w+\s+IS\s+NULL\b", sql, re.IGNORECASE):
                warnings.append("LEFT JOIN right-table predicate in WHERE may turn the LEFT JOIN into an INNER JOIN.")
                break
    if len(JOIN.findall(sql)) >= 2 and not DISTINCT.search(sql) and re.search(
        r"\b(name|title)\b", sql, re.IGNORECASE
    ):
        warnings.append("Multi-join entity listing without DISTINCT may produce duplicate rows.")
    if summary["bridge_tables"] and not DISTINCT.search(sql) and not GROUP_BY.search(sql):
        joined_bridge = [t for t in summary["bridge_tables"] if re.search(r"\b" + re.escape(t) + r"\b", sql, re.IGNORECASE)]
        if joined_bridge and re.search(r"\b(name|title)\b", _select_list(sql), re.IGNORECASE):
            warnings.append("Join through bridge table without DISTINCT/GROUP BY may duplicate listed entities.")
    if LIMIT.search(sql) and not ORDER_BY.search(sql):
        warnings.append("LIMIT without ORDER BY is nondeterministic unless the question permits any row.")
    if LIMIT.search(sql) and re.search(r"\b(top|most|highest|lowest|max|min|tie|ties|tied)\b", f"{upper} {question}", re.IGNORECASE):
        warnings.append("LIMIT may mishandle ties; ensure the question does not require all tied rows.")
    if re.search(r"\b(all tied|ties|tied)\b", q) and LIMIT.search(sql):
        warnings.append("Question asks for all tied rows; LIMIT is likely wrong unless paired with tie-safe logic.")
    if NOT_IN.search(sql) and re.search(r"\b(not|no|none|never|without)\b", q):
        warnings.append("NOT IN can be unsafe when the subquery may contain NULL; consider NOT EXISTS.")
    if UNION.search(sql) and not UNION_ALL.search(sql):
        if re.search(r"\b(duplicate|duplicates|occurrence|occurrences|including duplicates)\b", q):
            warnings.append("UNION removes duplicates but the question may require duplicate preservation; consider UNION ALL.")
        else:
            warnings.append("UNION removes duplicates; ensure duplicate preservation is not required.")
    if AGGREGATE.search(sql) and not GROUP_BY.search(sql):
        select_list = _select_list(sql)
        if re.search(r"\b(name|title|dept|category|city|country)\b", select_list, re.IGNORECASE):
            warnings.append("Bare columns with aggregate and no GROUP BY are SQLite-specific and often semantically wrong.")
    if question:
        wanted = []
        for key in ("name", "age", "title", "count", "average", "avg", "category", "revenue"):
            if re.search(r"\b" + re.escape(key) + r"\b", q):
                wanted.append(key)
        select_lower = _select_list(sql).lower()
        if len(wanted) >= 2:
            first, second = wanted[0], wanted[1]
            first_pos = select_lower.find("avg" if first == "average" else first)
            second_pos = select_lower.find("avg" if second == "average" else second)
            if first_pos >= 0 and second_pos >= 0 and second_pos < first_pos:
                warnings.append("Projection order may not match the order requested in the question.")
    return warnings


def validate(schema_ddl: str, sql: str) -> tuple[bool, str]:
    ok, err, _ = validate_with_warnings(schema_ddl, sql)
    return ok, err


def validate_with_warnings(schema_ddl: str, sql: str) -> tuple[bool, str, list[str]]:
    return validate_with_warnings_for_question(schema_ddl, sql, "")


def validate_with_warnings_for_question(schema_ddl: str, sql: str, question: str = "") -> tuple[bool, str, list[str]]:
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

    warnings = semantic_warnings(sql_stripped, question=question, schema_ddl=schema_ddl)
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
    ok, err, warnings = validate_with_warnings_for_question(
        _payload_schema(payload), str(payload.get("sql", "")), str(payload.get("question", ""))
    )
    return _emit(ok, err, warnings)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
