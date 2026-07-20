"""Deterministic financial analysis for parsed stock workbooks."""

from __future__ import annotations

from dataclasses import replace
from statistics import mean, pstdev
from typing import Any

from stock_research.dataclasses import (
    AnalysisResult,
    ParsedWorkbook,
    QuarterAnalysis,
    QuarterRecord,
    ScoreBreakdown,
    TrendSignal,
    is_historical_quarter,
)


def analyze_workbook(parsed: ParsedWorkbook) -> AnalysisResult:
    """Calculate deterministic metrics, trend flags, risks, and scores."""

    quarter_analyses = tuple(_analyze_quarter(parsed.quarters, index) for index in range(len(parsed.quarters)))
    scores = _score(parsed.quarters, quarter_analyses)
    trends = tuple(_detect_trends(parsed.quarters, quarter_analyses))
    risks = tuple(_detect_risks(parsed.quarters, quarter_analyses))
    summary_metrics = _summary_metrics(parsed.quarters, quarter_analyses, scores)

    return AnalysisResult(
        company=parsed.company,
        quarter_analyses=quarter_analyses,
        scores=scores,
        trends=trends,
        risk_indicators=risks,
        summary_metrics=summary_metrics,
    )


def apply_market_overlay(analysis: AnalysisResult, market_data: Any | None) -> AnalysisResult:
    """Blend available Yahoo Finance data into the headline investment score."""

    market_score = _market_score(market_data)
    if market_score is None:
        return analysis

    original_overall = analysis.scores.overall_investment
    adjusted_overall = _clamp_score((0.75 * original_overall) + (0.25 * market_score))
    adjusted_scores = replace(analysis.scores, overall_investment=round(adjusted_overall, 1))

    summary_metrics = dict(analysis.summary_metrics)
    summary_metrics.update(
        {
            "workbook_only_score": original_overall,
            "market_score": round(market_score, 1),
            "overall_investment_score": adjusted_scores.overall_investment,
            "target_upside_pct": _target_upside(market_data),
            "market_data_included": True,
        }
    )
    return replace(analysis, scores=adjusted_scores, summary_metrics=summary_metrics)


def _analyze_quarter(quarters: tuple[QuarterRecord, ...], index: int) -> QuarterAnalysis:
    quarter = quarters[index]
    prior_quarter = quarters[index + 1] if index + 1 < len(quarters) else None
    year_ago_quarter = quarters[index + 4] if index + 4 < len(quarters) else None

    return QuarterAnalysis(
        row_number=quarter.row_number,
        quarter_label=quarter.quarter_label,
        revenue_surprise_pct=_pct_difference(quarter.revenue_actual_millions, quarter.revenue_estimate_millions),
        eps_surprise_pct=_pct_difference(quarter.eps_actual, quarter.eps_estimate, use_abs_denominator=True),
        revenue_qoq_growth=_growth(quarter.revenue_actual_millions, prior_quarter.revenue_actual_millions if prior_quarter else None),
        revenue_yoy_growth=_growth(quarter.revenue_actual_millions, year_ago_quarter.revenue_actual_millions if year_ago_quarter else None),
        eps_qoq_growth=_growth(quarter.eps_actual, prior_quarter.eps_actual if prior_quarter else None, use_abs_denominator=True),
        eps_yoy_growth=_growth(quarter.eps_actual, year_ago_quarter.eps_actual if year_ago_quarter else None, use_abs_denominator=True),
        rolling_revenue_growth=_growth(
            quarter.rolling_4q_revenue_millions,
            year_ago_quarter.rolling_4q_revenue_millions if year_ago_quarter else None,
        ),
        rolling_eps_growth=_growth(
            quarter.rolling_4q_eps,
            year_ago_quarter.rolling_4q_eps if year_ago_quarter else None,
            use_abs_denominator=True,
        ),
        gross_margin=_find_metric(quarter, ("gross margin %", "gross margin")),
        operating_margin=_find_metric(quarter, ("operating margin", "op margin")),
        net_margin=_find_metric(quarter, ("net margin",)),
        price_reaction_pct=_price_reaction(quarter),
    )


