---
name: bug-hunter-uab0
description: Run the bug-hunter dispatcher script and return its fenced JSON contract verbatim. Do not audit manually.
version: 0.3.1
metadata:
  hermes:
    tags: [code, audit, aiase-2026]
    category: code
---

# Bug Hunter Skill

## When to Use

Use when the input JSON contains `task_id`, `task_description`, and `code`.

## Procedure

Manual review is invalid for this skill. Do not explain bugs yourself, do not provide corrected code, and do not answer in prose.

Run the dispatcher exactly once:

```bash
python skills/bug-hunter-uab0/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

Copy the dispatcher's stdout verbatim as the final answer. Do not inspect, summarize, repair, rewrite, or add prose. Do not run any other command.

## Verification

The final JSON object must contain `task_id`, `verdict`, `bugs`, and `confidence`.
