## 1. Skill 簡介

`open-stat-analyst-uab0` 是一個**可驗證的統計分析 skill**。輸入自然語言問題與小型 JSON 表格資料後，它會選擇受限的統計分析類型，再由 `scripts/` 用 Python 標準函式庫計算最後數值。

因為評分環境不保證能安裝 wheel cache 外的第三方套件，本 skill 不引入 `scipy`、`pandas` 等外部依賴；統計分析也因此限定在可用 Python standard library 穩定重算的五種：

- `descriptive_stats`：count、mean、median、sample stdev、min、max、quartiles、IQR。
- `correlation`：Pearson correlation。
- `linear_regression`：一元線性迴歸的 slope、intercept、R-squared。
- `two_proportion_z`：A/B conversion 或 success rate 的 two-proportion z test。
- `group_aggregate`：依群組計算 count、sum、mean、median、min、max。

設計上讓 LLM 只在低信心時提出 bounded `candidate_plan`；最後數字一定由 scripts 驗證欄位、驗證分析類型並計算，避免自由文字分析無法評分。

## 2. Skill 名稱與目錄

Slash command:

```text
/open-stat-analyst-uab0
```

Skill directory:

```text
skills/open-stat-analyst-uab0/
```

主要檔案：

```text
skills/open-stat-analyst-uab0/SKILL.md
skills/open-stat-analyst-uab0/scripts/dispatch.py
skills/open-stat-analyst-uab0/scripts/compute.py
skills/open-stat-analyst-uab0/scripts/evaluate.py
skills/open-stat-analyst-uab0/scripts/run.py
```

不需要外部套件、網路、API key、私有資料或本機絕對路徑。資料由評分輸入 JSON 提供。

## 3. 呼叫方式

正式呼叫方式：

```bash
hermes chat --toolsets skills,terminal --yolo -Q -q '/open-stat-analyst-uab0 {"task_id":"open_stat_desc_001","question":"Summarize the distribution of customer spend. Include mean, median, standard deviation, quartiles, and IQR.","data":[{"customer_id":"c1","spend":12.0},{"customer_id":"c2","spend":18.0},{"customer_id":"c3","spend":19.0},{"customer_id":"c4","spend":21.0},{"customer_id":"c5","spend":30.0}]}'
```

skill 會把正式結果寫到 `AIASE_RESULT_PATH`；若未設定，寫到 `./aiase_result.json`。對話文字不作為正式輸出。`scripts/run.py` 同時支援 dispatcher 使用的 JSON payload，以及老師範本形式的 argparse flags，避免直接呼叫 `run.py` 時因介面不一致而失敗。

自動化比對方式：

```bash
python3 skills/open-stat-analyst-uab0/scripts/evaluate.py --input scenario.json --result result.json
```

`evaluate.py` 會讀入同一份 scenario 與 skill 產生的 result file，依 result 中的 `analysis_type` 與 `columns` 回到輸入資料重算 ground truth；也可用 `--expected expected.json` 加上子集合式預期檢查。

輸入 JSON schema：

```json
{
  "task_id": "string",
  "question": "string",
  "data": [
    {
      "column_name": "number|string|boolean|null"
    }
  ],
  "candidate_plan": {
    "analysis_type": "optional string",
    "columns": "optional object",
    "options": "optional object"
  }
}
```

`candidate_plan` 是選填，只用於低信心 fallback。即使有 `candidate_plan`，dispatcher 仍會檢查 analysis type 是否支援、欄位是否存在。

結果檔 JSON schema：

```json
{
  "task_id": "open_stat_desc_001",
  "analysis_type": "descriptive_stats",
  "columns": {
    "value": "spend"
  },
  "result": {
    "count": 5,
    "mean": 20.0,
    "median": 19.0,
    "stdev": 6.519202405202649,
    "min": 12.0,
    "max": 30.0,
    "q1": 18.0,
    "q3": 21.0,
    "iqr": 3.0
  },
  "decision": "computed",
  "warnings": [],
  "confidence": 0.78
}
```

必要欄位：`task_id`、`analysis_type`、`columns`、`result`、`decision`、`warnings`、`confidence`。

## 4. 自定 Verifiable Scenario

Scenario：給定 JSON 表格與自然語言統計問題，skill 必須選出正確分析類型、欄位角色，並計算可重算的數值結果。評分器可用同一批輸入資料重新計算 ground truth，因此 metric 不依賴人工判讀。

### Public scenarios

Scenario 1：描述統計 + 無關欄位

```json
{
  "task_id": "open_stat_desc_001",
  "question": "Summarize the distribution of customer spend. Include mean, median, standard deviation, quartiles, and IQR.",
  "data": [
    {"customer_id": "c1", "spend": 12.0, "noise": "x"},
    {"customer_id": "c2", "spend": 18.0, "noise": "x"},
    {"customer_id": "c3", "spend": 19.0, "noise": "x"},
    {"customer_id": "c4", "spend": 21.0, "noise": "x"},
    {"customer_id": "c5", "spend": 30.0, "noise": "x"}
  ]
}
```

