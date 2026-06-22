"""Tests documenting the official file-based contract semantics."""

import aiase_contract as contract
from run_dev import bag_equal as strict_bag_equal


def test_official_bag_equal_ignores_column_order():
    a = [("Alice", "CS")]
    b = [("CS", "Alice")]
    assert contract.bag_equal(a, b)


def test_strict_quality_bag_equal_keeps_column_order():
    a = [("Alice", "CS")]
    b = [("CS", "Alice")]
    assert not strict_bag_equal(a, b)
