# 期末報告 — AIASE 2026 Final Project

學生：劉宇昕  
GitHub：`uab0`

## 1. 設計決策

### 1.1 Basic — `text2sql-uab0`

Basic 採用 dispatcher-first 架構。Hermes 載入 skill 後，`SKILL.md` 要求模型先執行 `scripts/dispatch.py`，由 scripts 產生或驗證 SQL，再透過 `scripts/run.py` 寫入 `AIASE_RESULT_PATH`。選擇 scripts 優先，是希望即使評分模型較小、工具遵循能力較弱，也能把格式、驗證與輸出流程固定住。`run.py` 同時支援 JSON payload 與 argparse flags，避免正式或除錯流程直接呼叫 `run.py` 時介面不一致。

這樣設計是為了讓格式、read-only SQL、欄位存在性、SQLite 語法等確定性要求交給程式處理。若 deterministic solver 低信心，模型只補一個 candidate SQL，仍須回到 dispatcher 檢查。近期也加入 count 類 perturbation guard，避免「列出名字」的 rule 在 hidden 題改成「how many / count」時仍高信心硬回舊查詢。

### 1.2 Pairwise — `code-author-uab0` 與 `bug-hunter-uab0`

Code Author 由 dispatcher 產生保守實作並做 self-test，輸出 `code`、`loc`、`self_test_results`、`rationale`、`confidence`。對已知 reference family，scripts 能快速產生可通過邊界測試的實作；對未知 family，模型仍可產生 candidate code，但必須交回 dispatcher 檢查 forbidden imports、entry function、S-LOC 與 sample/edge tests。

Bug Hunter 採 evidence-gated 設計。scripts 先做 AST 檢查與 probe，再把 evidence 轉成 line-localized bug report。這個設計刻意降低 false positive：沒有可重現 evidence 時維持 clean；有 evidence 時才報具體 line、type、description、suggested_fix。若 deterministic 結果低信心，LLM 可補 bounded candidate bugs，但最後仍由 dispatcher sanitize 並寫 result file。

### 1.3 Open Track — `open-stat-analyst-uab0`

Open Track 是可驗證的統計分析 skill。輸入自然語言問題與 JSON rows，支援描述統計、Pearson correlation、一元線性迴歸、two-proportion z test、group aggregate。選這個題目是因為它和統計與資料科學直接相關，且 ground truth 可由評分輸入資料重算。

此 track 不依賴外部套件，只用 Python standard library。LLM 只在低信心語意判斷時提供 bounded `candidate_plan`；最後欄位檢查、missing value 處理、數值計算與 file-based contract 都由 scripts 控制。另提供 `scripts/evaluate.py` 自動化比對器，可依 result 中的欄位角色回到原始資料重算 ground truth，也會檢查不支援方法不可偽造數值結果。metric 因此可抗 perturbation：改 task_id、重排 rows、加入無關欄位、同義詞與 selected-column missing values 都應可驗證。

## 2. 實際遭遇之失敗與分析

### 失敗 1 — SKILL.md 步驟太自由，模型在工具選擇與格式化上消耗時間

- 觸發場景: Basic 初期流程讓模型自行理解 schema、草稿 SQL、驗證、重試與輸出格式；即使 deterministic solver 已能快速產生正確 SQL，Hermes batch 仍可能卡在模型/tool orchestration。
- log 片段:
  ```text
  total: 21  passed: 18  rate: 85.7%
  task_nl2sql_005  hermes timed out after 120s
  task_nl2sql_013  hermes timed out after 120s
  task_nl2sql_020  hermes timed out after 120s
  ```
- 成因分析: 瓶頸不是 SQL 執行，而是模型被要求同時負責推理、工具選擇、驗證分支與最後 contract。小模型或較不穩定的模型容易在這些步驟中猶豫或重試，導致沒有產出結果。
- 修正方式: 將流程改成 dispatcher-first：先跑 `scripts/dispatch.py`；高信心就停止；低信心時模型只補一次 candidate SQL，且 candidate 必須交回 dispatcher 驗證後由 `run.py` 寫結果檔。
- MAST 分類: (2) agent 間協調、(3) 驗證與品質。

### 失敗 2 — Bug Hunter 有 probe evidence，但模型無法穩定轉成正確行號與 bug type

- 觸發場景: Bug Hunter 初版已能用 probes 發現輸出錯誤，但將 evidence 轉成評分需要的 `line_start` / `type` 時不穩定。
- log 片段:
  ```text
  total: 5  passed: 1  rate: 20.0%
  direct dispatcher on task_pair_004:
    got      (6, logic_error), (6, edge_case)
    expected (5, logic_error), (2, edge_case)
  ```
