---
name: text2sql-uab0
description: Must run the Text2SQL dispatcher to write AIASE_RESULT_PATH; never answer SQL directly in chat.
version: 0.3.1
metadata:
  hermes:
    tags: [sql, text2sql, data, aiase-2026]
    category: data
    requires_toolsets: [terminal]
---

# Text2SQL Skill

## When to Use

Use when the input JSON contains `task_id`, `question`, `db_schema`, and optionally `dialect`.

## Output Contract

- **Run the dispatcher first.**
- Only the result file at `AIASE_RESULT_PATH` is consumed. Chat text is ignored.
- **Do not place the final SQL, prose, plain JSON, YAML, tables, or Markdown fenced JSON in chat.**
- **Send every candidate SQL back to the dispatcher before stopping.**
- Use reasoning only when the dispatcher result is missing, empty, or low confidence.

## Procedure

Follow this sequence exactly:

1. First, run the dispatcher on the exact original input using this heredoc form. Use the skill directory path provided by Hermes as `<skill_dir>`:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

2. If the command fails and no result file is written, retry once using the same command pattern.

3. If the result file has non-empty `sql` and confidence is at least `0.85`, stop.

4. Otherwise, draft exactly one SQLite read-only `SELECT` query from the original `question` and `db_schema`, then send it back to the dispatcher:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
{
  "task_id": "<same task_id>",
  "question": "<same question>",
  "db_schema": "<same db_schema>",
  "candidate_sql": "<your SQL>"
}
JSON
```

5. After the final dispatcher run writes the result file, stop.

## Pitfalls

- Do not bypass the dispatcher.
- Do not invent tables, columns, values, or SQLite functions not supported by the schema and dialect.
- SQL must be a single read-only SQLite query.

## Verification

The result file JSON must contain `task_id`, `sql`, `rationale`, and `confidence`. SQL must be a single read-only SQLite query.
