---
name: code-author-uab0
description: Must run the Code Author dispatcher to write AIASE_RESULT_PATH; never answer code directly in chat.
version: 0.3.1
metadata:
  hermes:
    tags: [code, python, aiase-2026]
    category: code
    requires_toolsets: [terminal]
---

# Code Author Skill

## When to Use

Use when the input JSON contains `task_id`, `task_description`, and `constraints`.

## Output Contract

- **Run the dispatcher first.**
- Only the result file at `AIASE_RESULT_PATH` is consumed. Chat text is ignored.
- **Do not place the final code, prose, plain JSON, YAML, tables, or Markdown fenced JSON in chat.**
- **Send every candidate code back to the dispatcher before stopping.**
- Use reasoning only when the dispatcher result fails self-tests or is low confidence.

## Procedure

Follow this sequence exactly:

1. First, run the dispatcher on the exact original input using this heredoc form. Use the skill directory path provided by Hermes as `<skill_dir>`:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

2. If the command fails and no result file is written, retry once using the same command pattern.

3. If `self_test_results.failed == 0` and confidence is at least `0.6`, stop.

4. Otherwise, write one simple implementation for `constraints.entry_function`. Candidate code must not use forbidden imports, filesystem/network/process calls, `eval`, or `exec`.

5. Send the candidate back to the dispatcher:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
{
  "task_id": "<same task_id>",
  "task_description": "<same task_description>",
  "constraints": <same constraints object>,
  "candidate_code": "<your Python source>"
}
JSON
```

6. After the final dispatcher run writes the result file, stop.

## Pitfalls

- Do not bypass the dispatcher.
- Do not use forbidden imports, filesystem/network/process calls, `eval`, or `exec`.
- Match `constraints.entry_function` exactly and keep code within the required size limit.

## Verification

The result file JSON must contain `task_id`, `code`, `loc`, `self_test_results`, `rationale`, and `confidence`.