預期：`analysis_type = "descriptive_stats"`，`columns.value = "spend"`。

Scenario 2：線性迴歸

```json
{
  "task_id": "open_stat_reg_001",
  "question": "Fit a simple linear regression predicting sales from ad_spend. Return slope, intercept, and R squared.",
  "data": [
    {"ad_spend": 1.0, "sales": 3.0},
    {"ad_spend": 2.0, "sales": 5.0},
    {"ad_spend": 3.0, "sales": 7.0},
    {"ad_spend": 4.0, "sales": 9.0}
  ]
}
```

預期：predictor `ad_spend`、response `sales`、slope `2.0`、intercept `1.0`、R-squared `1.0`。

Scenario 3：A/B two-proportion z test

```json
{
  "task_id": "open_stat_ab_001",
  "question": "Compare the conversion rate between control and treatment. Is the treatment significantly different at alpha 0.05?",
  "data": [
    {"group": "control", "converted": 0},
    {"group": "control", "converted": 1},
    {"group": "control", "converted": 0},
    {"group": "control", "converted": 1},
    {"group": "treatment", "converted": 1},
    {"group": "treatment", "converted": 1},
    {"group": "treatment", "converted": 1},
    {"group": "treatment", "converted": 0}
  ]
}
```

預期：輸出兩組樣本數、成功數、rate、difference、pooled proportion、z statistic、p-value、decision。

Scenario 4：group aggregate，輸入列順序可變

```json
{
  "task_id": "open_stat_group_001",
  "question": "For each sales channel, compute the mean revenue and the number of rows.",
  "data": [
    {"channel": "search", "revenue": 30.0},
    {"channel": "email", "revenue": 14.0},
    {"channel": "search", "revenue": 20.0},
    {"channel": "email", "revenue": 10.0}
  ]
}
```

預期：依 `channel` 分組，對 `revenue` 算 `count` 與 `mean`；結果以 group key 比對，不看輸入順序。

Scenario 5：遺失值處理

```json
{
  "task_id": "open_stat_missing_001",
  "question": "Summarize the distribution of customer spend. Include mean and median.",
  "data": [
    {"customer_id": "c1", "spend": 10.0},
    {"customer_id": "c2", "spend": null},
    {"customer_id": "c3"},
    {"customer_id": "c4", "spend": 20.0}
  ]
}
```

預期：只保留可用 selected values，`count = 2`、`mean = 15.0`，並在 `warnings` 說明 dropped rows。

Scenario 6：低信心問題 + LLM bounded candidate plan

```json
{
  "task_id": "open_stat_candidate_001",
  "question": "Can you inspect these two measurements?",
  "data": [
    {"a": 1.0, "b": 2.0},
    {"a": 2.0, "b": 4.0},
    {"a": 3.0, "b": 6.0}
  ],
  "candidate_plan": {
    "analysis_type": "correlation",
    "columns": {"x": "a", "y": "b"},
    "options": {}
  }
}
```

預期：dispatcher 驗證 candidate plan 後計算 Pearson `r = 1.0`。

Scenario 7：模糊 regression 問題 + candidate plan

```json
{
  "task_id": "open_stat_candidate_reg_001",
  "question": "Can you model the relationship in these measurements?",
  "data": [
    {"marketing": 1.0, "revenue": 5.0},
    {"marketing": 2.0, "revenue": 8.0},
    {"marketing": 3.0, "revenue": 11.0},
    {"marketing": 4.0, "revenue": 14.0}
  ],
  "candidate_plan": {
    "analysis_type": "linear_regression",
    "columns": {"predictor": "marketing", "response": "revenue"},
    "options": {}
  }
}
```

預期：LLM 可選擇 regression 與欄位角色；scripts 計算 slope `3.0`、intercept `2.0`。

Scenario 8：模糊 group summary + candidate plan

```json
{
  "task_id": "open_stat_candidate_group_001",
  "question": "Can you summarize this table by segment?",
  "data": [
    {"segment": "new", "amount": 10.0},
    {"segment": "new", "amount": 14.0},
    {"segment": "returning", "amount": 20.0},
    {"segment": "returning", "amount": 30.0}
  ],
  "candidate_plan": {
    "analysis_type": "group_aggregate",
    "columns": {"group": "segment", "value": "amount"},
    "options": {"aggregations": ["count", "mean"]}
  }
}
```

預期：LLM 只補計畫，scripts 驗證欄位並計算各 segment 的 count/mean。

Scenario 9：不支援的統計方法，不可假裝計算

