---
name: bug-hunter-uab0
description: Find Python bugs with a deterministic dispatcher first; use bounded LLM candidate-bug review only when the dispatcher is clean and low-confidence.
version: 0.4.1-hybrid
metadata:
  hermes:
    tags: [code, audit, aiase-2026]
    category: code
---

# Bug Hunter Skill

## When to Use

Use when the input JSON contains `task_id`, `task_description`, and `code`, and the goal is to decide whether the code is buggy and report precise line-localized defects.

## Procedure

Do not review the code before the first tool call.

Run the dispatcher:

```bash
python skills/bug-hunter-uab0/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

If the dispatcher output has `verdict: "buggy"` or `confidence >= 0.75`, return that fenced JSON block verbatim and stop.

Only if the dispatcher output has both `verdict: "clean"` and `confidence < 0.75`, privately inspect the task description and code. Identify zero to three concrete bugs that violate the specification.

Submit the fallback review to the dispatcher:

```bash
python skills/bug-hunter-uab0/scripts/dispatch.py <<'JSON'
{
  "original": <INPUT_JSON>,
  "mode": "hybrid",
  "candidate_bugs": [
    {
      "line_start": 1,
      "line_end": 1,
      "severity": "high",
      "type": "logic_error",
      "description": "Replace this example with a concrete bug, or use an empty list when the code is clean.",
      "suggested_fix": "Replace this example with a concrete fix direction."
    }
  ]
}
JSON
```

If you find no concrete bug, set `"candidate_bugs": []`. Never keep the example object.

Return only the final dispatcher's fenced JSON block. Do not add prose.

## Verification

The final answer must be the single fenced JSON block printed by the dispatcher. It must contain `task_id`, `verdict`, `bugs`, and `confidence`. Each bug must use an allowed `severity` and `type`, and line numbers must be 1-indexed.
