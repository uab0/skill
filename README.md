# AIASE 2026 期末專案 - uab0

這個 repo 是我的 AIASE 2026 期末專案，內容是可在 Hermes Agent 中執行的四個 skill。

## Skills

- `text2sql-uab0`：Basic Track 的 Text2SQL skill。透過 `scripts/dispatch.py` 產生與驗證 SQL，最後寫入正式 result file。
- `code-author-uab0`：Pairwise Code Author skill。產生 Python 實作，並先跑本地 self-tests 再輸出結果。
- `bug-hunter-uab0`：Pairwise Bug Hunter skill。用 deterministic probes 與 bounded fallback review 回報具體行號的 bug。
- `open-stat-analyst-uab0`：Open Track 統計分析 skill。支援一組可驗證、只依賴 Python 標準函式庫的統計分析，並提供 evaluator script。

## 重要檔案

- `PAIRWISE_ROLE.md`：Pairwise 角色宣告。
- `OPEN_TRACK.md`：Open Track 的 scenario、metric、perturbation 與 token budget 說明。
- `report.md`：設計決策、失敗分析與最終自測摘要。
- `run_dev.py`：Basic 與 Pairwise 的本地 dev-set runner。
- `aiase_contract.py`：file-based output contract 的共用 helper。
- `tests/`：本地 regression tests，用來檢查 deterministic scripts 與輸出契約。

## 本地檢查

```bash
.venv/bin/python verify_repo.py --github-id uab0
.venv/bin/pytest -q
```

Basic：

```bash
.venv/bin/python run_dev.py --track basic --skill text2sql-uab0
```

Pairwise：

```bash
.venv/bin/python run_dev.py --track pairwise --role code-author --skill code-author-uab0
.venv/bin/python run_dev.py --track pairwise --role bug-hunter --skill bug-hunter-uab0
```

Open Track evaluator 範例：

```bash
.venv/bin/python skills/open-stat-analyst-uab0/scripts/evaluate.py --input scenario.json --result result.json
```

## 備註

本專案使用 file-based output，正式輸出由 `AIASE_RESULT_PATH` 指定的 result file 決定。chat 文字不是正式答案；四個 skill 都要求先執行 dispatcher，等 result file 寫入後只回覆 `Done.`。

`pytest` 僅作為本地 regression tests；正式評分仍以 file-based result contract 與公開 dev-set 檢查邏輯為準。
