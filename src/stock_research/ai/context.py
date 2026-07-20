"""Prompt context assembly for the workbook-aware AI assistant."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from stock_research.dataclasses import AnalysisResult, ParsedWorkbook, is_historical_quarter
from stock_research.market_data import MarketDataSnapshot


def build_ai_context(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
    max_quarters: int = 6,
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None = None,
) -> str:
    """Build a compact, deterministic evidence packet for an AI provider."""

    quarters = []
    historical_pairs = [
        (quarter, quarter_analysis)
        for quarter, quarter_analysis in zip(parsed.quarters, analysis.quarter_analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]
    for quarter, quarter_analysis in historical_pairs[:max_quarters]:
        quarters.append(
            {
                "quarter": quarter.quarter_label,
                "revenue_estimate_millions": quarter.revenue_estimate_millions,
                "revenue_actual_millions": quarter.revenue_actual_millions,
                "revenue_surprise_pct": _round_or_none(quarter_analysis.revenue_surprise_pct),
                "revenue_yoy_growth": _round_or_none(quarter_analysis.revenue_yoy_growth),
                "eps_estimate": quarter.eps_estimate,
                "eps_actual": quarter.eps_actual,
                "eps_surprise_pct": _round_or_none(quarter_analysis.eps_surprise_pct),
                "eps_yoy_growth": _round_or_none(quarter_analysis.eps_yoy_growth),
                "rolling_4q_revenue_millions": quarter.rolling_4q_revenue_millions,
                "rolling_4q_eps": quarter.rolling_4q_eps,
                "gross_margin": _round_or_none(quarter_analysis.gross_margin),
                "price_reaction_pct": _round_or_none(quarter_analysis.price_reaction_pct),
            }
        )

    context = {
        "company": {
            "title": parsed.company.title,
            "ticker": parsed.company.ticker,
            "company_name": parsed.company.company_name,
            "description": _truncate(parsed.company.description or "", 400),
        },
        "scores": _compact_mapping(asdict(analysis.scores)),
        "market_data": _market_data_payload(market_data),
        "summary_metrics": _compact_mapping(analysis.summary_metrics),
        "recent_quarters": quarters,
        "trend_signals": [_compact_mapping(asdict(trend)) for trend in analysis.trends[:8]],
        "risk_indicators": [_truncate(item, 180) for item in analysis.risk_indicators[:8]],
        "loaded_workbook_comparison": _comparison_payload(comparison_workbooks, parsed),
    }
    return json.dumps(context, default=_json_default, separators=(", ", ": "))


def build_system_prompt() -> str:
    """Return the standing instructions for the stock research assistant."""

    return (
        "You are a concise equity research copilot inside a local Streamlit app. "
        "Use only the provided workbook data, deterministic analysis results, and Yahoo Finance market data. "
        "Write like a senior equity analyst advising an internal research team: direct, specific, evidence-based, and brief. "
        "Give a clear research opinion when the evidence supports one, but write it in plain English rather than rating labels or percentage confidence. "
        "Lead with the conclusion, then explain the two or three facts that drive it. Use phrases like 'I would lean constructive', 'I would be cautious', or 'the data is not strong enough to take a firm view'. "
        "Mention important counterpoints, but do not default to a balanced bull-case/bear-case format unless the user explicitly asks for that format. "
        "Write in polished normal prose with spaces between words and punctuation; do not use Markdown, tables, code formatting, LaTeX/math formatting, or copied JSON formatting. "
        "Do not invent facts, prices, targets, or financial figures. Distinguish historical workbook metrics from live market data. "
        "Do not add generic financial-advice disclaimers or boilerplate. "
        "If asked for a buy/sell decision, frame the answer as an internal research opinion based on the supplied evidence, not as personalized client advice."
    )


def build_user_payload(context: str, chat_history: list[dict[str, str]], question: str) -> str:
    """Combine context, short chat history, and the current question."""

    recent_history = chat_history[-2:]
    history_text = "\n".join(
        f"{item['role']}: {_truncate(item['content'], 300)}"
        for item in recent_history
    )
    return (
        "Evidence packet:\n"
        f"{context}\n\n"
        "Recent conversation:\n"
        f"{history_text or 'None'}\n\n"
        "Formatting instruction:\n"
        "Answer in clean readable prose. Do not copy raw JSON formatting from the evidence packet.\n\n"
        "User question:\n"
        f"{question}"
    )


def _market_data_payload(market_data: MarketDataSnapshot | None) -> dict[str, Any] | None:
    if market_data is None:
        return None
    return {
        "provider": market_data.provider,
        "ticker": market_data.ticker,
        "as_of": market_data.as_of.isoformat(),
        "quote": asdict(market_data.quote),
        "analyst_targets": asdict(market_data.analyst_targets) if market_data.analyst_targets else None,
        "history_rows": [
            {"date": row.date, "close": _round_or_none(row.close), "volume": row.volume}
            for row in market_data.history[-8:]
        ],
        "news": [
            {
                "title": _truncate(item.title, 160),
                "publisher": item.publisher,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "summary": _truncate(item.summary or "", 700) or None,
                "link": item.link,
            }
            for item in market_data.news[:5]
        ],
        "metadata": market_data.metadata,
        "warnings": market_data.warnings[:4],
    }


def _comparison_payload(
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None,
    active_parsed: ParsedWorkbook,
) -> list[dict[str, Any]]:
    if not comparison_workbooks or len(comparison_workbooks) < 2:
        return []

    rows = []
    for display_name, parsed, analysis in comparison_workbooks:
        latest = _latest_historical_pair(parsed, analysis)
        quarter, quarter_analysis = latest if latest else (None, None)
        rows.append(
            {
                "active": parsed.company.workbook_path == active_parsed.company.workbook_path,
                "file": display_name,
                "ticker": parsed.company.ticker,
                "company": parsed.company.company_name or parsed.company.title,
                "latest_quarter": quarter.quarter_label if quarter else None,
                "scores": _compact_mapping(asdict(analysis.scores)),
                "latest_revenue_yoy_growth": _round_or_none(quarter_analysis.revenue_yoy_growth) if quarter_analysis else None,
                "latest_eps_yoy_growth": _round_or_none(quarter_analysis.eps_yoy_growth) if quarter_analysis else None,
                "risk_count": len(analysis.risk_indicators),
            }
        )
    return rows


def _latest_historical_pair(parsed: ParsedWorkbook, analysis: AnalysisResult):
    for quarter, quarter_analysis in zip(parsed.quarters, analysis.quarter_analyses):
        if is_historical_quarter(quarter) and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None):
            return quarter, quarter_analysis
    return None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _round_or_none(value: Any, digits: int = 2) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _compact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    compact = {}
    for key, value in payload.items():
        if value is None or value == "":
            continue
        if isinstance(value, float):
            compact[key] = round(value, 2)
        elif isinstance(value, str):
            compact[key] = _truncate(value, 180)
        else:
            compact[key] = value
    return compact


def _json_default(value: Any) -> str | float | int | None:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
