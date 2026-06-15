---
name: bug-hunter-uab0
description: Must run the Bug Hunter dispatcher to write AIASE_RESULT_PATH; only use bounded candidate review after a low-confidence clean result.
version: 0.4.2-hybrid
metadata:
  hermes:
    tags: [code, audit, aiase-2026]
    category: code
    requires_toolsets: [terminal]
---

# Bug Hunter Skill

## When to Use

Use when the input JSON contains `task_id`, `task_description`, and `code`, and the goal is to decide whether the code is buggy and report precise line-localized defects.

## Output Contract

- **Run the dispatcher first.**
- Only the result file at `AIASE_RESULT_PATH` is consumed. Chat text is ignored.
- **Do not review the code before the first dispatcher run.**
- **Do not place prose, plain JSON, YAML, tables, or Markdown fenced JSON in chat as the final answer.**
- **Send every candidate bug list back to the dispatcher before stopping.**
- Use reasoning only when fallback is allowed by the dispatcher result.

## Procedure

Follow this sequence exactly:

1. First, run the dispatcher on the exact original input using this heredoc form. Use the skill directory path provided by Hermes as `<skill_dir>`:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
<INPUT_JSON>
JSON
```

2. If the command fails and no result file is written, retry once using the same command pattern.

3. Stop if `verdict == "buggy"` or confidence is at least `0.75`.

4. Fallback is allowed only when `verdict == "clean"` and confidence is below `0.75`. Privately identify zero to three concrete spec-violating bugs. Do not report style issues, speculative bugs, or bugs without a concrete line range.

5. Send candidates back to the dispatcher:

```bash
python3 <skill_dir>/scripts/dispatch.py <<'JSON'
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

6. If no concrete bug is found, use `"candidate_bugs": []`; never keep the example object.

7. After the final dispatcher run writes the result file, stop.

## Pitfalls

- Do not bypass the dispatcher.
- Do not report style issues, speculative bugs, or bugs without a concrete line range.
- Line numbers are 1-indexed, and clean code requires `"bugs": []`.

## Verification

The result file JSON must contain `task_id`, `verdict`, `bugs`, and `confidence`. Each bug must contain `line_start`, `line_end`, `severity`, `type`, `description`, and `suggested_fix`. Line numbers are 1-indexed. `verdict == "clean"` requires `"bugs": []`.
