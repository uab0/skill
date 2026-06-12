---
name: code-author-uab0
description: Implement a Python function from a natural-language task description, self-test, and emit the AIASE 2026 Pairwise Code Author contract.
version: 0.2.0
metadata:
  hermes:
    tags: [code, python, aiase-2026]
    category: code
---

# Code Author Skill (Pairwise Track)

## When to Use

Use this skill when the input JSON contains `task_id`, `task_description`, and `constraints` with `entry_function`, `max_loc`, and `imports_forbidden`.

The skill must return Python source code defining exactly the requested entry function. Code Author score depends on hidden tests for the returned code.

## Procedure

1. Parse `task_id`, `task_description`, and `constraints`.
2. Identify the exact function name, inputs, output behavior, invalid/empty cases, boundary cases, and complexity requirements.
3. First try the deterministic author helper. Run this exact command from the repo root with the original input JSON:

```bash
python skills/code-author-uab0/scripts/author.py '{"task_id":"<task_id>","task_description":"<task description>","constraints":{...}}'
```

4. If `author.py` returns `confidence >= 0.6` and `self_test_results.failed == 0`, use that output as the final answer unchanged. Paste the helper output exactly, including the opening ```json fence and closing ``` fence. Do not answer in a special JSON channel, plain JSON object, prose, table, or YAML.
5. Only if `author.py` is low-confidence or failed, draft simple Python source code yourself:
   - define the exact `constraints.entry_function`;
   - output code only in the `code` string, not Markdown;
   - avoid imports unless clearly allowed and necessary;
   - do not use network, filesystem dependency, dynamic import, `eval`, `exec`, `subprocess`, multiprocessing, or threading;
   - keep code below `constraints.max_loc`.
6. Build a compact `sample_inputs` array with expected outputs. Include task-specific edge cases, not only happy paths.
   - Preferred sample format: `{"input": [[1, 2, 3], 2], "expected": 1}` where `input` is the positional argument list for the function.
   - The self-test also accepts `{"args": [...], "expected": ...}` and simple `{"input": [...], "target": x, "expected": ...}`, but prefer the positional `input` format.
7. Self-test by running this exact command from the repo root:

```bash
python skills/code-author-uab0/scripts/selftest.py '{"code":"<candidate code>","task_description":"<task description>","constraints":{...},"sample_inputs":[...]}'
```

8. If self-test reports failed cases, syntax/entry errors, import/security violations, or `loc_violation=true`, fix the code and retry at most 2 rounds.
9. Final action: run this exact command from the repo root and return its Markdown fenced JSON block unchanged:

```bash
python skills/code-author-uab0/scripts/run.py '{"task_id":"<same task_id>","code":"<final code>","loc":0,"self_test_results":{...},"rationale":"<brief design and edge cases>","confidence":0.0}'
```

Paste the wrapper output exactly, including the opening ```json fence and closing ``` fence. Do not answer in a special JSON channel, plain JSON object, prose, table, or YAML.

## Pitfalls

- Missing empty-input handling is common. Test `[]`, `""`, `0`, or invalid bounds when relevant.
- Off-by-one errors are common. Test first, last, singleton, and just-outside-bound cases.
- Preserve duplicates unless the task says to deduplicate.
- Do not use forbidden convenience imports such as `csv`, `os`, `sys`, or `subprocess`.
- For parser tasks, test empty fields, quoted delimiters, and escaped characters.
- For dynamic programming tasks, test 0/1 dimensions and small hand-computable cases.
- Keep rationale truthful: mention actual algorithm and actual edge handling.

## Verification

The final output must be the single last Markdown fenced ```json``` block printed by `scripts/run.py`, with:

- `task_id`
- `code`
- `loc`
- `self_test_results` including `passed` and `failed`
- `rationale`
- `confidence`

Do not add any reasoning or another fenced JSON block after the final contract.
