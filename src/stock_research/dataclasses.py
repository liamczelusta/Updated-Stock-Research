"""Typed data containers for parsed workbooks and deterministic analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
from typing import Any


ExcelValue = str | int | float | date | None


@dataclass(frozen=True)
class StaticCell:
    """A workbook cell that carries fixed metadata or template context."""

    sheet_name: str
    coordinate: str
    value: ExcelValue
    description: str


@dataclass(frozen=True)
class AdditionalMetricValue:
    """A non-core metric captured from the optional company-specific columns."""

    name: str
    value: ExcelValue
    column_letter: str
    source_cell: str


@dataclass(frozen=True)
class QuarterRecord:
    """One row from the workbook's fixed quarterly matrix."""

    row_number: int
    quarter_label: str
    quarter_date: date | None
    status: str | None
    revenue_estimate_millions: float | None
    revenue_actual_millions: float | None
    rolling_4q_revenue_millions: float | None
    rolling_4q_revenue_yoy_growth: float | None
    workbook_revenue_surprise_pct: float | None
    workbook_revenue_qoq_growth: float | None
    workbook_revenue_yoy_growth: float | None
    eps_estimate: float | None
    eps_actual: float | None
    rolling_4q_eps: float | None
    rolling_4q_eps_yoy_growth: float | None
    workbook_eps_surprise_pct: float | None
    workbook_eps_qoq_growth: float | None
    workbook_eps_yoy_growth: float | None
    shares_millions: float | None
    total_earnings_millions: float | None
    price_before_earnings: float | None
    price_after_earnings: float | None
    workbook_price_reaction_pct: float | None
    is_forecast: bool = False
    notes: tuple[str, ...] = ()
    additional_metrics: tuple[AdditionalMetricValue, ...] = ()


@dataclass(frozen=True)
class CompanyInfo:
    """Company-level metadata found in the workbook."""

    title: str
    ticker: str | None
    company_name: str | None
    description: str | None
    workbook_path: Path
    worksheet_names: tuple[str, ...]
    data_sheet_name: str
    header_row: int
    data_start_row: int
    data_end_row: int
    static_cells: tuple[StaticCell, ...] = ()


@dataclass(frozen=True)
class ParserWarning:
    """A non-fatal issue found while reading the workbook."""

    message: str
    sheet_name: str | None = None
    cell: str | None = None


@dataclass(frozen=True)
class ParsedWorkbook:
    """Complete parsed representation of one stock workbook."""

    company: CompanyInfo
    quarters: tuple[QuarterRecord, ...]
    ignored_sheets: tuple[str, ...] = ()
    ignored_ranges: tuple[str, ...] = ()
    warnings: tuple[ParserWarning, ...] = ()


@dataclass(frozen=True)
class QuarterAnalysis:
    """Derived calculations for one quarter."""

    row_number: int
    quarter_label: str
    revenue_surprise_pct: float | None
    eps_surprise_pct: float | None
    revenue_qoq_growth: float | None
    revenue_yoy_growth: float | None
    eps_qoq_growth: float | None
    eps_yoy_growth: float | None
    rolling_revenue_growth: float | None
    rolling_eps_growth: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    price_reaction_pct: float | None


@dataclass(frozen=True)
class ScoreBreakdown:
    """Named deterministic scores on a 0-100 scale."""

    historical_execution: float
    growth: float
    profitability: float
    financial_quality: float
    management_execution: float
    overall_investment: float


@dataclass(frozen=True)
class TrendSignal:
    """A human-readable trend flag produced by deterministic rules."""

    name: str
    direction: str
    description: str
    strength: float | None = None


@dataclass(frozen=True)
class AnalysisResult:
    """Complete deterministic analysis output for a parsed workbook."""

    company: CompanyInfo
    quarter_analyses: tuple[QuarterAnalysis, ...]
    scores: ScoreBreakdown
    trends: tuple[TrendSignal, ...] = ()
    risk_indicators: tuple[str, ...] = ()
    summary_metrics: dict[str, Any] = field(default_factory=dict)


INCOMPLETE_DATE_RE = re.compile(r"^\d{4}[-/]\s*$|^\d{4}[-/]\d{0,2}\s*$")


def is_estimate_quarter_label(label: str | None) -> bool:
    """Return True when a quarter label is an incomplete date-like estimate marker."""

    text = str(label or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return lowered in {"estimate", "est", "future", "forward"} or bool(INCOMPLETE_DATE_RE.match(text))


def is_historical_quarter(quarter: QuarterRecord, today: date | None = None) -> bool:
    """Return True only for completed historical workbook quarters."""

    today = today or date.today()
    if quarter.is_forecast:
        return False
    if quarter.quarter_date is not None:
        return quarter.quarter_date <= today
    label = quarter.quarter_label.strip()
    if is_estimate_quarter_label(label):
        return False
    if len(label) >= 4 and label[:4].isdigit():
        year = int(label[:4])
        return year <= today.year
    return True
