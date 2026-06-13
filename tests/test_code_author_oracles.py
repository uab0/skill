"""Tests for Code Author hidden-style oracle samples."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELFTEST_PATH = ROOT / "skills" / "code-author-uab0" / "scripts" / "selftest.py"


def _load():
    spec = importlib.util.spec_from_file_location("code_author_selftest", SELFTEST_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


st = _load()


def test_parse_csv_samples_use_csv_oracle():
    samples = st.generated_samples("Implement parse_csv_line(line)", "parse_csv_line")
    labels = {s["label"] for s in samples}
    assert {"trailing comma", "quoted empty", "escaped quote"} <= labels
    assert any(s["input"] == ["a,b,"] and s["expected"] == ["a", "b", ""] for s in samples)


def test_unique_paths_samples_include_comb_rectangle():
    samples = st.generated_samples("Implement unique_paths(m, n) for a grid", "unique_paths")
    assert any(s["input"] == [3, 7] and s["expected"] == 28 for s in samples)


def test_kth_smallest_samples_include_invalid_k_and_negatives():
    samples = st.generated_samples("Implement kth_smallest(nums, k)", "kth_smallest")
    assert any(s["input"] == [[1, 2, 3], 0] and s["expected"] is None for s in samples)
    assert any(s["input"] == [[-1, -5, 3, 0], 2] and s["expected"] == -1 for s in samples)


def test_binary_search_duplicate_accepts_any_matching_index():
    code = """def binary_search(arr, target):
    return 3
"""
    sample = {"input": [[1, 2, 2, 2, 3], 2], "expected_any_index_value": 2}
    ok, err = st.run_sample(code, "binary_search", sample)
    assert ok, err
