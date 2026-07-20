from datetime import date

from stock_research.dataclasses import QuarterRecord, is_estimate_quarter_label, is_historical_quarter
from stock_research.excel_parser import _extract_quarter_date, _forecast_zero_as_missing


def test_incomplete_year_label_is_estimate_not_historical() -> None:
    quarter = _quarter("2026-")

    assert is_estimate_quarter_label("2026-")
    assert not is_historical_quarter(quarter, today=date(2026, 7, 9))


def test_current_year_complete_label_can_remain_historical() -> None:
    quarter = _quarter("2026 Q1")

    assert is_historical_quarter(quarter, today=date(2026, 7, 9))


def test_forecast_flag_overrides_historical_date() -> None:
    quarter = _quarter("2026-04-30", quarter_date=date(2026, 4, 30), is_forecast=True)

    assert not is_historical_quarter(quarter, today=date(2026, 7, 9))


def test_parser_extracts_date_from_legacy_label() -> None:
    assert _extract_quarter_date("2016-04-26 (A)") == date(2016, 4, 26)


def test_forecast_zero_rolling_values_are_missing() -> None:
    assert _forecast_zero_as_missing(0.0, is_forecast=True) is None
    assert _forecast_zero_as_missing(0.0, is_forecast=False) == 0.0
    assert _forecast_zero_as_missing(12.3, is_forecast=True) == 12.3


def _quarter(label: str, quarter_date: date | None = None, is_forecast: bool = False) -> QuarterRecord:
    return QuarterRecord(
        row_number=1,
        quarter_label=label,
        quarter_date=quarter_date,
        status=None,
        revenue_estimate_millions=None,
        revenue_actual_millions=100.0,
        rolling_4q_revenue_millions=None,
        rolling_4q_revenue_yoy_growth=None,
        workbook_revenue_surprise_pct=None,
        workbook_revenue_qoq_growth=None,
        workbook_revenue_yoy_growth=None,
        eps_estimate=None,
        eps_actual=None,
        rolling_4q_eps=None,
        rolling_4q_eps_yoy_growth=None,
        workbook_eps_surprise_pct=None,
        workbook_eps_qoq_growth=None,
        workbook_eps_yoy_growth=None,
        shares_millions=None,
        total_earnings_millions=None,
        price_before_earnings=None,
        price_after_earnings=None,
        workbook_price_reaction_pct=None,
        is_forecast=is_forecast,
    )
