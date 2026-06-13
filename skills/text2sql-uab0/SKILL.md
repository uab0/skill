---
name: text2sql-uab0
description: Convert a natural-language question + SQLite schema into a verified read-only SQL query. AIASE 2026 Basic Track.
version: 0.3.0
metadata:
  hermes:
    tags: [sql, text2sql, data, aiase-2026]
    category: data
---

# Text2SQL Skill

## When to Use

Use when the input JSON contains `task_id`, `question`, `db_schema`, and optionally `dialect`.

## Procedure

Run the dispatcher first:

```bash
python skills/text2sql-uab0/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

If the returned fenced JSON has non-empty `sql` and `confidence >= 0.85`, return it unchanged.

If `sql` is empty or confidence is low, use the question and schema to draft one SQLite read-only `SELECT` query, then validate and format it by running:

```bash
python skills/text2sql-uab0/scripts/dispatch.py <<'JSON'
{"task_id":"<same task_id>","question":"<same question>","db_schema":"<same db_schema>","candidate_sql":"<your SQL>"}
JSON
```

Return only the final Markdown fenced ```json``` block printed by `dispatch.py`. Do not add prose, tables, YAML, or another fenced block.

## Verification

The final JSON object must contain `task_id`, `sql`, `rationale`, and `confidence`.
