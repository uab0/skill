---
name: open-stat-analyst-uab0
description: Must run the statistics dispatcher to write AIASE_RESULT_PATH; never compute final statistics directly in chat.
version: 0.1.0
metadata:
  hermes:
    tags: [statistics, data, analysis, aiase-2026]
    category: data
    requires_toolsets: [terminal]
---

# Open Stat Analyst Skill

## When to Use

Use when the input JSON contains `task_id`, `question`, and `data`, where `data` is a list of JSON row objects. The skill supports bounded statistical analysis: descriptive statistics, Pearson correlation, simple linear regression, two-proportion z tests, and grouped aggregates.

## Output Contract

- **Run the dispatcher first.**
- Only the result file at `AIASE_RESULT_PATH` is consumed. Chat text is ignored.
- **Do not compute final statistics in chat.**
- **Do not place prose, plain JSON, YAML, tables, or Markdown fenced JSON as the final answer.**
- **Send every candidate plan back to the dispatcher before stopping.**
- Use reasoning only when the dispatcher asks for or permits a bounded candidate plan.

## Procedure

Follow this sequence exactly:

1. First, run the dispatcher on the exact original input using this heredoc form. Use the skill directory path provided by Hermes as `<skill_dir>`:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

2. If the command fails and no result file is written, retry once using the same command pattern.

3. If the result is not `decision: "needs_plan"` and confidence is at least `0.75`, stop.

4. Otherwise, privately infer one bounded `candidate_plan`. The plan may only contain:

- `analysis_type`: one of `descriptive_stats`, `correlation`, `linear_regression`, `two_proportion_z`, `group_aggregate`.
- `columns`: a JSON object mapping roles to existing column names.
- `options`: optional settings such as `alpha` or `aggregations`.

5. Send the candidate plan back to the dispatcher:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
{
  "original": <INPUT_JSON>,
  "candidate_plan": {
    "analysis_type": "descriptive_stats",
    "columns": {
      "value": "replace_with_existing_column"
    },
    "options": {}
  }
}
JSON
```

6. After the final dispatcher run writes the result file, stop.

## Pitfalls

- Do not bypass the dispatcher.
- Do not invent columns, analysis types, or unsupported statistical tests.
- The dispatcher and scripts compute final numeric results; candidate plans only choose supported roles and options.

## Verification

The result file JSON must contain `task_id`, `analysis_type`, `columns`, `result`, `decision`, `warnings`, and `confidence`.
