#!/usr/bin/env python3
"""
run_dev.py — AIASE 2026 期末專案本地自測驅動程式

本檔同時是「single source of truth」of:
- extract_last_json_block(stdout): 從 Hermes stdout 擷取最後一段 fenced JSON
- bag_equal(rows_a, rows_b):       SQL 結果的 multiset equality
- run_sql(db_path, sql):           在 sqlite 上跑 read-only SQL
- grade_basic / grade_pairwise:    本地對 dev set / reference 對手評分

評分環境會 import 上面這些 helper,**不要在他處自行實作對比邏輯**。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parent
DEV_SET_DIR = REPO_ROOT / "dev_set"
RESULTS_DIR = REPO_ROOT / "dev_run_results"

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_TIMEOUT_SEC = int(os.environ.get("HERMES_TIMEOUT_SEC", "120"))
HERMES_QUIET = os.environ.get("HERMES_QUIET", "1").lower() not in {
    "0",
    "false",
    "no",
}
HERMES_PRELOAD_SKILL = os.environ.get("HERMES_PRELOAD_SKILL", "").lower() in {
    "1",
    "true",
    "yes",
}


# ---------------------------------------------------------------------------
# 1. JSON 輸出契約擷取
# ---------------------------------------------------------------------------

# 抓所有 ```json ... ``` 區塊(忽略開頭的 ```json 後可有任何 whitespace 直到 newline)
_FENCED_JSON_RE = re.compile(
    r"```json[ \t]*\r?\n(?P<body>.*?)\r?\n```",
    re.DOTALL | re.IGNORECASE,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def extract_last_json_block(stdout: str) -> Optional[dict]:
    """
    從 Hermes Agent 的 stdout 擷取「最後一段 fenced JSON 區塊」並解析。

    規格(規格書 §1.4):
    - 多段 fenced JSON 時只取最後一段。
    - 必須是合法 JSON、top-level 是 object。
    - 不接受 trailing comma / comments / NaN / Infinity(json.loads 本身就會 reject)。

    Returns:
        dict — 解析後的 JSON object。
        None — 找不到 / 解析失敗 / 不是 object。
    """
    if not isinstance(stdout, str):
        return None
    stdout = _ANSI_RE.sub("", stdout)
    matches = _FENCED_JSON_RE.findall(stdout)
    if matches:
        body = matches[-1].strip()
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    # Hermes sometimes renders the assistant's final message as a JSON channel
    # instead of preserving Markdown fences. Keep this fallback narrowly scoped
    # to that explicit channel marker so arbitrary prose is still rejected.
    marker = "<channel|>json"
    idx = stdout.rfind(marker)
    if idx == -1:
        return None
    tail = stdout[idx + len(marker):]
    start = tail.find("{")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(tail[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


# ---------------------------------------------------------------------------
# 2. Bag equality(SQL 結果 multiset 比對)
# ---------------------------------------------------------------------------


def _row_to_hashable(row: Any) -> tuple:
    """sqlite cursor 回傳 tuple of (str|int|float|bytes|None);轉成 hashable 以利 Counter。"""
    if isinstance(row, tuple):
        return tuple(_cell(c) for c in row)
    if isinstance(row, list):
        return tuple(_cell(c) for c in row)
    return (_cell(row),)


def _cell(v: Any) -> Any:
    if isinstance(v, bytes):
        return ("__bytes__", v)
    return v


def bag_equal(rows_a: Iterable[Any], rows_b: Iterable[Any]) -> bool:
    """
    Multiset (bag) equality between two SQL result row collections.

    規格(規格書 §4.1):
    - 列順序不計。
    - 重複列的次數**計入**(不是 set equality)。
    - 欄位順序由 SELECT 子句決定(tuple 比對 — 兩邊 SELECT 不同欄位順序就會 fail)。
    - column name / alias 不參與比對(只比 row tuple 的值)。

    Returns True iff sorted multiset is equal.
    """
    a = [_row_to_hashable(r) for r in rows_a]
    b = [_row_to_hashable(r) for r in rows_b]
    if len(a) != len(b):
        return False
    return Counter(a) == Counter(b)


# ---------------------------------------------------------------------------
# 3. SQLite 執行
# ---------------------------------------------------------------------------


READ_ONLY_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|DETACH|REPLACE|TRUNCATE|VACUUM|PRAGMA)\b",
    re.IGNORECASE,
)


def is_read_only_sql(sql: str) -> tuple[bool, str]:
    """淺檢:不允許 DDL/DML 與多 statement。"""
    if ";" in sql.strip().rstrip(";"):
        return False, "Multiple SQL statements not allowed."
    if READ_ONLY_FORBIDDEN_KEYWORDS.search(sql):
        return False, "DDL/DML keyword detected."
    return True, ""


def run_sql(db_path: Path, sql: str, timeout_sec: float = 5.0) -> list[tuple]:
    """
    Run a read-only SQL on a sqlite DB, return rows as list of tuples.

    Raises sqlite3.Error on syntax / runtime errors. Caller decides how to score.
    """
    con = sqlite3.connect(str(db_path), timeout=timeout_sec)
    try:
        con.execute("PRAGMA query_only = ON;")
        cur = con.execute(sql)
        return list(cur.fetchall())
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 4. Hermes 呼叫
# ---------------------------------------------------------------------------


def hermes_available() -> bool:
    return shutil.which(HERMES_BIN) is not None


@dataclass
class HermesResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    elapsed_sec: float
    error: str = ""


def call_hermes_skill(slash_command: str, payload: dict) -> HermesResult:
    """
    呼叫正式評分路徑:
    `hermes chat -Q --toolsets skills,terminal --yolo -q '<slash_command> <payload_json>'`。

    設定 HERMES_QUIET=0 時,可關閉 `-Q` 以對照老師公告的原始指令。

    設定 HERMES_PRELOAD_SKILL=1 時,改用本地除錯路徑:
    `hermes chat -Q --toolsets skills,terminal --yolo --skills <skill> -q '<payload_json>'`。
    預設仍維持 slash-command 路徑。

    若 hermes 不在 PATH,回傳 ok=False 並標註 error,呼叫端可決定要 skip 還是 fail。
    """
    if not hermes_available():
        return HermesResult(
            ok=False, stdout="", stderr="", returncode=-1, elapsed_sec=0.0,
            error=f"`{HERMES_BIN}` not found in PATH; set $HERMES_BIN or install Hermes Agent.",
        )

    payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    skill_name = slash_command.lstrip("/")
    if HERMES_PRELOAD_SKILL:
        arg = payload_str
        cmd = [
            HERMES_BIN,
            "chat",
            "--skills", skill_name,
        ]
    else:
        arg = f"{slash_command} {payload_str}"
        cmd = [
            HERMES_BIN,
            "chat",
        ]
    if HERMES_QUIET:
        cmd.append("-Q")
    cmd.extend([
        "--toolsets", "skills,terminal",
        "--yolo",
        "-q", arg,
    ])

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=HERMES_TIMEOUT_SEC, check=False,
        )
    except subprocess.TimeoutExpired:
        return HermesResult(
            ok=False, stdout="", stderr="", returncode=-1,
            elapsed_sec=time.time() - t0,
            error=f"hermes timed out after {HERMES_TIMEOUT_SEC}s",
        )
    elapsed = time.time() - t0
    return HermesResult(
        ok=(proc.returncode == 0),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
        elapsed_sec=elapsed,
    )


# ---------------------------------------------------------------------------
# 5. Dev set loader
# ---------------------------------------------------------------------------


def load_basic_tasks() -> list[dict]:
    tasks = []
    basic_dir = DEV_SET_DIR / "basic"
    if not basic_dir.exists():
        return tasks
    for p in sorted(basic_dir.glob("task_nl2sql_*.json")):
        try:
            tasks.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"[warn] skip invalid JSON: {p.name}: {e}", file=sys.stderr)
    return tasks


def load_pairwise_reference_tasks() -> list[dict]:
    tasks = []
    ref_dir = DEV_SET_DIR / "pairwise" / "reference_tasks"
    if not ref_dir.exists():
        return tasks
    for p in sorted(ref_dir.glob("task_*.json")):
        if p.name.endswith("_GROUND_TRUTH.json"):
            continue
        try:
            tasks.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"[warn] skip invalid JSON: {p.name}: {e}", file=sys.stderr)
    return tasks


def load_reference_ground_truth(task_id: str) -> Optional[dict]:
    """
    Return a dict with ground-truth fields (`clean_code`, `buggy_code`, `tricky_code`,
    `bugs_in_buggy`, `bugs_in_tricky`, `test_cases`) for a reference task.

    Looks for either:
      - dev_set/pairwise/reference_tasks/<task_id>_GROUND_TRUTH.json (separated form), or
      - dev_set/pairwise/reference_tasks/<task_id>.json (consolidated form, used by this repo)

    For pairwise grading, this function also rewrites field names so callers can use
    a single key shape regardless of which variant the buggy/tricky code came from.
    """
    base = DEV_SET_DIR / "pairwise" / "reference_tasks"
    gt = base / f"{task_id}_GROUND_TRUTH.json"
    if gt.exists():
        path = gt
    else:
        main = base / f"{task_id}.json"
        if not main.exists():
            return None
        path = main
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    # Normalize: callers may ask for `bugs` (sometimes meaning bugs_in_buggy).
    data.setdefault("bugs", data.get("bugs_in_buggy", []))
    return data


# ---------------------------------------------------------------------------
# 6. Track 評分流程
# ---------------------------------------------------------------------------


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    reason: str = ""
    sql_returned: str = ""
    elapsed_sec: float = 0.0
    extras: dict = field(default_factory=dict)


@dataclass
class TrackReport:
    track: str
    skill: str
    role: str = ""
    total: int = 0
    passed: int = 0
    results: list[TaskResult] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pass_rate"] = (self.passed / self.total) if self.total else 0.0
        return d


def grade_basic(skill_name: str, dry_run: bool = False) -> TrackReport:
    """對 dev_set/basic/ 內所有任務跑學生 skill,以 bag_equal 比對 gold_sql 結果。"""
    rep = TrackReport(track="basic", skill=skill_name)
    tasks = load_basic_tasks()
    rep.total = len(tasks)
    if not tasks:
        rep.note = "no basic tasks loaded from dev_set/basic/"
        return rep

    slash = f"/{skill_name}"
    for task in tasks:
        task_id = task.get("task_id", "<missing>")
        db_path = REPO_ROOT / task.get("db_path", "")
        gold_sql = task.get("gold_sql", "")

        if dry_run:
            rep.results.append(TaskResult(task_id, False, reason="dry-run (skill not invoked)"))
            continue

        if not db_path.exists():
            rep.results.append(TaskResult(task_id, False, reason=f"db_path missing: {db_path}"))
            continue

        # 呼叫 skill
        payload = {
            "task_id": task_id,
            "question": task.get("question", ""),
            "db_schema": task.get("db_schema", ""),
            "dialect": task.get("dialect", "sqlite"),
        }
        hr = call_hermes_skill(slash, payload)
        if not hr.ok:
            rep.results.append(TaskResult(
                task_id, False,
                reason=f"hermes call failed: {hr.error or hr.stderr[:200]}",
                elapsed_sec=hr.elapsed_sec,
            ))
            continue

        obj = extract_last_json_block(hr.stdout)
        if obj is None:
            rep.results.append(TaskResult(
                task_id, False, reason="no valid fenced JSON in stdout",
                elapsed_sec=hr.elapsed_sec,
            ))
            continue

        if obj.get("task_id") != task_id:
            rep.results.append(TaskResult(
                task_id, False,
                reason=f"task_id mismatch (got {obj.get('task_id')!r})",
                elapsed_sec=hr.elapsed_sec,
            ))
            continue

        student_sql = obj.get("sql", "")
        ok_ro, why = is_read_only_sql(student_sql)
        if not ok_ro:
            rep.results.append(TaskResult(
                task_id, False, reason=f"non-read-only SQL: {why}",
                sql_returned=student_sql, elapsed_sec=hr.elapsed_sec,
            ))
            continue

        # 跑兩段 SQL,以 bag_equal 比對
        try:
            student_rows = run_sql(db_path, student_sql)
            gold_rows = run_sql(db_path, gold_sql)
        except sqlite3.Error as e:
            rep.results.append(TaskResult(
                task_id, False, reason=f"SQL execution error: {e}",
                sql_returned=student_sql, elapsed_sec=hr.elapsed_sec,
            ))
            continue

        passed = bag_equal(student_rows, gold_rows)
        rep.results.append(TaskResult(
            task_id, passed,
            reason="" if passed else "bag equality failed",
            sql_returned=student_sql, elapsed_sec=hr.elapsed_sec,
            extras={"student_rowcount": len(student_rows), "gold_rowcount": len(gold_rows)},
        ))

    rep.passed = sum(1 for r in rep.results if r.passed)
    return rep


def _bug_set_from_obj(obj: dict) -> set[tuple[int, str]]:
    """把 bug-hunter 輸出的 bugs[] 轉成 (line_start, type) 集合供比對。"""
    out = set()
    for b in obj.get("bugs", []) or []:
        try:
            ls = int(b.get("line_start"))
            t = str(b.get("type", "")).strip()
            out.add((ls, t))
        except (TypeError, ValueError):
            continue
    return out


def grade_pairwise(skill_name: str, role: str, dry_run: bool = False) -> TrackReport:
    """
    Pairwise 本地評分 — 學生端無 hidden tests,只能對 reference 對手與 ground truth。

    若 role == "code-author":
        - 對每個 reference task,呼叫學生 author 產 code。
        - 把 code 餵給 reference-bug-hunter-aggressive (作為一個快速 sanity 對手)。
        - 同時跑 ground truth 的 test_cases 算 pass rate。
        - 兩者皆寫入 result,但 pass 判定以 test_cases pass rate 為準(完整通過才 pass)。

    若 role == "bug-hunter":
        - 對每個 reference task,把 reference-author-buggy 的 code 餵給學生 hunter。
        - 比對 hunter 的 bugs[] 與 ground-truth bug 位置(以 (line_start, type) 集合的 Jaccard >= 0.5 視為 pass)。
        - 同時對 reference-author-clean 跑,檢查 false positive(乾淨 code 不應報任何 bug)。
    """
    rep = TrackReport(track="pairwise", skill=skill_name, role=role)
    tasks = load_pairwise_reference_tasks()
    rep.total = len(tasks)
    if not tasks:
        rep.note = "no reference tasks loaded from dev_set/pairwise/reference_tasks/"
        return rep

    slash = f"/{skill_name}"

    if role == "code-author":
        for task in tasks:
            task_id = task["task_id"]
            if dry_run:
                rep.results.append(TaskResult(task_id, False, reason="dry-run"))
                continue
            payload = {
                "task_id": task_id,
                "task_description": task.get("task_description", ""),
                "constraints": task.get("constraints", {}),
            }
            hr = call_hermes_skill(slash, payload)
            if not hr.ok:
                rep.results.append(TaskResult(task_id, False, reason=f"hermes failed: {hr.error}"))
                continue
            obj = extract_last_json_block(hr.stdout)
            if obj is None or obj.get("task_id") != task_id or "code" not in obj:
                rep.results.append(TaskResult(task_id, False, reason="contract violation"))
                continue

            code = obj.get("code", "")
            gt = load_reference_ground_truth(task_id) or {}
            test_cases = gt.get("test_cases", [])
            passed_cases, failed_cases = _run_code_test_cases(code, task.get("constraints", {}), test_cases)

            all_pass = (failed_cases == 0 and passed_cases == len(test_cases))
            rep.results.append(TaskResult(
                task_id, all_pass,
                reason=("" if all_pass else f"{failed_cases}/{len(test_cases)} hidden-style cases failed"),
                elapsed_sec=hr.elapsed_sec,
                extras={"passed_cases": passed_cases, "total_cases": len(test_cases)},
            ))

    elif role == "bug-hunter":
        for task in tasks:
            task_id = task["task_id"]
            if dry_run:
                rep.results.append(TaskResult(task_id, False, reason="dry-run"))
                continue
            gt = load_reference_ground_truth(task_id) or {}
            buggy_code = gt.get("buggy_code", "")
            clean_code = gt.get("clean_code", "")
            gt_bugs = _bug_set_from_obj({"bugs": gt.get("bugs", [])})
            if not buggy_code:
                rep.results.append(TaskResult(task_id, False, reason="no ground-truth buggy_code"))
                continue

            # 對 buggy code:期待 hunter 抓到
            payload_b = {
                "task_id": task_id,
                "task_description": task.get("task_description", ""),
                "code": buggy_code,
            }
            hr = call_hermes_skill(slash, payload_b)
            if not hr.ok:
                rep.results.append(TaskResult(task_id, False, reason=f"hermes failed: {hr.error}"))
                continue
            obj = extract_last_json_block(hr.stdout)
            if obj is None or obj.get("task_id") != task_id:
                rep.results.append(TaskResult(task_id, False, reason="contract violation"))
                continue

            student_bugs = _bug_set_from_obj(obj)
            # Jaccard
            inter = len(student_bugs & gt_bugs)
            union = len(student_bugs | gt_bugs) or 1
            recall_like = inter / max(1, len(gt_bugs))
            # 也對 clean 跑一輪,加分項:應無誤報
            clean_fp = 0
            if clean_code:
                payload_c = dict(payload_b); payload_c["code"] = clean_code
                hr_c = call_hermes_skill(slash, payload_c)
                if hr_c.ok:
                    objc = extract_last_json_block(hr_c.stdout) or {}
                    if objc.get("verdict") == "buggy" or len(objc.get("bugs", []) or []) > 0:
                        clean_fp = 1

            passed = (recall_like >= 0.5 and clean_fp == 0)
            rep.results.append(TaskResult(
                task_id, passed,
                reason=("" if passed else f"recall={recall_like:.2f}, clean_fp={clean_fp}"),
                elapsed_sec=hr.elapsed_sec,
                extras={
                    "jaccard": inter / union,
                    "recall_like": recall_like,
                    "clean_fp": clean_fp,
                },
            ))
    else:
        rep.note = f"unknown role: {role}"
        return rep

    rep.passed = sum(1 for r in rep.results if r.passed)
    return rep


def _run_code_test_cases(code: str, constraints: dict, test_cases: list[dict]) -> tuple[int, int]:
    """
    在一個簡易 namespace 中 exec student code,呼叫 entry_function,以 test_cases 比對。
    test_cases: [{"input": [...], "expected": ...}, ...]
    回傳 (passed_count, failed_count)。任何 exception 都計為 failure。
    """
    entry = constraints.get("entry_function", "")
    if not entry or not code:
        return 0, len(test_cases)

    ns: dict = {}
    try:
        exec(compile(code, "<student_code>", "exec"), ns)
    except Exception:
        return 0, len(test_cases)

    fn = ns.get(entry)
    if not callable(fn):
        return 0, len(test_cases)

    passed = 0
    for tc in test_cases:
        args = tc.get("input", [])
        expected = tc.get("expected")
        try:
            got = fn(*args) if isinstance(args, list) else fn(args)
            if got == expected:
                passed += 1
        except Exception:
            pass
    return passed, len(test_cases) - passed


# ---------------------------------------------------------------------------
# 7. CLI
# ---------------------------------------------------------------------------


def _write_report(report: TrackReport) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{report.role}" if report.role else ""
    out = RESULTS_DIR / f"{report.track}{suffix}_{report.skill}_{stamp}.json"
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return out


def _print_summary(report: TrackReport) -> None:
    print(f"\n=== {report.track.upper()} :: {report.skill} {('('+report.role+')') if report.role else ''} ===")
    if report.note:
        print(f"  note: {report.note}")
    print(f"  total: {report.total}  passed: {report.passed}  rate: "
          f"{(report.passed/report.total*100 if report.total else 0):.1f}%")
    if report.results:
        for r in report.results[:50]:
            mark = "✓" if r.passed else "✗"
            print(f"   {mark} {r.task_id}  {r.reason}")
        if len(report.results) > 50:
            print(f"   ... ({len(report.results)-50} more)")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="AIASE 2026 local dev runner")
    p.add_argument("--skill", required=False, help="skill name (folder name)")
    p.add_argument("--track", choices=["basic", "pairwise"], required=False)
    p.add_argument("--role", choices=["code-author", "bug-hunter"], default="",
                   help="required for --track pairwise")
    p.add_argument("--dry-run", action="store_true",
                   help="don't call hermes; just verify loader + structure")
    p.add_argument("--check-only", action="store_true",
                   help="check dev_set integrity + helpers, exit 0/1; no skill invocation")
    args = p.parse_args(argv)

    if args.check_only:
        return _check_only()

    if not args.skill or not args.track:
        p.error("--skill and --track are required (or use --check-only)")

    if args.track == "basic":
        rep = grade_basic(args.skill, dry_run=args.dry_run)
    else:
        if not args.role:
            p.error("--role is required when --track pairwise")
        rep = grade_pairwise(args.skill, args.role, dry_run=args.dry_run)

    _print_summary(rep)
    if not args.dry_run:
        out = _write_report(rep)
        print(f"\nreport written to: {out.relative_to(REPO_ROOT)}")
    return 0


def _check_only() -> int:
    """Sanity check the dev set + helpers without invoking Hermes."""
    print("[check] loading basic tasks...")
    tasks = load_basic_tasks()
    print(f"  loaded {len(tasks)} basic tasks")
    bad = 0
    for t in tasks:
        tid = t.get("task_id", "?")
        db = REPO_ROOT / t.get("db_path", "")
        if not db.exists():
            print(f"  ✗ {tid}: missing db {db.relative_to(REPO_ROOT)}")
            bad += 1
            continue
        gold = t.get("gold_sql", "")
        ok, why = is_read_only_sql(gold)
        if not ok:
            print(f"  ✗ {tid}: gold_sql not read-only: {why}")
            bad += 1
            continue
        try:
            rows = run_sql(db, gold)
        except sqlite3.Error as e:
            print(f"  ✗ {tid}: gold_sql failed: {e}")
            bad += 1
            continue
        if not bag_equal(rows, rows):
            print(f"  ✗ {tid}: bag_equal not reflexive!")
            bad += 1
            continue
        print(f"  ✓ {tid}: {len(rows)} rows")

    print(f"\n[check] reference tasks...")
    refs = load_pairwise_reference_tasks()
    print(f"  loaded {len(refs)} reference tasks")
    for r in refs:
        tid = r.get("task_id", "?")
        gt = load_reference_ground_truth(tid)
        if gt is None:
            print(f"  ! {tid}: no ground-truth (may be intentional for student-facing variant)")
        else:
            print(f"  ✓ {tid}: ground-truth has {len(gt.get('bugs', []))} bugs, "
                  f"{len(gt.get('test_cases', []))} test cases")

    print(f"\n[check] done. {bad} issue(s).")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
