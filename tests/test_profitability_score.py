from datetime import date
from pathlib import Path

from stock_research.analysis_engine import analyze_workbook
from stock_research.dataclasses import CompanyInfo, ParsedWorkbook, QuarterRecord


def _quarter(row: int, label: str, revenue: float, earnings: float) -> QuarterRecord:
    return QuarterRecord(
        row_number=row,
        quarter_label=label,
        quarter_date=date(2026, row, 1),
        status=None,
        revenue_estimate_millions=None,
        revenue_actual_millions=revenue,
        rolling_4q_revenue_millions=None,
        rolling_4q_revenue_yoy_growth=None,
        workbook_revenue_surprise_pct=None,
        workbook_revenue_qoq_growth=None,
        workbook_revenue_yoy_growth=None,
        eps_estimate=None,
        eps_actual=1.0,
        rolling_4q_eps=None,
        rolling_4q_eps_yoy_growth=None,
        workbook_eps_surprise_pct=None,
        workbook_eps_qoq_growth=None,
        workbook_eps_yoy_growth=None,
        shares_millions=None,
        total_earnings_millions=earnings,
        price_before_earnings=None,
        price_after_earnings=None,
        workbook_price_reaction_pct=None,
    )


def test_profitability_uses_earnings_margin_fallback_without_exploding() -> None:
    parsed = ParsedWorkbook(
        company=CompanyInfo(
            title="Test",
            ticker="TST",
            company_name="Test Co",
            description=None,
            workbook_path=Path("test.xlsx"),
            worksheet_names=("Quarterly",),
            data_sheet_name="Quarterly",
            header_row=1,
            data_start_row=2,
            data_end_row=9,
        ),
        quarters=tuple(_quarter(row, f"Q{row}", 100.0, 25.0) for row in range(1, 9)),
    )

    score = analyze_workbook(parsed).scores.profitability

    assert score > 50
    assert score < 90
