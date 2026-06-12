---
name: bug-hunter-uab0
description: Audit a Python function for bugs against its task description, emit a structured bug report per the AIASE 2026 Pairwise Bug Hunter contract.
version: 0.2.0
metadata:
  hermes:
    tags: [code, audit, aiase-2026]
    category: code
---

# Bug Hunter Skill (Pairwise Track)

## When to Use

Use this skill when the input JSON contains `task_id`, `code`, and `task_description`. The skill must return a structured bug report with precise line numbers and low false-positive rate.

## Procedure

1. Parse `task_id`, `code`, and `task_description`.
2. Read the input `code` line-by-line. Line numbers are 1-indexed, and blank/comment lines count.
3. Run deterministic analysis from the repo root:

```bash
python skills/bug-hunter-uab0/scripts/analyze.py '{"task_id":"<task_id>","code":"<code>","task_description":"<task description>"}'
```

4. Review the analyzer evidence:
   - parse/compile status;
   - entry function status;
   - forbidden import or dangerous construct findings;
   - reproducible crashes, mismatches, or timeouts;
   - traceback-localized candidate lines;
   - suspicious AST lines.
5. Report `buggy` only when there is clear evidence:
   - compile/import failure;
   - forbidden or dangerous construct;
   - reproducible crash;
   - reproducible mismatch against a provided/reference oracle;
   - timeout on a small deterministic probe;
   - clear AST-localized spec violation.
6. If evidence is weak or only stylistic, prefer `verdict="clean"` and `bugs=[]`.
7. For each bug, choose:
   - the smallest relevant `line_start`/`line_end`;
   - one allowed `type`;
   - calibrated `severity`;
   - a specific description and suggested fix.
8. Final action: run this exact command from the repo root and return its Markdown fenced JSON block unchanged:

```bash
python skills/bug-hunter-uab0/scripts/run.py '{"task_id":"<same task_id>","verdict":"clean","bugs":[],"confidence":0.0}'
```

Paste the wrapper output exactly, including the opening ```json fence and closing ``` fence. Do not answer in a special JSON channel, plain JSON object, prose, table, or YAML.

## Pitfalls

- False positives on clean code are penalized. Do not report speculative bugs.
- Do not point at the function signature when a specific loop/index/return line causes the issue.
- Empty-input crashes are usually `edge_case` with `medium` severity.
- Common-input wrong answers are usually `logic_error` or `off_by_one` with `high` severity.
- Style-only or theoretical performance concerns should usually be `clean`, unless the task explicitly requires performance and the code likely times out.
- If `verdict=clean`, `bugs` must be `[]`.

## Verification

The final output must be the single last Markdown fenced ```json``` block printed by `scripts/run.py`, with:

- `task_id`
- `verdict`, either `"buggy"` or `"clean"`
- `bugs`, empty when clean
- `confidence`

Each bug object must contain `line_start`, `line_end`, `severity`, `type`, `description`, and `suggested_fix`.

Do not add any reasoning or another fenced JSON block after the final contract.
