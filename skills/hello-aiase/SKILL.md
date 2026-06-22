---
name: hello-aiase
description: Minimal warm-up skill. Reads a name from the input JSON and writes a greeting result file (file-based output contract).
version: 2.0.0
metadata:
  hermes:
    tags: [hello, aiase, warmup]
    category: aiase
    requires_toolsets: [terminal]
---

# hello-aiase (file-based output contract)

最小範例：示範「skill 由 `scripts/run.py` 把結果寫到結果檔」的輸出契約。

## When to Use
當使用者輸入 `/hello-aiase {json}` 時觸發。輸入形如 `{"task_id":"...","name":"Ada"}`。

## Procedure
1. 從輸入 JSON 取得 `task_id` 與 `name`。
2. **使用 `terminal` 工具（不要用 process/background 工具）**，以**絕對路徑**執行
   （`<skill_dir>` 由 Hermes 以 `[Skill directory: ...]` 提供）：
   ```
   python3 <skill_dir>/scripts/run.py --task_id "<task_id>" --name "<name>"
   ```
3. 執行 `scripts/run.py` 把最終結果寫入結果檔（路徑取自環境變數 `AIASE_RESULT_PATH`，
   未設定則寫工作目錄 `./aiase_result.json`）。**你不需要在對話訊息中再輸出或複述 JSON。**

## Verification
結果檔存在、為合法 JSON object、含 `task_id` / `greeting` / `ok`。
