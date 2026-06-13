---
name: code-author-uab0
description: Implement a Python function from a natural-language task description, self-test it, and emit the AIASE 2026 Pairwise Code Author contract.
version: 0.3.0
metadata:
  hermes:
    tags: [code, python, aiase-2026]
    category: code
---

# Code Author Skill

## When to Use

Use when the input JSON contains `task_id`, `task_description`, and `constraints`.

## Procedure

Run the dispatcher first:

```bash
python skills/code-author-uab0/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

If the returned fenced JSON has `self_test_results.failed == 0` and `confidence >= 0.6`, return it unchanged.

If confidence is low or tests failed, write a simple Python implementation for `constraints.entry_function`, then validate and format it by running:

```bash
python skills/code-author-uab0/scripts/dispatch.py <<'JSON'
{"task_id":"<same task_id>","task_description":"<same task_description>","constraints":<same constraints object>,"candidate_code":"<your Python source>"}
JSON
```

Do not use forbidden imports, filesystem/network/process calls, `eval`, or `exec` in candidate code.

Return only the final Markdown fenced ```json``` block printed by `dispatch.py`. Do not add prose, tables, YAML, or another fenced block.

## Verification

The final JSON object must contain `task_id`, `code`, `loc`, `self_test_results`, `rationale`, and `confidence`.
