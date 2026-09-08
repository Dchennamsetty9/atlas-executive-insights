"""Offline regression tests for strict retained forecast/actual matching."""

from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes.forecast_backtest import (  # noqa: E402
    backtest_response, backtest_summary, build_backtest_query, valid_pairs,
)

TODAY = date(2026, 9, 8)


def pair(**changes):
    return {"ds": "2026-08-31", "run_date": "2026-08-09",
            "origin_ts": "2026-08-09 11:00:00", "actual_run_date": "2026-09-08",
            "predicted": 100, "actual": 125, "worst": 80, "best": 130,
            "forecast_variants": 1, "actual_variants": 1, **changes}


def test_unique_closed_pair_keeps_source_values_and_lead_days():
    rows, rejected = valid_pairs([pair()], 4, TODAY)
    assert rejected == 0
    assert rows[0]["lead_days"] == 22
    assert rows[0]["predicted"] == 100
    assert rows[0]["actual"] == 125
    assert backtest_summary(rows) == {
        "weeks_scored": 1, "mape_weeks_scored": 1, "band_weeks_scored": 1,
        "zero_actual_weeks": 0, "coverage_pct": 100, "mape_pct": 20, "bias_pct": -20,
    }


@pytest.mark.parametrize("changes", [
    {"run_date": None}, {"origin_ts": None}, {"actual_run_date": None},
    {"run_date": "2026-08-31"}, {"origin_ts": "2026-08-10 11:00:00"},
    {"actual_run_date": "2026-09-01"}, {"actual_run_date": "2026-09-09"},
    {"predicted": float("nan")}, {"actual": float("inf")}, {"predicted": None},
    {"actual": None}, {"predicted": True}, {"forecast_variants": 2}, {"actual_variants": 2},
])
def test_invalid_or_ambiguous_pairs_are_rejected(changes):
    assert valid_pairs([pair(**changes)], 4, TODAY) == ([], 1)


def test_does_not_count_duplicate_targets_as_multiple_weeks():
    rows, rejected = valid_pairs([pair(), pair(predicted=105)], 4, TODAY)
    assert rows == []
    assert rejected == 2


def test_requested_horizon_is_enforced_not_relabelled():
    assert valid_pairs([pair()], 1, TODAY) == ([], 1)
    assert valid_pairs([pair()], 4, TODAY)[1] == 0


def test_open_week_is_not_scored_even_with_an_actual():
    row = pair(ds="2026-09-07", run_date="2026-08-16", origin_ts="2026-08-16 10:00:00")
    assert valid_pairs([row], 4, TODAY) == ([], 1)


@pytest.mark.parametrize("changes", [{"worst": None}, {"best": float("inf")}, {"worst": 150}, {"best": 90}])
def test_invalid_bounds_do_not_erase_or_modify_point(changes):
    rows, rejected = valid_pairs([pair(**changes)], 4, TODAY)
    assert rejected == 0 and rows[0]["predicted"] == 100
    assert rows[0]["worst"] is None and rows[0]["best"] is None
    assert backtest_summary(rows)["coverage_pct"] is None
    assert backtest_summary(rows)["mape_pct"] == 20


def test_coverage_uses_only_banded_pairs_and_zero_actual_is_explicit():
    rows, _ = valid_pairs([
        pair(),
        pair(ds="2026-08-24", run_date="2026-08-02", origin_ts="2026-08-02 11:00:00",
             actual=0, predicted=0, worst=None, best=None),
    ], 4, TODAY)
    summary = backtest_summary(rows)
    assert summary["weeks_scored"] == 2
    assert summary["mape_weeks_scored"] == summary["band_weeks_scored"] == 1
    assert summary["zero_actual_weeks"] == 1
    assert summary["coverage_pct"] == 100


@pytest.mark.parametrize("product", ["UCC", "ITSG"])
def test_query_enforces_identity_total_grain_and_unique_latest_origin(product):
    sql = build_backtest_query(f"{product}_vintages", f"{product}_cbe", product, "lightgbm", 4)
    assert f"Global_LGB_Q50_{product}" in sql
    assert f"product_group)) = '{product}'" in sql
    assert sql.count("LOWER(TRIM(grain_level)) = 'total'") == 2
    assert sql.count("UPPER(TRIM(sales_market)) IN ('ALL', 'TOTAL')") == 2
    assert "BETWEEN 22 AND 28" in sql
    assert "origin_ts < CAST(ds AS TIMESTAMP)" in sql
    assert "origin_date = CAST(origin_ts AS DATE)" in sql
    assert "ORDER BY origin_ts DESC" in sql
    assert "forecast_variants" in sql and "actual_variants" in sql
    assert "accuracy_history" not in sql
    assert "p50 DESC" not in sql and "LIMIT 104" not in sql


def test_native_prophet_cannot_be_silently_replaced_with_trend_model():
    with pytest.raises(ValueError):
        build_backtest_query("v", "a", "UCC", "prophet", 4)


def test_empty_error_and_small_sample_responses_are_honest():
    scope = dict(product="ITSG", market="Total", model="ensemble", horizon_weeks=4)
    empty = backtest_response(**scope, today=TODAY)
    assert empty["source"] == "unavailable" and empty["rows"] == []
    assert empty["reason"] == "no_matched_history"
    assert empty["summary"]["mape_pct"] is None
    failed = backtest_response(**scope, reason="source_query_failed")
    assert not failed["available"] and failed["source"] != "demo"
    live = backtest_response(**scope, raw_rows=[pair()], today=TODAY)
    assert live["small_sample"] and live["available"]
    assert live["interval_basis"] == "published_bounds_not_assumed_calibrated"