def _score(quarters: tuple[QuarterRecord, ...], analyses: tuple[QuarterAnalysis, ...]) -> ScoreBreakdown:
    usable_pairs = [
        (quarter, analysis)
        for quarter, analysis in zip(quarters, analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]
    usable_quarters = [quarter for quarter, _analysis in usable_pairs]
    usable_analyses = [analysis for _quarter, analysis in usable_pairs]
    recent = usable_analyses[:8]
    recent_quarters = usable_quarters[:8]

    revenue_beat_rate = _positive_rate(item.revenue_surprise_pct for item in recent)
    eps_beat_rate = _positive_rate(item.eps_surprise_pct for item in recent)
    avg_positive_surprise = _average(
        _clamp(value, -0.25, 0.25)
        for item in recent
        for value in (item.revenue_surprise_pct, item.eps_surprise_pct)
        if value is not None
    )
    historical_execution = _clamp_score(50 + 35 * ((revenue_beat_rate + eps_beat_rate) / 2 - 0.5) + 60 * avg_positive_surprise)

    revenue_growth = _average(item.revenue_yoy_growth for item in recent if item.revenue_yoy_growth is not None)
    rolling_growth = _average(item.rolling_revenue_growth for item in recent if item.rolling_revenue_growth is not None)
    acceleration = _acceleration([item.revenue_yoy_growth for item in usable_analyses])
    growth = _clamp_score(50 + 80 * revenue_growth + 40 * rolling_growth + 25 * acceleration)

    profitability_base = _profitability_base(usable_quarters, usable_analyses)
    margin_change = _latest_vs_prior_average([_best_margin_signal(quarter, analysis) for quarter, analysis in usable_pairs])
    profitability = _clamp_score(45 + 70 * profitability_base + 45 * margin_change)

    eps_growth = _average(item.eps_yoy_growth for item in recent if item.eps_yoy_growth is not None)
    financial_quality = _clamp_score(0.35 * growth + 0.35 * profitability + 30 + 30 * eps_growth)

    analyst_accuracy = 1 - _average(
        abs(value)
        for item in recent
        for value in (item.revenue_surprise_pct, item.eps_surprise_pct)
        if value is not None
    )
    positive_reaction_rate = _positive_rate(item.price_reaction_pct for item in recent if item.price_reaction_pct is not None)
    management_execution = _clamp_score(
        35 * ((revenue_beat_rate + eps_beat_rate) / 2)
        + 35 * analyst_accuracy
        + 30 * positive_reaction_rate
    )

    if not any(q.price_before_earnings and q.price_after_earnings for q in recent_quarters):
        management_execution = _clamp_score(0.75 * management_execution + 12.5)

    overall = _clamp_score(
        0.25 * historical_execution
        + 0.25 * growth
        + 0.2 * profitability
        + 0.15 * financial_quality
        + 0.15 * management_execution
    )

    return ScoreBreakdown(
        historical_execution=round(historical_execution, 1),
        growth=round(growth, 1),
        profitability=round(profitability, 1),
        financial_quality=round(financial_quality, 1),
        management_execution=round(management_execution, 1),
        overall_investment=round(overall, 1),
    )


def _detect_trends(
    quarters: tuple[QuarterRecord, ...],
    analyses: tuple[QuarterAnalysis, ...],
) -> list[TrendSignal]:
    trends: list[TrendSignal] = []

    usable = _usable_analyses(quarters, analyses)
    revenue_acceleration = _acceleration([item.revenue_yoy_growth for item in usable])
    if revenue_acceleration > 0.02:
        trends.append(TrendSignal("Revenue growth", "accelerating", "Recent revenue growth is stronger than the prior period.", revenue_acceleration))
    elif revenue_acceleration < -0.02:
        trends.append(TrendSignal("Revenue growth", "slowing", "Recent revenue growth is weaker than the prior period.", revenue_acceleration))

    gross_margin_change = _latest_vs_prior_average([item.gross_margin for item in usable])
    if gross_margin_change > 0.01:
        trends.append(TrendSignal("Gross margins", "expanding", "Recent gross margins are above the prior-period average.", gross_margin_change))
    elif gross_margin_change < -0.01:
        trends.append(TrendSignal("Gross margins", "contracting", "Recent gross margins are below the prior-period average.", gross_margin_change))

    eps_surprise_volatility = _volatility([item.eps_surprise_pct for item in usable[:8]])
    prior_eps_surprise_volatility = _volatility([item.eps_surprise_pct for item in usable[8:16]])
    if eps_surprise_volatility is not None and prior_eps_surprise_volatility is not None:
        if eps_surprise_volatility < prior_eps_surprise_volatility:
            trends.append(TrendSignal("EPS consistency", "improving", "EPS surprise volatility has declined.", prior_eps_surprise_volatility - eps_surprise_volatility))
        elif eps_surprise_volatility > prior_eps_surprise_volatility:
            trends.append(TrendSignal("EPS consistency", "worsening", "EPS surprise volatility has increased.", eps_surprise_volatility - prior_eps_surprise_volatility))

    reaction_change = _latest_vs_prior_average([abs(item.price_reaction_pct) if item.price_reaction_pct is not None else None for item in usable])
    if reaction_change < -0.01:
        trends.append(TrendSignal("Price reaction", "less reactive", "Absolute post-earnings price reactions have decreased.", reaction_change))
    elif reaction_change > 0.01:
        trends.append(TrendSignal("Price reaction", "more reactive", "Absolute post-earnings price reactions have increased.", reaction_change))

    accuracy_change = _latest_vs_prior_average(
        [
            _average(
                abs(value)
                for value in (item.revenue_surprise_pct, item.eps_surprise_pct)
                if value is not None
            )
            for item in usable
        ]
    )
    if accuracy_change < -0.01:
        trends.append(TrendSignal("Analyst expectations", "more accurate", "Average revenue/EPS surprise magnitude has declined.", accuracy_change))
    elif accuracy_change > 0.01:
        trends.append(TrendSignal("Analyst expectations", "less accurate", "Average revenue/EPS surprise magnitude has increased.", accuracy_change))

    return trends


def _detect_risks(quarters: tuple[QuarterRecord, ...], analyses: tuple[QuarterAnalysis, ...]) -> list[str]:
    risks: list[str] = []
    usable_pairs = [
        (quarter, analysis)
        for quarter, analysis in zip(quarters, analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]
    usable = [analysis for _quarter, analysis in usable_pairs]
    recent = usable[:8]

    if _average(item.revenue_yoy_growth for item in recent if item.revenue_yoy_growth is not None) < 0:
        risks.append("Recent year-over-year revenue growth is negative.")

    if _acceleration([item.revenue_yoy_growth for item in usable]) < -0.05:
        risks.append("Revenue growth is decelerating meaningfully.")

    if _positive_rate(item.eps_surprise_pct for item in recent) < 0.5:
        risks.append("EPS beats have been inconsistent recently.")

    if _average(item.price_reaction_pct for item in recent if item.price_reaction_pct is not None) < 0:
        risks.append("Average post-earnings price reaction has been negative.")

    if _latest_vs_prior_average([item.gross_margin for item in usable]) < -0.02:
        risks.append("Gross margins are contracting versus the prior period.")

    revenue_misses = sum(
        1 for item in recent[:4] if item.revenue_surprise_pct is not None and item.revenue_surprise_pct < -0.02
    )
    if revenue_misses:
        label = "quarter" if revenue_misses == 1 else "quarters"
        count_label = "One" if revenue_misses == 1 else str(revenue_misses)
        risks.append(f"{count_label} recent {label} missed revenue expectations by more than 2%.")

    return risks


def _market_score(market_data: Any | None) -> float | None:
    if market_data is None:
        return None

    quote = getattr(market_data, "quote", None)
    if quote is None:
        return None

    score = 50.0
    components = 0

    target_upside = _target_upside(market_data)
    if target_upside is not None:
        score += _clamp(target_upside, -0.4, 0.4) * 70
        components += 1

    forward_pe = getattr(quote, "forward_pe", None)
    if forward_pe is not None and forward_pe > 0:
        if forward_pe <= 20:
            score += 9
        elif forward_pe <= 35:
            score += 4
        elif forward_pe >= 70:
            score -= 13
        elif forward_pe >= 50:
            score -= 8
        components += 1

    current_price = getattr(quote, "current_price", None)
    low = getattr(quote, "fifty_two_week_low", None)
    high = getattr(quote, "fifty_two_week_high", None)
    if current_price is not None and low is not None and high is not None and high > low:
        range_position = (current_price - low) / (high - low)
        if range_position <= 0.25:
            score += 5
        elif range_position >= 0.85 and (target_upside is None or target_upside < 0.08):
            score -= 6
        components += 1

    recommendation = None
    targets = getattr(market_data, "analyst_targets", None)
    if targets is not None:
        recommendation = getattr(targets, "recommendation", None)
    if isinstance(recommendation, str):
        lowered = recommendation.lower()
        if "buy" in lowered:
            score += 4
        elif "sell" in lowered or "underperform" in lowered:
            score -= 8
        elif "hold" in lowered:
            score -= 2
        components += 1

    return _clamp_score(score) if components else None


def _target_upside(market_data: Any | None) -> float | None:
    if market_data is None:
        return None
    quote = getattr(market_data, "quote", None)
    targets = getattr(market_data, "analyst_targets", None)
    if quote is None or targets is None:
        return None
    current_price = getattr(quote, "current_price", None)
    target_price = getattr(targets, "mean", None) or getattr(targets, "median", None)
    if current_price is None or target_price is None or current_price <= 0:
        return None
    return (target_price - current_price) / current_price


def _summary_metrics(
    quarters: tuple[QuarterRecord, ...],
    analyses: tuple[QuarterAnalysis, ...],
    scores: ScoreBreakdown,
) -> dict[str, float | int | str | None]:
    usable_pairs = [
        (quarter, analysis)
        for quarter, analysis in zip(quarters, analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]
    latest_quarter, latest = usable_pairs[0] if usable_pairs else (None, None)
    return {
        "quarter_count": len(usable_pairs),
        "parsed_quarter_count": len(quarters),
        "latest_quarter": latest_quarter.quarter_label if latest_quarter else None,
        "latest_revenue_millions": latest_quarter.revenue_actual_millions if latest_quarter else None,
        "latest_eps": latest_quarter.eps_actual if latest_quarter else None,
        "latest_revenue_yoy_growth": latest.revenue_yoy_growth if latest else None,
        "latest_eps_yoy_growth": latest.eps_yoy_growth if latest else None,
        "latest_price_reaction_pct": latest.price_reaction_pct if latest else None,
        "overall_investment_score": scores.overall_investment,
    }


def _find_metric(quarter: QuarterRecord, names: tuple[str, ...]) -> float | None:
    for name in names:
        for metric in quarter.additional_metrics:
            metric_name = metric.name.lower()
            if name not in metric_name:
                continue
            value = _to_float(metric.value)
            if value is None:
                continue
            if "margin" in metric_name and "%" not in metric_name and not -1 <= value <= 1:
                continue
            if "margin" in metric_name and "%" in metric_name and value > 1:
                return value / 100
            return value
    return None


def _profitability_base(quarters: list[QuarterRecord], analyses: list[QuarterAnalysis]) -> float:
    """Return the latest available profitability signal, falling back gracefully."""

    latest_signal = _latest_non_null(_best_margin_signal(quarter, analysis) for quarter, analysis in zip(quarters, analyses))
    if latest_signal is not None:
        return latest_signal

    earnings_margin = _latest_non_null(
        _earnings_margin_signal(quarter)
        for quarter in quarters
    )
    if earnings_margin is not None:
        return earnings_margin

    return 0.10


def _best_margin_signal(quarter: QuarterRecord, analysis: QuarterAnalysis) -> float | None:
    candidates = [
        analysis.gross_margin,
        analysis.operating_margin,
        analysis.net_margin,
        _find_metric(quarter, ("gross margin", "gm")),
        _find_metric(quarter, ("operating margin", "op margin", "oper margin", "ebit margin")),
        _find_metric(quarter, ("net margin",)),
        _segment_margin(quarter),
        _earnings_margin_signal(quarter),
    ]
    return _latest_non_null(candidates)


def _segment_margin(quarter: QuarterRecord) -> float | None:
    margin_metrics = [
        _to_percent_decimal(metric.value)
        for metric in quarter.additional_metrics
        if "margin" in metric.name.lower()
    ]
    margin_metrics = [value for value in margin_metrics if value is not None]
    if margin_metrics:
        return max(margin_metrics)

    income_values = [
        _to_float(metric.value)
        for metric in quarter.additional_metrics
        if any(term in metric.name.lower() for term in ("operating income", "op income", "ebit"))
    ]
    revenue_values = [
        _to_float(metric.value)
        for metric in quarter.additional_metrics
        if any(term in metric.name.lower() for term in ("revenue", "rev.", "net sales", "sales"))
    ]
    income_values = [value for value in income_values if value is not None and value > 0]
    revenue_values = [value for value in revenue_values if value is not None and value > 0]
    if income_values and revenue_values:
        return _reasonable_margin(_ratio_or_none(max(income_values), max(revenue_values)))
    return None


def _to_percent_decimal(value: object) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if numeric > 1:
        numeric = numeric / 100
    if -1 <= numeric <= 1:
        return numeric
    return None


def _ratio_or_none(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _earnings_margin_signal(quarter: QuarterRecord) -> float | None:
    return _reasonable_margin(_ratio_or_none(quarter.total_earnings_millions, quarter.revenue_actual_millions))


def _reasonable_margin(value: float | None) -> float | None:
    if value is None:
        return None
    if not -0.5 <= value <= 1.5:
        return None
    return _clamp(value, -0.2, 0.45)


def _usable_analyses(
    quarters: tuple[QuarterRecord, ...],
    analyses: tuple[QuarterAnalysis, ...],
) -> list[QuarterAnalysis]:
    return [
        analysis
        for quarter, analysis in zip(quarters, analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]


def _price_reaction(quarter: QuarterRecord) -> float | None:
    calculated = _pct_difference(quarter.price_after_earnings, quarter.price_before_earnings)
    return calculated if calculated is not None else quarter.workbook_price_reaction_pct


def _pct_difference(actual: float | None, estimate: float | None, use_abs_denominator: bool = False) -> float | None:
    if actual is None or estimate is None:
        return None
    denominator = abs(estimate) if use_abs_denominator else estimate
    if denominator == 0:
        return None
    return (actual - estimate) / denominator


def _growth(current: float | None, prior: float | None, use_abs_denominator: bool = False) -> float | None:
    if current is None or prior is None:
        return None
    denominator = abs(prior) if use_abs_denominator else prior
    if denominator == 0:
        return None
    return (current - prior) / denominator


def _to_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _average(values) -> float:
    valid = [value for value in values if value is not None]
    if not valid:
        return 0.0
    return mean(valid)


def _positive_rate(values) -> float:
    valid = [value for value in values if value is not None]
    if not valid:
        return 0.5
    return sum(1 for value in valid if value > 0) / len(valid)


def _latest_non_null(values) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _latest_vs_prior_average(values: list[float | None], window: int = 4) -> float:
    valid_latest = [value for value in values[:window] if value is not None]
    valid_prior = [value for value in values[window : window * 2] if value is not None]
    if not valid_latest or not valid_prior:
        return 0.0
    return mean(valid_latest) - mean(valid_prior)


def _acceleration(values: list[float | None], window: int = 4) -> float:
    return _latest_vs_prior_average(values, window=window)


def _volatility(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if len(valid) < 2:
        return None
    return pstdev(valid)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _clamp_score(value: float) -> float:
    return _clamp(value, 0.0, 100.0)
