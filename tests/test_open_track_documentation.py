from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPEN_TRACK = ROOT / "OPEN_TRACK.md"


def test_open_track_has_required_sections_and_no_placeholders():
    text = OPEN_TRACK.read_text(encoding="utf-8")
    required = [
        "## 1. Skill 簡介",
        "## 2. Skill 名稱與目錄",
        "## 3. 呼叫方式",
        "## 4. 自定 Verifiable Scenario",
        "## 5. 預期失敗模式",
        "## 6. 互動對象",
        "## 7. Token Budget 估算",
    ]
    for heading in required:
        assert heading in text

    forbidden = [
        "(一句話說明",
        "(你的 skill",
        "(評分環境",
        "open-<short-name>",
        "<github_id>",
        "Scenario 1: ...",
    ]
    for marker in forbidden:
        assert marker not in text


def test_open_track_declares_current_skill_and_file_based_output():
    text = OPEN_TRACK.read_text(encoding="utf-8")
    assert "/open-stat-analyst-uab0" in text
    assert "skills/open-stat-analyst-uab0/" in text
    assert "AIASE_RESULT_PATH" in text
    assert "deterministic evaluator" in text
    assert "Anti-hardcoding" in text
    assert "candidate_plan" in text
