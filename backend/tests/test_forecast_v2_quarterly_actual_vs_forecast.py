import datetime

import routes.forecast_v2_impl as impl


def test_horizon_is_18_months_in_every_rolling_filter():
    assert impl.FORECAST_HORIZON_MONTHS == 18
    assert ", 18)" in impl._rolling_next_year_filter()
    assert ", 18)" in impl._v5_next_year_filter()


def test_history_sql_is_same_product_total_grain_first_published():
    sql = impl._quarterly_history_sql("itsg", "ITSG")
    assert "itsg_forecast_vintages" in sql and "itsg_forecast_cbe" in sql
    assert "'Global_LGB_Q50_ITSG'" in sql and "'Adaptive_Ensemble'" in sql
    assert "ASC) AS rn" in sql and "f.rn = 1" in sql  # earliest vintage per model and week
    assert "UPPER(TRIM(sales_market)) IN ('ALL', 'TOTAL')" in sql


def test_assemble_splits_closed_in_progress_and_forecast_quarters():
    history = [
        {"yr": 2026, "qtr": 2, "model": "Adaptive_Ensemble", "n_weeks": 13, "actual": 10_000_000, "forecast": 9_000_000},
        {"yr": 2026, "qtr": 2, "model": "ETS", "n_weeks": 13, "actual": 10_000_000, "forecast": 11_000_000},
        {"yr": 2026, "qtr": 4, "model": "Adaptive_Ensemble", "n_weeks": 4, "actual": 3_000_000, "forecast": 3_300_000},
        {"yr": 2026, "qtr": 2, "model": "Unknown_Model", "n_weeks": 13, "actual": 1, "forecast": 1},
    ]
    forward = [
        {"yr": 2026, "qtr": 4, "actual": 3_000_000, "actual_weeks": 4, "worst": 5_000_000, "likely": 6_000_000, "best": 7_000_000, "forecast_weeks": 9},
        {"yr": 2028, "qtr": 1, "actual": 0, "actual_weeks": 0, "worst": 8_000_000, "likely": 9_000_000, "best": 10_000_000, "forecast_weeks": 13},
    ]
    rows = impl._assemble_quarterly_actual_vs_forecast(history, forward, datetime.date(2026, 10, 27))
    by = {r["label"]: r for r in rows}
    assert list(by) == ["Q2 2026", "Q4 2026", "Q1 2028"]

    q2 = by["Q2 2026"]
    assert q2["status"] == "closed" and q2["actual"] == 10_000_000 and q2["projection"] is None
    assert q2["models"]["ensemble"]["error_pct"] == -10.0  # under-forecast is negative
    assert q2["models"]["ets"]["error_pct"] == 10.0
    assert set(q2["models"]) == {"ensemble", "ets"}

    q4 = by["Q4 2026"]
    assert q4["status"] == "in_progress" and q4["actual"] == 3_000_000 and q4["actual_weeks"] == 4
    assert q4["projection"]["landing_likely"] == 9_000_000
    assert (q4["projection"]["landing_low"], q4["projection"]["landing_high"]) == (8_000_000, 10_000_000)

    q1 = by["Q1 2028"]
    assert q1["status"] == "forecast" and q1["actual"] is None
    assert q1["projection"]["landing_likely"] == 9_000_000 and q1["projection"]["actual_to_date"] == 0


def test_assemble_ignores_forward_rows_before_the_current_quarter():
    forward = [{"yr": 2026, "qtr": 2, "actual": 1, "worst": 1, "likely": 1, "best": 1}]
    assert impl._assemble_quarterly_actual_vs_forecast([], forward, datetime.date(2026, 10, 27)) == []
