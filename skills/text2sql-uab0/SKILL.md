---
name: text2sql-uab0
description: Convert a natural-language question + SQLite schema into a verified read-only SQL query. AIASE 2026 Basic Track.
version: 0.2.0
metadata:
  hermes:
    tags: [sql, text2sql, data, aiase-2026]
    category: data
---

# Text2SQL Skill (Basic Track)

## When to Use

Use this skill when the input JSON contains a natural-language `question`, a SQLite schema DDL string in `db_schema`, and usually `task_id` plus `dialect`.

The skill must output one SQLite read-only query in the Basic Track JSON contract. The grader compares result rows by bag equality: row order does not matter, but duplicate row counts and selected column order do matter.

## Procedure

1. Parse the input JSON. Extract `task_id`, `question`, `db_schema`, and `dialect`.
2. First try the deterministic solver. Run this exact command from the repo root with the original input JSON:

```bash
python skills/text2sql-uab0/scripts/solve.py '{"task_id":"<task_id>","question":"<question>","db_schema":"<schema ddl>","dialect":"sqlite"}'
```

3. If `solve.py` returns `confidence >= 0.85` and non-empty `sql`, use that Markdown fenced JSON block as the final answer unchanged. Paste the helper output exactly, including the opening ```json fence and closing ``` fence. Do not answer in a special JSON channel, plain JSON object, prose, table, or YAML.
4. Only if `solve.py` is low-confidence or empty, ground the question in the schema before writing SQL:
   - identify relevant tables and columns;
   - identify likely join keys and join path;
   - identify filters, aggregations, grouping, sorting, limits, set operations, and whether duplicates should be removed.
5. Draft exactly one SQLite read-only SQL query.
6. Validate the draft by running this exact command from the repo root:

```bash
python skills/text2sql-uab0/scripts/validate_sql.py '{"db_schema":"<schema ddl>","sql":"<draft sql>"}'
```

7. If validation returns `ok=false`, fix the SQL using the returned `error`. Retry at most 2 validation rounds.
8. Treat validation `warnings` as semantic risk hints, not hard failures. Revise if the warning clearly applies to the question.
9. Final action: run this exact command from the repo root and return its Markdown fenced JSON block unchanged:

```bash
python skills/text2sql-uab0/scripts/run.py '{"task_id":"<same task_id>","sql":"<final sql>","rationale":"<brief reason>","confidence":0.0}'
```

Paste the wrapper output exactly, including the opening ```json fence and closing ``` fence. Do not answer in a special JSON channel, plain JSON object, prose, table, or YAML.

## Pitfalls

- Use SQLite only.
- Do not use CTE / `WITH`, window functions, recursive queries, DDL/DML, `PRAGMA`, or non-SQLite syntax.
- Output exactly one statement. A trailing semicolon is okay, but semicolon-separated statements are not.
- Many-to-many or one-to-many joins may require `DISTINCT` when the question asks for unique names/titles/entities.
- In `LEFT JOIN` tasks, filtering the right table in `WHERE` can accidentally remove zero-match rows.
- With `LEFT JOIN`, `COUNT(*)` may count the preserved parent row; use `COUNT(child_id)` when zero children should count as 0.
- Tie questions such as "if multiple tie, return all" usually need a subquery comparing to `MAX`/`MIN`, not plain `LIMIT 1`.
- For "every", "none", and "all" conditions, consider `NOT EXISTS`.
- Column names/aliases are ignored by the grader, but selected column order is not.
- The output `task_id` must exactly match the input `task_id`.

## Verification

The final output must be the single last Markdown fenced ```json``` block printed by `scripts/run.py`, with:

- `task_id`
- `sql`
- `rationale`
- `confidence`

Do not add any reasoning or another fenced JSON block after the final contract.
