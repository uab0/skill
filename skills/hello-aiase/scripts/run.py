#!/usr/bin/env python3
"""hello-aiase / scripts/run.py — file-based 輸出契約入口（原子寫入結果檔）。

⚠️ 刻意「自帶」resolve_result_path，不 import aiase_contract：
skill 被單獨安裝到 ~/.hermes/skills/<cat>/<name>/ 後找不到 repo 根的模組。
路徑規則須與 aiase_contract.resolve_result_path 完全一致。
"""
import os, json, argparse


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task_id", required=True)
    ap.add_argument("--name", default="world")
    a = ap.parse_args()
    result = {"task_id": a.task_id, "greeting": f"Hello, {a.name}!", "ok": True}
    path = resolve_result_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp, path)  # 原子寫入
    print(f"written ok -> {path}")


if __name__ == "__main__":
    main()