```json
{
  "task_id": "open_stat_unsupported_ttest_001",
  "question": "Run a two-sample t-test comparing score between group A and group B. Return the p-value.",
  "data": [
    {"group": "A", "score": 10.0},
    {"group": "A", "score": 12.0},
    {"group": "A", "score": 11.0},
    {"group": "B", "score": 18.0},
    {"group": "B", "score": 17.0},
    {"group": "B", "score": 19.0}
  ]
}
```

預期：`analysis_type = "unknown"`，`decision = "invalid_input"`，`result = {}`，`warnings` 說明 t-test 不在支援範圍內。skill 不應改用描述統計或 group aggregate 來假裝回答 p-value。

### Metric

每題以 `skills/open-stat-analyst-uab0/scripts/evaluate.py` 這個 deterministic evaluator 評分：

1. result file 存在且是合法 JSON object。
2. `task_id` 完全一致。
3. `analysis_type` 正確。
4. `columns` 的角色對應正確。
5. 數值欄位以 absolute tolerance `1e-6` 比對；group aggregate 依 group key 排序後比對。
6. `decision` 可由結果重算：例如 `p_value < alpha` 為 `significant`，否則 `not_significant`。
7. 遺失值情境須在 `warnings` 說明 selected-column rows 被丟棄。
8. 不支援方法情境須回 `invalid_input` 或等價拒絕狀態，且不可輸出偽造的數值結果。

### Anti-hardcoding 與 staff perturbation

此 metric 不可 gameable，因為 ground truth 由評分輸入資料即時計算，不靠固定字串。以下 perturbation 不應改變正確答案：

- 改變 `task_id`。
- 重排資料列。
- 加入無關欄位。
- 改欄位名稱但保留問題中的語意。
- A/B 資料交換 group 順序。
- 使用等價說法：`std`、`sd`、`R^2`、`r2`、`success rate`、`CTR`、`5% significance level`。
- 在 selected columns 加入 missing values，skill 應刪除並給 warning。

## 5. 預期失敗模式

- 規格與角色偏離：若 LLM 嘗試在 chat 中直接計算、輸出統計結論，正式 evaluator 不採用該文字。`SKILL.md` 因此要求先跑 dispatcher，且 `run.py` 只寫 result file。
- 資訊傳遞不足：自然語言問題可能只說「inspect these measurements」或「summarize by segment」，不足以讓 deterministic heuristic 高信心判斷分析類型。此時 LLM 只能補一個 bounded `candidate_plan`，而 candidate 必須再交回 dispatcher 驗證。
- 驗證判斷錯誤：若 LLM 指到不存在欄位、錯誤欄位角色或不支援的統計方法，dispatcher 會忽略或拒絕該 candidate，並在 `warnings` 或 `decision` 中說明原因。
- 輸出契約失敗：若工具未寫入 `AIASE_RESULT_PATH`，該題視為沒有正式輸出；因此 `run.py` 使用 temp file + `os.replace` 原子寫入，且支援 JSON argv 與 argparse flags。
- Open Track metric gameable：若 skill 只對固定 `task_id` 或固定資料列順序回答案，staff perturbation 會失敗。metric 會重排 rows、加入無關欄位、改 task_id、檢查 missing-value warning，並用輸入資料即時計算 ground truth。
- 資料品質限制：可刪除的 selected-column missing values 會列入 `warnings`；資料不足、zero variance、不可轉為數字或二元結果時，scripts 回傳 `invalid_input`。
- Scope 限制：t-test、chi-square、logistic regression 等不在支援範圍內。skill 不會假裝計算，而是回傳 `needs_plan` 或 `invalid_input`。

## 6. 互動對象

本 Open Track skill 為 standalone，不依賴同學 skill、外部服務、MCP server、網路或私有資料。

互動流程：

1. Hermes 依 `SKILL.md` 執行 `scripts/dispatch.py`。
2. `dispatch.py` 先用 deterministic heuristics 選分析類型與欄位。
3. 若低信心，LLM 只可補一個 bounded `candidate_plan`。
4. `dispatch.py` 驗證 candidate plan。
5. `compute.py` 計算最後數字。
6. `run.py` 寫入 `AIASE_RESULT_PATH`。

這個流程讓 log 能看到 LLM 有參與模糊語意判斷，但最終答案仍由 scripts 管控，兼顧互動性與可驗證性。

## 7. Token Budget 估算

預期輸入都是小型 JSON 表格，不會接近 50k tokens。

| Scenario | 預估 input tokens | 預估 output tokens | 預估 total |
|---|---:|---:|---:|
| Descriptive stats | 350 | 180 | 530 |
| Linear regression | 320 | 170 | 490 |
| Two-proportion z | 450 | 260 | 710 |
| Group aggregate | 350 | 220 | 570 |
| Missing selected values | 320 | 200 | 520 |
| Correlation candidate fallback | 420 | 180 | 600 |
| Regression candidate fallback | 430 | 190 | 620 |
| Group candidate fallback | 430 | 210 | 640 |
| Unsupported t-test rejection | 380 | 120 | 500 |
