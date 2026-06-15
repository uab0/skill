#!/usr/bin/env python3
"""Deterministic standard-library statistics for open-stat-analyst-uab0."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


class StatError(ValueError):
    """Raised when an analysis cannot be computed for valid task-level reasons."""


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def to_number(value: Any) -> float:
    if not is_number(value):
        raise StatError(f"non-numeric value: {value!r}")
    return float(value)


def to_binary(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return int(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "success", "converted", "1"}:
            return 1
        if v in {"false", "no", "failure", "not_converted", "0"}:
            return 0
    raise StatError(f"non-binary value: {value!r}")


def column_values(rows: list[dict], column: str, *, numeric: bool = False) -> list[Any]:
    vals: list[Any] = []
    for row in rows:
        if column not in row or row[column] is None:
            continue
        vals.append(to_number(row[column]) if numeric else row[column])
    if not vals:
        raise StatError(f"column {column!r} has no usable values")
    return vals


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise StatError("percentile requires at least one value")
    if p < 0.0 or p > 1.0:
        raise StatError("percentile p must be in [0, 1]")
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    weight = pos - lo
    return xs[lo] * (1.0 - weight) + xs[hi] * weight


def descriptive_stats(rows: list[dict], column: str) -> dict:
    values = column_values(rows, column, numeric=True)
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
        "min": min(values),
        "max": max(values),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def pearson_correlation(rows: list[dict], x_col: str, y_col: str) -> dict:
    pairs = _numeric_pairs(rows, x_col, y_col)
    if len(pairs) < 2:
        raise StatError("correlation requires at least two paired rows")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    sx = _sample_stdev(xs)
    sy = _sample_stdev(ys)
    if sx == 0.0 or sy == 0.0:
        raise StatError("correlation undefined for zero-variance columns")
    cov = _sample_covariance(xs, ys)
    r = cov / (sx * sy)
    return {"n": len(pairs), "r": max(-1.0, min(1.0, r))}


def linear_regression(rows: list[dict], x_col: str, y_col: str) -> dict:
    pairs = _numeric_pairs(rows, x_col, y_col)
    if len(pairs) < 2:
        raise StatError("linear regression requires at least two paired rows")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    var_x = _sample_variance(xs)
    if var_x == 0.0:
        raise StatError("linear regression undefined for zero-variance predictor")
    slope = _sample_covariance(xs, ys) / var_x
    intercept = statistics.fmean(ys) - slope * statistics.fmean(xs)
    fitted = [intercept + slope * x for x in xs]
    sse = sum((y - y_hat) ** 2 for y, y_hat in zip(ys, fitted))
    mean_y = statistics.fmean(ys)
    sst = sum((y - mean_y) ** 2 for y in ys)
    r_squared = 1.0 if sst == 0.0 and sse == 0.0 else (0.0 if sst == 0.0 else 1.0 - sse / sst)
    return {
        "n": len(pairs),
        "slope": slope,
        "intercept": intercept,
        "r_squared": max(0.0, min(1.0, r_squared)),
    }


def two_proportion_z(rows: list[dict], group_col: str, outcome_col: str, alpha: float = 0.05) -> dict:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if group_col not in row or outcome_col not in row or row[group_col] is None or row[outcome_col] is None:
            continue
        groups[str(row[group_col])].append(to_binary(row[outcome_col]))
    if len(groups) != 2:
        raise StatError("two_proportion_z requires exactly two groups")
    labels = sorted(groups)
    a, b = labels
    x1 = sum(groups[a])
    n1 = len(groups[a])
    x2 = sum(groups[b])
    n2 = len(groups[b])
    if n1 == 0 or n2 == 0:
        raise StatError("two_proportion_z requires non-empty groups")
    p1 = x1 / n1
    p2 = x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
    if se == 0.0:
        raise StatError("two_proportion_z undefined when pooled standard error is zero")
    z = (p2 - p1) / se
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return {
        "groups": {
            a: {"n": n1, "successes": x1, "rate": p1},
            b: {"n": n2, "successes": x2, "rate": p2},
        },
        "difference": p2 - p1,
        "pooled_proportion": pooled,
        "z_stat": z,
        "p_value": max(0.0, min(1.0, p_value)),
        "alpha": alpha,
    }


def group_aggregate(rows: list[dict], group_col: str, value_col: str, aggregations: list[str]) -> dict:
    allowed = {"count", "sum", "mean", "median", "min", "max"}
    aggs = [a for a in aggregations if a in allowed]
    if not aggs:
        aggs = ["count", "mean"]
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if group_col not in row or value_col not in row or row[group_col] is None or row[value_col] is None:
            continue
        grouped[str(row[group_col])].append(to_number(row[value_col]))
    if not grouped:
        raise StatError("group_aggregate found no usable grouped numeric values")
    out: dict[str, dict[str, float | int]] = {}
    for key in sorted(grouped):
        values = grouped[key]
        item: dict[str, float | int] = {}
        if "count" in aggs:
            item["count"] = len(values)
        if "sum" in aggs:
            item["sum"] = sum(values)
        if "mean" in aggs:
            item["mean"] = statistics.fmean(values)
        if "median" in aggs:
            item["median"] = statistics.median(values)
        if "min" in aggs:
            item["min"] = min(values)
        if "max" in aggs:
            item["max"] = max(values)
        out[key] = item
    return {"groups": out, "aggregations": aggs}


def _numeric_pairs(rows: list[dict], x_col: str, y_col: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        if x_col not in row or y_col not in row or row[x_col] is None or row[y_col] is None:
            continue
        pairs.append((to_number(row[x_col]), to_number(row[y_col])))
    return pairs


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        raise StatError("sample variance requires at least two values")
    return statistics.variance(values)


def _sample_stdev(values: list[float]) -> float:
    if len(values) < 2:
        raise StatError("sample stdev requires at least two values")
    return statistics.stdev(values)


def _sample_covariance(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise StatError("sample covariance requires paired values")
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