- 成因分析: Probe failure 只能證明程式輸出錯或 crash，常指向 return line、traceback line 或下游錯誤，不一定是 root cause line。若讓模型自由解讀 evidence，它可能說得合理，但行號與 bug type 不符合 pairwise metric。
- 修正方式: 在 dispatcher 中加入 task-family static checks，把 failing probe、AST/字串結構與題型規格合併判斷，直接產生 contract-shaped bugs；模型只在低信心或未知 family 時補 bounded candidate bugs。
- MAST 分類: (3) 驗證與品質。

### 失敗 3 — Shell quoting 讓 code payload 被破壞，模型無法把正確輸入交給 script

- 觸發場景: Bug Hunter 測 `parse_csv_line` 時，輸入 code 內含單引號，例如 `cur = ''`。早期 SKILL 範例把整個 JSON 放在 shell 單引號裡，模型照抄後破壞 payload。
- log 片段:
  ```text
  direct dispatcher: line_start=5, type=unhandled_input
  Hermes smoke: syntax error: invalid syntax (<unknown>, line 3)
  observed truncated line: cur =
  ```
- 成因分析: 模型不是看不懂 CSV，而是 shell 參數傳遞方式太脆弱；JSON 裡的 Python code 含 quote/newline 時，payload 在進 dispatcher 前就已經變形。
- 修正方式: dispatcher 支援 stdin 與 `@file`；`SKILL.md` 改用 single-quoted heredoc delimiter：`<<'JSON'`，讓 code、schema、task description 的 quote 與換行能原樣傳入。
- MAST 分類: (2) agent 間協調、(3) 驗證與品質。

### 失敗 4 — 給 LLM 更多自由，沒有改善 hidden-like bug hunting，反而讓 contract 更不穩

- 觸發場景: 曾比較「讓 LLM 多想、多主導 bug hunting」是否能補 scripts 沒寫到的情況，包括 LLM-heavy、candidate-only 與 hybrid 流程。
- log 片段:
  ```text
  pre-fix baseline: 0/5
  LLM-heavy variant: 0/5
  candidate-only: task_pair_001-task_pair_004 timed out after 120s; task_pair_005 contract violation
  hybrid: all five tasks timed out after 120s
  ```
- 成因分析: 多步自然語言流程讓模型在「要不要 review、如何引用 evidence、是否再跑 tool、如何輸出 contract」之間變得更不穩；更多推理不一定提升泛化，反而放大 timeout 與 contract violation。
- 修正方式: 採用 script-controlled protocol。已知 family 走 deterministic fast path；低信心或未知情境才允許 bounded fallback；所有 candidate 都必須回 dispatcher sanitize，再由 `run.py` 寫結果檔。
- MAST 分類: (2) agent 間協調、(3) 驗證與品質。

## 3. 改進方向

- Basic 可加入更多 schema-grounded lint，例如 DISTINCT、NULL、NOT IN/NOT EXISTS、aggregation granularity 的風險提示；但 warning 不應直接當 hard failure，以免誤殺正確 SQL。
- Bug Hunter 可把未知 family 的 fallback 做得更 script-controlled，例如由 script 產生 probe summary，再要求 LLM 只回 bounded candidate bugs，避免自由 review 流程超時。
- Open Track 可增加小型多步能力，例如 group aggregate 後取 top group 或先分組再比較比例；同時擴充 `evaluate.py` 與 perturbation tests，維持可自動評分。
- 本地測試可更完整保存 Hermes session id、elapsed time、result path、重打次數，讓 external provider failure 與 skill design failure 更容易分開。

## 4. 引用說明

- Python standard library：`statistics`、`math.erf` 用於 Open Track 統計計算。
- ChatGPT：協助整理、程式修改與文字草稿。
- 只參考概念、未複製 public code：LIDA / Data-Copilot / InfiAgent-DABench 等資料分析 agent 評測想法，主要借用「LLM 產生中間計畫，工具負責執行與驗證」的設計原則。

## 5. 最終自測摘要

註：`pytest` 並未寫入課程評分標準，而是本 repo 的本地 regression tests。因課程規則中途改為 file-based output，加上官方提供之改版後 `run_dev.py` 與其需求檔案結構存在差異，因此本 repo 另加入 result-file contract、dispatcher 與邊界案例測試；`run_dev.py` 保留本地測試 helper，但核心結果讀取與 Basic 比對仍使用 `aiase_contract.py`。若直接置換為其他版本的 `run_dev.py`，`pytest` 結果可能不同；以下僅作為本地驗證參考。

- `pytest -q`：`224 passed, 1 skipped`。
- `python verify_repo.py --github-id uab0`：`31/31 passed`。
- `python run_dev.py --check-only`：Basic dev DB 與 Pairwise reference tasks 檢查通過，`0 issue(s)`。
- Basic Hermes batch：`21/21`。
- Pairwise Code Author：`5/5`。
- Pairwise Bug Hunter：`5/5`。
- Open Track：`9/9`。
