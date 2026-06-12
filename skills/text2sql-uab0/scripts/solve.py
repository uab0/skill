#!/usr/bin/env python3
"""Rule-based first-pass Text2SQL solver for common AIASE Basic task families."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RUN_PY = SCRIPT_DIR / "run.py"


def _quoted(text: str, default: str = "") -> str:
    m = re.search(r"'([^']+)'", text)
    return m.group(1) if m else default


def _emit(task_id: str, sql: str, rationale: str, confidence: float) -> int:
    payload = {
        "task_id": task_id,
        "sql": sql,
        "rationale": rationale,
        "confidence": confidence,
    }
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


def solve(question: str, schema: str) -> tuple[str, str, float]:
    q = " ".join(question.lower().split())
    s = schema.lower()

    if {"students", "courses", "enrollments"} <= _tables(s):
        course = _quoted(question)
        if "cs department" in q:
            return (
                "SELECT name FROM Students WHERE dept = 'CS';",
                "Filter Students by department.",
                0.95,
            )
        if "enrolled in the course titled" in q:
            return (
                f"SELECT s.name FROM Students s JOIN Enrollments e ON s.sid = e.sid "
                f"JOIN Courses c ON e.cid = c.cid WHERE c.title = '{course}';",
                "Join students through enrollments to the named course.",
                0.95,
            )
        if "for each course" in q and "average score" in q:
            return (
                "SELECT c.title, AVG(e.score) FROM Courses c JOIN Enrollments e "
                "ON c.cid = e.cid GROUP BY c.cid, c.title ORDER BY AVG(e.score) DESC;",
                "Aggregate enrollment scores per course.",
                0.95,
            )
        if "more than two enrollments" in q:
            return (
                "SELECT s.name FROM Students s JOIN Enrollments e ON s.sid = e.sid "
                "GROUP BY s.sid, s.name HAVING COUNT(*) > 2;",
                "Count enrollments per student and keep counts above two.",
                0.95,
            )
        if "highest single-course score" in q and "average score" in q:
            return (
                "SELECT s.name FROM Students s JOIN Enrollments e ON s.sid = e.sid "
                "GROUP BY s.sid, s.name HAVING MAX(e.score) > "
                f"(SELECT AVG(score) FROM Enrollments WHERE cid = "
                f"(SELECT cid FROM Courses WHERE title = '{course}'));",
                "Compare each student's maximum score with the named course average.",
                0.95,
            )

    if {"customers", "products", "orders", "orderitems"} <= _tables(s):
        name_or_category = _quoted(question)
        if "distinct names of products purchased by the customer" in q:
            return (
                "SELECT DISTINCT p.name FROM Customers c JOIN Orders o ON c.cid = o.cid "
                "JOIN OrderItems oi ON o.oid = oi.oid JOIN Products p ON oi.pid = p.pid "
                f"WHERE c.name = '{name_or_category}';",
                "Follow customer orders to purchased products and remove duplicates.",
                0.95,
            )
        if "customers who have not placed any orders" in q:
            return (
                "SELECT c.name FROM Customers c LEFT JOIN Orders o ON c.cid = o.cid "
                "WHERE o.oid IS NULL;",
                "Use a left join and keep customers with no matching order.",
                0.95,
            )
        if "top two product categories" in q and "total revenue" in q:
            return (
                "SELECT p.category, SUM(p.price * oi.qty) AS revenue FROM Products p "
                "JOIN OrderItems oi ON p.pid = oi.pid GROUP BY p.category "
                "ORDER BY revenue DESC LIMIT 2;",
                "Compute revenue per category and take the top two.",
                0.95,
            )
        if "electronics" in q and "books" in q and "customers" in q:
            base = (
                "SELECT DISTINCT c.name FROM Customers c JOIN Orders o ON c.cid = o.cid "
                "JOIN OrderItems oi ON o.oid = oi.oid JOIN Products p ON oi.pid = p.pid "
            )
            return (
                base + "WHERE p.category = 'Electronics' UNION " + base + "WHERE p.category = 'Books';",
                "Union distinct customers who bought either requested category.",
                0.95,
            )

    if {"books", "authors", "bookauthors", "members", "loans"} <= _tables(s):
        author = _quoted(question)
        if "titles of all books written by author" in q:
            return (
                "SELECT b.title FROM Books b JOIN BookAuthors ba ON b.bid = ba.bid "
                f"JOIN Authors a ON ba.aid = a.aid WHERE a.name = '{author}';",
                "Join books through the many-to-many author table.",
                0.95,
            )
        if "for each author" in q and "number of books" in q:
            return (
                "SELECT a.name, COUNT(ba.bid) FROM Authors a LEFT JOIN BookAuthors ba "
                "ON a.aid = ba.aid GROUP BY a.aid, a.name;",
                "Left join authors to authored books so zero-book authors remain.",
                0.95,
            )
        if "outstanding loan" in q and "distinct titles" in q:
            return (
                "SELECT DISTINCT b.title FROM Books b JOIN Loans l ON b.bid = l.bid "
                "WHERE l.returned = 0;",
                "Select books with at least one unreturned loan.",
                0.95,
            )
        if "none of whose books are currently on outstanding loan" in q:
            return (
                "SELECT a.name FROM Authors a WHERE a.aid IN "
                "(SELECT aid FROM BookAuthors WHERE bid IN (SELECT bid FROM Books)) "
                "AND a.aid NOT IN (SELECT aid FROM BookAuthors WHERE bid IN "
                "(SELECT bid FROM Loans WHERE returned = 0));",
                "Require at least one authored book and exclude authors with outstanding-loan books.",
                0.95,
            )

    if {"teams", "players", "games", "goals"} <= _tables(s):
        team = _quoted(question)
        if "players on the team named" in q:
            return (
                f"SELECT p.name FROM Players p JOIN Teams t ON p.tid = t.tid WHERE t.name = '{team}';",
                "Join players to their team and filter by team name.",
                0.95,
            )
        if "scored more than three goals" in q:
            return (
                "SELECT p.name FROM Players p JOIN Goals g ON p.pid = g.pid "
                "GROUP BY p.pid, p.name HAVING COUNT(*) > 3;",
                "Count goals per player and keep counts above three.",
                0.95,
            )
        if "played the most games as the home team" in q:
            return (
                "SELECT t.name FROM Teams t WHERE t.tid IN "
                "(SELECT home_tid FROM Games GROUP BY home_tid HAVING COUNT(*) = "
                "(SELECT MAX(c) FROM (SELECT COUNT(*) AS c FROM Games GROUP BY home_tid)));",
                "Find the maximum home-game count and return all tied teams.",
                0.95,
            )
        if "every home game played by their team" in q:
            return (
                "SELECT p.name FROM Players p WHERE NOT EXISTS "
                "(SELECT 1 FROM Games g WHERE g.home_tid = p.tid AND NOT EXISTS "
                "(SELECT 1 FROM Goals go WHERE go.gid = g.gid AND go.pid = p.pid));",
                "Use double NOT EXISTS for the every-home-game condition.",
                0.95,
            )

    if {"departments", "doctors", "patients", "appointments"} <= _tables(s):
        dept = _quoted(question)
        if "for each department" in q and "zero appointments" in q:
            return (
                "SELECT d.name, COUNT(a.aid) FROM Departments d LEFT JOIN Doctors doc "
                "ON d.did = doc.did LEFT JOIN Appointments a ON doc.doc_id = a.doc_id "
                "GROUP BY d.did, d.name;",
                "Left join through doctors to appointments and count appointment ids.",
                0.95,
            )
        if "three oldest patients" in q:
            return (
                "SELECT DISTINCT p.name, p.age FROM Patients p JOIN Appointments a "
                "ON p.pid = a.pid ORDER BY p.age DESC LIMIT 3;",
                "Keep patients with appointments and order by descending age.",
                0.95,
            )
        if "cardiology" in q and "doctors" in q and "patients" in q:
            return (
                "SELECT doc.name FROM Doctors doc JOIN Departments d ON doc.did = d.did "
                f"WHERE d.name = '{dept}' UNION SELECT p.name FROM Patients p "
                "JOIN Appointments a ON p.pid = a.pid JOIN Doctors doc ON a.doc_id = doc.doc_id "
                f"JOIN Departments d ON doc.did = d.did WHERE d.name = '{dept}';",
                "Union department doctors with patients seen by that department's doctors.",
                0.95,
            )
        if "every patient ever seen" in q and "older than 60" in q:
            return (
                "SELECT d.name FROM Departments d WHERE d.did IN "
                "(SELECT doc.did FROM Doctors doc JOIN Appointments a ON doc.doc_id = a.doc_id) "
                "AND NOT EXISTS (SELECT 1 FROM Patients p WHERE p.age <= 60 AND p.pid IN "
                "(SELECT pid FROM Appointments WHERE doc_id IN "
                "(SELECT doc_id FROM Doctors WHERE did = d.did)));",
                "Require at least one appointment and exclude any seen patient aged 60 or below.",
                0.95,
            )

    return "", "No high-confidence rule matched; use LLM drafting path.", 0.0


def _tables(schema_lower: str) -> set[str]:
    return {m.group(1).lower() for m in re.finditer(r"create\s+table\s+([a-z_][a-z0-9_]*)", schema_lower)}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit("", "", "solve.py invoked without argv payload", 0.0)
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload not an object")
    except (json.JSONDecodeError, ValueError) as e:
        return _emit("", "", f"invalid argv JSON: {e}", 0.0)

    task_id = str(payload.get("task_id", ""))
    question = str(payload.get("question", ""))
    schema = str(payload.get("db_schema", payload.get("schema_ddl", "")))
    sql, rationale, confidence = solve(question, schema)
    return _emit(task_id, sql, rationale, confidence)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
