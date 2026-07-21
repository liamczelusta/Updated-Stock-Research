"""Streamlit dashboard views for parsed stock workbooks."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path
import os
import math
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from stock_research.analysis_engine import apply_market_overlay
from stock_research.ai.context import build_ai_context, build_system_prompt, build_user_payload
from stock_research.ai.providers import AIProviderError, AISettings, create_ai_client
from stock_research.dataclasses import AnalysisResult, ParsedWorkbook, QuarterAnalysis, QuarterRecord, is_estimate_quarter_label, is_historical_quarter
from stock_research.local_secrets import delete_local_secret, load_local_secret, save_local_secret
from stock_research.market_data import MarketDataError, MarketDataSnapshot, YahooFinanceProvider
from stock_research.preferences import AppPreferences
from stock_research.reporting import (
    ExecutiveSummary,
    build_complete_report_text,
    build_executive_summary,
    build_pdf,
)


POSITIVE = "#43d18c"
NEGATIVE = "#ff6b6b"
NEUTRAL = "#9ca3af"
BLUE = "#6ea8fe"
CYAN = "#38d9e6"
GOLD = "#f6c85f"
PURPLE = "#b197fc"
FORECAST = "#2dd4bf"
FORECAST_MARKER = FORECAST
PLOT_BG = "#101820"
PAPER_BG = "#0b1117"
GRID = "rgba(148, 163, 184, 0.18)"
AI_PROVIDER = "Anthropic"
AI_KEY_ENV_NAME = "ANTHROPIC_API_KEY"
AI_MODELS = {
    "Haiku - fastest / cheapest": "claude-haiku-4-5-20251001",
    "Sonnet - stronger analysis": "claude-sonnet-5",
    "Opus - most powerful": "claude-opus-4-8",
    "Fable - deepest analysis": "claude-fable-5",
}
DEFAULT_AI_MODEL_LABEL = "Haiku - fastest / cheapest"


def render_empty_state(preferences: AppPreferences | None = None, error: str | None = None) -> None:
    """Render the first screen before a workbook is loaded."""

    _apply_theme()
    recent_hint = ""
    if preferences and preferences.recent_files:
        recent_hint = f"<p class=\"hero-copy\">Recent folder: {preferences.last_folder or 'N/A'}</p>"
    error_html = f'<div class="error-panel">{error}</div>' if error else ""
    st.markdown(
        f"""
        <section class="app-hero">
            <div>
                <p class="eyebrow">Internal equity research</p>
                <h1>Stock Research Dashboard</h1>
                <p class="hero-copy">Drop one or more standardized Excel workbooks in the sidebar. The analysis, summary, market data, and chat will load automatically.</p>
                {recent_hint}
                {error_html}
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None = None,
) -> None:
    """Render the full dashboard for one parsed workbook."""

    _apply_theme()
    quarters_df = _quarters_dataframe(parsed, analysis)
    additional_df = _additional_metrics_dataframe(parsed)
    market_data: MarketDataSnapshot | None = None

    usable_df = quarters_df[
        quarters_df["revenue_actual_millions"].notna() | quarters_df["eps_actual"].notna()
    ].copy()
    usable_df = _historical_rows(usable_df)
    if usable_df.empty:
        usable_df = quarters_df.copy()

    with st.sidebar:
        provider = AI_PROVIDER
        saved_api_key = load_local_secret(AI_KEY_ENV_NAME)
        api_key = _api_key_for(AI_KEY_ENV_NAME) or saved_api_key
        st.subheader("Current workbook")
        st.caption(parsed.company.workbook_path.name)
        if comparison_workbooks and len(comparison_workbooks) > 1:
            st.caption(f"{len(comparison_workbooks)} workbooks loaded")

        st.divider()
        st.subheader("AI")
        model_label = st.selectbox(
            "Model",
            list(AI_MODELS),
            index=list(AI_MODELS).index(DEFAULT_AI_MODEL_LABEL),
            help="Use Haiku for routine work, Sonnet for stronger judgment, Opus or Fable only for deeper reviews.",
        )
        model = AI_MODELS[model_label]
        max_tokens = st.slider("Response length", min_value=100, max_value=3000, value=1500, step=100)
        if api_key:
            st.caption("Claude connected")
        else:
            st.caption("Add a Claude key in Advanced once to use chat.")

        st.divider()
        st.subheader("Market data")
        fetch_market_data = st.toggle("Yahoo Finance", value=True)
        market_period = st.selectbox("Price history", ["6mo", "1y", "2y", "5y"], index=1, disabled=not fetch_market_data)

        with st.expander("Advanced"):
            app_theme = st.radio("Display", ["Dark", "Light"], index=0, horizontal=True)
            max_quarters = max(4, min(len(usable_df), 80))
            default_quarters = min(16, max_quarters)
            quarter_count = st.slider("Quarters shown", min_value=4, max_value=max_quarters, value=default_quarters)
            show_forecast_extension = st.toggle("Show forecast extension", value=True)
            api_key_input = st.text_input("Claude API key", type="password", value="")
            if st.button("Save Claude key on this computer", disabled=not bool(api_key_input.strip())):
                save_local_secret(AI_KEY_ENV_NAME, api_key_input)
                st.success("Saved locally for this computer.")
                st.rerun()
            if saved_api_key and not _api_key_for(AI_KEY_ENV_NAME):
                if st.button("Forget saved Claude key"):
                    delete_local_secret(AI_KEY_ENV_NAME)
                    st.rerun()
            api_key = api_key_input or _api_key_for(AI_KEY_ENV_NAME) or load_local_secret(AI_KEY_ENV_NAME)

        if "quarter_count" not in locals():
            app_theme = "Dark"
            max_quarters = max(4, min(len(usable_df), 80))
            quarter_count = min(16, max_quarters)
            show_forecast_extension = True
            fetch_market_data = True
            market_period = "1y"

        st.divider()
        if fetch_market_data:
            try:
                ticker = parsed.company.ticker or ""
                with st.spinner("Loading market data"):
                    market_data = _cached_market_snapshot(
                        ticker,
                        market_period,
                        _api_key_for("FINNHUB_API_KEY"),
                    )
                st.caption(f"{market_data.provider}: {market_data.ticker}")
                if market_data.warnings:
                    st.caption("Some market or news fields were not available.")
            except MarketDataError as exc:
                st.caption("Market data could not load right now.")
                with st.expander("Details"):
                    st.caption(str(exc))

        ai_settings = AISettings(
            provider=provider.lower(),
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
        )

    _apply_theme(str(app_theme or "Dark"))
    analysis = apply_market_overlay(analysis, market_data)
    latest_df = usable_df.head(quarter_count)
    forecast_df = _forecast_rows(quarters_df)
    chart_df = _chart_rows(usable_df, forecast_df, quarter_count, show_forecast_extension)

    _render_header(parsed, analysis, usable_df)
    summary = build_executive_summary(parsed, analysis, market_data)
    _render_executive_summary(parsed, analysis, market_data, summary, ai_settings, comparison_workbooks)
    _render_scorecards(analysis)
    _render_workbook_comparison(comparison_workbooks)
    _render_overview(parsed, analysis, chart_df, latest_df, additional_df, market_data)

    st.markdown('<div class="section-title">Financial trends</div>', unsafe_allow_html=True)
    _render_financial_trends(chart_df, additional_df)

    with st.expander("Earnings surprises and price reactions"):
        _render_earnings_reaction(chart_df)

    st.markdown('<div class="section-title">Market snapshot</div>', unsafe_allow_html=True)
    _render_market_data(market_data, analysis)

    st.markdown('<div class="section-title">Ask follow-up questions</div>', unsafe_allow_html=True)
    _render_ai_chat(parsed, analysis, market_data, ai_settings, comparison_workbooks)

    with st.expander("Parsed workbook data"):
        _render_data_quality(parsed, quarters_df, additional_df)


def _render_header(parsed: ParsedWorkbook, analysis: AnalysisResult, usable_df: pd.DataFrame) -> None:
    company = parsed.company
    latest = analysis.summary_metrics
    subtitle_parts = [
        part
        for part in (
            company.company_name,
            company.description,
            f"{len(usable_df)} usable quarter rows",
        )
        if part
    ]
    st.markdown(
        f"""
        <section class="dashboard-header">
            <div>
                <p class="eyebrow">{company.ticker or "Stock"} research</p>
                <h1>{company.ticker or company.title}</h1>
                <p>{' / '.join(subtitle_parts)}</p>
            </div>
            <div class="header-stat">
                <span>Latest quarter</span>
                <strong>{latest.get("latest_quarter") or "N/A"}</strong>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_scorecards(analysis: AnalysisResult) -> None:
    scores = analysis.scores
    score_items = [
        (
            "Overall",
            scores.overall_investment,
            "Workbook + market" if analysis.summary_metrics.get("market_data_included") else "Workbook score",
            "The big-picture score. It blends the workbook results, growth, margins, execution, and market data when available.",
        ),
        (
            "Growth",
            scores.growth,
            "Revenue and EPS",
            "How well the company is growing. It looks at revenue, EPS, and whether recent growth is speeding up or slowing down.",
        ),
        (
            "Profitability",
            scores.profitability,
            "Margins",
            "How profitable the business looks. It focuses on gross margin, operating margin, net margin, and whether margins are improving.",
        ),
        (
            "Market",
            analysis.summary_metrics.get("market_score", 50.0),
            "Yahoo Finance" if analysis.summary_metrics.get("market_data_included") else "Not loaded",
            "How the live market setup looks. It considers valuation, 52-week price position, beta, analyst targets, and market reaction data when available.",
        ),
    ]

    columns = st.columns(4)
    for column, (label, value, caption, definition) in zip(columns, score_items):
        with column:
            _scorecard(label, value, caption, definition)


def _render_workbook_comparison(
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None,
) -> None:
    if not comparison_workbooks or len(comparison_workbooks) < 2:
        return

    rows = []
    for display_name, parsed, analysis in comparison_workbooks:
        latest = _latest_historical_pair(parsed, analysis)
        quarter, quarter_analysis = latest if latest else (None, None)
        rows.append(
            {
                "Workbook": parsed.company.ticker or Path(display_name).stem,
                "Company": parsed.company.company_name or parsed.company.title,
                "Latest quarter": quarter.quarter_label if quarter else None,
                "Workbook score": analysis.scores.overall_investment,
                "Growth": analysis.scores.growth,
                "Profitability": analysis.scores.profitability,
                "Execution": analysis.scores.historical_execution,
                "Revenue YoY": quarter_analysis.revenue_yoy_growth * 100 if quarter_analysis and quarter_analysis.revenue_yoy_growth is not None else None,
                "EPS YoY": quarter_analysis.eps_yoy_growth * 100 if quarter_analysis and quarter_analysis.eps_yoy_growth is not None else None,
            }
        )

    st.markdown('<div class="section-title">Workbook comparison</div>', unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Workbook score": st.column_config.NumberColumn("Workbook score", format="%.1f"),
            "Growth": st.column_config.NumberColumn("Growth", format="%.1f"),
            "Profitability": st.column_config.NumberColumn("Profitability", format="%.1f"),
            "Execution": st.column_config.NumberColumn("Execution", format="%.1f"),
            "Revenue YoY": st.column_config.NumberColumn("Revenue YoY", format="%.1f%%"),
            "EPS YoY": st.column_config.NumberColumn("EPS YoY", format="%.1f%%"),
        },
    )


def _latest_historical_pair(parsed: ParsedWorkbook, analysis: AnalysisResult):
    for quarter, quarter_analysis in zip(parsed.quarters, analysis.quarter_analyses):
        if is_historical_quarter(quarter) and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None):
            return quarter, quarter_analysis
    return None


def _render_executive_summary(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
    summary: ExecutiveSummary,
    ai_settings: AISettings,
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None = None,
) -> None:
    report_text = summary.as_text()
    complete_report = build_complete_report_text(parsed, analysis, market_data, summary)
    company_label = parsed.company.ticker or parsed.company.title or "stock"
    executive_pdf = build_pdf(f"{company_label} Executive Summary", report_text)
    complete_pdf = build_pdf(f"{company_label} Complete Report", complete_report)

    left, right = st.columns([1.55, 0.75])
    with left:
        st.markdown(
            f"""
            <section class="summary-panel">
                <p class="eyebrow">Executive summary</p>
                <h2>{escape(summary.headline)}</h2>
                <div class="summary-columns">
                    <div>
                        <span>Strengths</span>
                        <ul>{''.join(f'<li>{escape(item)}</li>' for item in summary.strengths)}</ul>
                    </div>
                    <div>
                        <span>Risks / watch items</span>
                        <ul>{''.join(f'<li>{escape(item)}</li>' for item in summary.risks)}</ul>
                    </div>
                </div>
                <p class="summary-conclusion">{escape(summary.conclusion)}</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown('<div class="section-title compact">Actions</div>', unsafe_allow_html=True)
        _copy_button("Copy Executive Summary", report_text, "copy_executive_summary")
        st.download_button(
            "Export Executive Summary PDF",
            data=executive_pdf,
            file_name=f"{_safe_filename(company_label)}_executive_summary.pdf",
            mime="application/pdf",
            width="stretch",
        )
        st.download_button(
            "Export Complete Report PDF",
            data=complete_pdf,
            file_name=f"{_safe_filename(company_label)}_complete_report.pdf",
            mime="application/pdf",
            width="stretch",
        )

    _render_ai_summary(parsed, analysis, market_data, ai_settings, fallback_summary=report_text, comparison_workbooks=comparison_workbooks)


def _render_ai_summary(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
    ai_settings: AISettings,
    fallback_summary: str,
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None = None,
) -> None:
    st.markdown('<div class="section-title">AI analyst memo</div>', unsafe_allow_html=True)
    summary_key = (
        f"ai_summary_{parsed.company.workbook_path}_"
        f"{analysis.scores.overall_investment}_{ai_settings.model}_{ai_settings.max_tokens}"
    )
    button_label = "Regenerate AI Memo" if summary_key in st.session_state else "Generate AI Memo"
    generate_memo = st.button(button_label, type="primary", disabled=not bool(ai_settings.api_key))

    if not ai_settings.api_key:
        st.markdown(
            '<div class="muted-panel">Add a Claude API key before generating the AI memo.</div>',
            unsafe_allow_html=True,
        )
        return

    if generate_memo:
        with st.spinner("Generating AI summary"):
            try:
                context = build_ai_context(
                    parsed,
                    analysis,
                    market_data,
                    max_quarters=6,
                    comparison_workbooks=comparison_workbooks,
                )
                payload = build_user_payload(
                    context,
                    [],
                    _with_length_instruction(
                        "Write a concise executive analyst memo. Start with one direct sentence stating our overall view in plain English. Then give 4-5 bullets covering the key drivers, risks, market context, and what to watch next. Do not use percentage confidence labels or Positive/Neutral/Negative rating labels. Use only the evidence packet.",
                        ai_settings.max_tokens,
                    ),
                )
                client = create_ai_client(ai_settings)
                st.session_state[summary_key] = _clean_ai_response(
                    client.complete(build_system_prompt(), payload)
                )
            except Exception as exc:
                st.session_state[summary_key] = f"AI memo could not be generated: {exc}"

    memo = st.session_state.get(summary_key)
    if memo:
        st.markdown(f'<div class="ai-memo">{escape(memo).replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
        _copy_button("Copy AI Response", memo, "copy_ai_summary")
    else:
        st.markdown(
            '<div class="muted-panel">AI memo is optional. Generate it when you want Claude to write the analyst summary.</div>',
            unsafe_allow_html=True,
        )


def _render_overview(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    chart_df: pd.DataFrame,
    latest_df: pd.DataFrame,
    additional_df: pd.DataFrame,
    market_data: MarketDataSnapshot | None,
) -> None:
    metric_columns = st.columns(4)
    latest = latest_df.iloc[0] if not latest_df.empty else None
    with metric_columns[0]:
        _metric_tile("Latest revenue", _money(latest["revenue_actual_millions"]) if latest is not None else "N/A")
    with metric_columns[1]:
        _metric_tile("Latest EPS", _number(latest["eps_actual"]) if latest is not None else "N/A")
    with metric_columns[2]:
        _metric_tile("Revenue YoY", _pct(latest["revenue_yoy_growth"]) if latest is not None else "N/A")
    with metric_columns[3]:
        current_price = market_data.quote.current_price if market_data else None
        _metric_tile("Current price", _price(current_price, market_data.quote.currency if market_data else None))

    _render_forecast_note(chart_df)

    st.plotly_chart(
        _actual_estimate_forecast_chart(
            chart_df,
            title="Revenue: actual vs estimate",
            actual_label="Actual revenue",
            actual_column="revenue_actual_millions",
            estimate_label="Revenue estimate",
            estimate_column="revenue_estimate_millions",
            y_title="Revenue ($M)",
        ),
        width="stretch",
    )

    _render_market_strip(market_data, analysis)

    st.markdown('<div class="section-title">Key signals</div>', unsafe_allow_html=True)
    _trend_grid(analysis, limit=3)

    visible_risks = _visible_risks(analysis.risk_indicators)
    if visible_risks:
        st.markdown('<div class="section-title">Watch items</div>', unsafe_allow_html=True)
        for risk in visible_risks:
            st.markdown(f'<div class="risk-row">{risk}</div>', unsafe_allow_html=True)


def _render_forecast_note(chart_df: pd.DataFrame) -> None:
    forecast = _forecast_rows(chart_df)
    if forecast.empty:
        return
    next_row = forecast.sort_values("order", ascending=False).iloc[0]
    details = []
    if pd.notna(next_row.get("revenue_actual_millions")):
        details.append(f"revenue {_money(next_row['revenue_actual_millions'])}")
    elif pd.notna(next_row.get("revenue_estimate_millions")):
        details.append(f"revenue estimate {_money(next_row['revenue_estimate_millions'])}")
    if pd.notna(next_row.get("eps_actual")):
        details.append(f"EPS {_number(next_row['eps_actual'])}")
    elif pd.notna(next_row.get("eps_estimate")):
        details.append(f"EPS estimate {_number(next_row['eps_estimate'])}")

    detail_text = f" Next forecast: {next_row['quarter_label']} / {', '.join(details)}." if details else ""
    st.markdown(
        f'<div class="muted-panel forecast-note">Showing {len(forecast)} forecast quarter(s) as the dashed forecast extension.{escape(detail_text)}</div>',
        unsafe_allow_html=True,
    )


def _render_financial_trends(chart_df: pd.DataFrame, additional_df: pd.DataFrame) -> None:
    revenue_col, eps_col = st.columns(2)
    with revenue_col:
        st.plotly_chart(
            _line_chart(
                chart_df,
                title="Revenue growth",
                series={
                    "YoY growth": ("revenue_yoy_growth", BLUE),
                    "Rolling growth": ("rolling_revenue_growth", GOLD),
                },
                y_title="Growth",
                percent_axis=True,
                height=310,
                split_forecast=True,
            ),
            width="stretch",
        )
    with eps_col:
        st.plotly_chart(
            _line_chart(
                chart_df,
                title="EPS growth",
                series={
                    "YoY growth": ("eps_yoy_growth", BLUE),
                    "Rolling growth": ("rolling_eps_growth", GOLD),
                },
                y_title="Growth",
                percent_axis=True,
                height=310,
                split_forecast=True,
            ),
            width="stretch",
        )

    rolling_col, margin_col = st.columns(2)
    with rolling_col:
        st.plotly_chart(
            _line_chart(
                chart_df,
                title="Rolling four-quarter revenue",
                series={
                    "Rolling revenue": ("rolling_4q_revenue_millions", BLUE),
                },
                y_title="Revenue ($M)",
                height=310,
                split_forecast=True,
            ),
            width="stretch",
        )
    with margin_col:
        margin_df = chart_df[["quarter_label", "gross_margin", "operating_margin", "net_margin"]].copy()
        if margin_df[["gross_margin", "operating_margin", "net_margin"]].notna().any().any():
            st.plotly_chart(
                _line_chart(
                    chart_df,
                    title="Margins",
                    series={
                        "Gross margin": ("gross_margin", POSITIVE),
                        "Operating margin": ("operating_margin", BLUE),
                        "Net margin": ("net_margin", GOLD),
                    },
                    y_title="Margin",
                    percent_axis=True,
                    height=310,
                ),
                width="stretch",
            )
        else:
            st.markdown('<div class="muted-panel">Margin data was not available in this workbook.</div>', unsafe_allow_html=True)

    numeric_metrics = _numeric_additional_metrics(additional_df)
    if numeric_metrics:
        with st.expander("Additional workbook metrics"):
            selected_metric = st.selectbox("Metric", numeric_metrics)
            metric_chart_df = additional_df[additional_df["metric_name"] == selected_metric].copy()
            metric_chart_df = metric_chart_df.sort_values("order", ascending=False)
            st.plotly_chart(
                _single_series_chart(metric_chart_df, selected_metric, "value_numeric", selected_metric),
                width="stretch",
            )


def _render_earnings_reaction(chart_df: pd.DataFrame) -> None:
    surprise_col, price_col = st.columns(2)
    with surprise_col:
        st.plotly_chart(
            _bar_chart(
                chart_df,
                title="Revenue and EPS surprises",
                series={
                    "Revenue surprise": ("revenue_surprise_pct", BLUE),
                    "EPS surprise": ("eps_surprise_pct", GOLD),
                },
                y_title="Surprise",
                percent_axis=True,
            ),
            width="stretch",
        )
    with price_col:
        st.plotly_chart(
            _bar_chart(
                chart_df,
                title="Price reaction after earnings",
                series={"Price reaction": ("price_reaction_pct", PURPLE)},
                y_title="Price reaction",
                percent_axis=True,
            ),
            width="stretch",
        )

    st.plotly_chart(
        _actual_estimate_forecast_chart(
            chart_df,
            title="EPS: actual vs estimate",
            actual_label="Actual EPS",
            actual_column="eps_actual",
            estimate_label="EPS estimate",
            estimate_column="eps_estimate",
            y_title="EPS",
        ),
        width="stretch",
    )

    price_df = chart_df.dropna(subset=["price_before_earnings", "price_after_earnings"], how="all")
    if not price_df.empty:
        st.plotly_chart(
            _line_chart(
                price_df,
                title="Price before and after earnings",
                series={
                    "Before earnings": ("price_before_earnings", NEUTRAL),
                    "After earnings": ("price_after_earnings", BLUE),
                },
                y_title="Price",
            ),
            width="stretch",
        )


def _render_market_data(market_data: MarketDataSnapshot | None, analysis: AnalysisResult) -> None:
    if market_data is None:
        st.markdown(
            '<div class="muted-panel">Enable Yahoo Finance data in the sidebar to load live market data.</div>',
            unsafe_allow_html=True,
        )
        return

    quote = market_data.quote
    target = market_data.analyst_targets
    target_upside = analysis.summary_metrics.get("target_upside_pct")
    top_columns = st.columns(4)
    with top_columns[0]:
        _metric_tile("Current price", _price(quote.current_price, quote.currency))
    with top_columns[1]:
        _metric_tile("Market cap", _large_money(quote.market_cap, quote.currency))
    with top_columns[2]:
        _metric_tile("Beta", _number(quote.beta))
    with top_columns[3]:
        _metric_tile("52W range", f"{_number(quote.fifty_two_week_low)} - {_number(quote.fifty_two_week_high)}")

    bottom_columns = st.columns(4)
    with bottom_columns[0]:
        _metric_tile("Avg volume", _large_money(quote.average_volume))
    with bottom_columns[1]:
        _metric_tile("Dividend yield", _pct((quote.dividend_yield or 0) * 100) if quote.dividend_yield else "N/A")
    with bottom_columns[2]:
        _analyst_target_tile(target, quote.currency)
    with bottom_columns[3]:
        _target_upside_tile(target_upside, target, quote)

    history_df = _market_history_dataframe(market_data)
    if not history_df.empty:
        st.plotly_chart(_market_price_chart(history_df, market_data.ticker), width="stretch")

    _render_news(market_data)

    details = {
        "Provider": market_data.provider,
        "Ticker": market_data.ticker,
        "As of": market_data.as_of.isoformat(),
        "Exchange": quote.exchange,
        "Currency": quote.currency,
        "Previous close": quote.previous_close,
        "Open": quote.open_price,
        "Day low": quote.day_low,
        "Day high": quote.day_high,
        "Trailing P/E": quote.trailing_pe,
        "Forward P/E": quote.forward_pe,
        "Beta": quote.beta,
        "Average volume": quote.average_volume,
        "Dividend yield": quote.dividend_yield,
        "Recommendation": target.recommendation if target else None,
        "Target low": target.low if target else None,
        "Target mean": target.mean if target else None,
        "Target median": target.median if target else None,
        "Target high": target.high if target else None,
        "Analyst count": target.number_of_analysts if target else None,
        "Target source": target.source if target else None,
        "Target last updated": target.last_updated if target else None,
    }
    details_df = pd.DataFrame(
        [{"field": key, "value": "" if value is None else str(value)} for key, value in details.items()]
    )
    with st.expander("Raw market fields"):
        st.dataframe(
            details_df,
            width="stretch",
            hide_index=True,
        )


def _render_news(market_data: MarketDataSnapshot) -> None:
    st.markdown('<div class="section-title">Recent company news</div>', unsafe_allow_html=True)
    if not market_data.news:
        st.markdown(
            '<div class="muted-panel">Yahoo Finance did not return recent headlines for this ticker.</div>',
            unsafe_allow_html=True,
        )
        return

    for item in market_data.news[:6]:
        date_label = _date_label(item.published_at) if item.published_at else "Recent"
        source = " / ".join(part for part in (item.publisher, date_label) if part)
        title = escape(item.title)
        summary = escape(item.summary or "")
        link_html = f'<a href="{escape(item.link)}" target="_blank">Source</a>' if item.link else ""
        st.markdown(
            f"""
            <div class="news-row">
                <div>
                    <span>{escape(source)}</span>
                    <strong>{title}</strong>
                    {'<small>' + summary + '</small>' if summary else ''}
                </div>
                {link_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _date_label(value) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def _render_ai_chat(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
    ai_settings: AISettings,
    comparison_workbooks: list[tuple[str, ParsedWorkbook, AnalysisResult]] | None = None,
) -> None:
    st.markdown(
        '<div class="muted-panel">Ask questions about the workbook, deterministic scores, trends, risks, Yahoo Finance market data, and recent company news summaries. The assistant does not use external tools directly.</div>',
        unsafe_allow_html=True,
    )
    chat_key = f"chat_messages_{parsed.company.ticker or parsed.company.title}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    for index, message in enumerate(st.session_state[chat_key]):
        with st.chat_message(message["role"]):
            _render_plain_ai_text(message["content"])
            if message["role"] == "assistant":
                _copy_button("Copy response", message["content"], f"copy_chat_response_{chat_key}_{index}")

    question = st.chat_input("Ask about the stock research data")
    if not question:
        return

    st.session_state[chat_key].append({"role": "user", "content": question})
    with st.chat_message("user"):
        _render_plain_ai_text(question)

    if not ai_settings.api_key:
        response = "Add a Claude API key in the sidebar or local secrets before using chat."
        st.session_state[chat_key].append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            _render_plain_ai_text(response)
        return

    with st.chat_message("assistant"):
        with st.spinner("Thinking through the workbook and market data"):
            try:
                context = build_ai_context(parsed, analysis, market_data, comparison_workbooks=comparison_workbooks)
                payload = build_user_payload(
                    context,
                    st.session_state[chat_key][:-1],
                    _with_length_instruction(question, ai_settings.max_tokens),
                )
                client = create_ai_client(ai_settings)
                response = _clean_ai_response(client.complete(build_system_prompt(), payload))
            except AIProviderError as exc:
                response = str(exc)
            except Exception as exc:
                response = f"AI chat failed: {exc}"
            _render_plain_ai_text(response)
            _copy_button("Copy response", response, f"copy_chat_response_{chat_key}_{len(st.session_state[chat_key])}")
    st.session_state[chat_key].append({"role": "assistant", "content": response})


def _render_data_quality(parsed: ParsedWorkbook, quarters_df: pd.DataFrame, additional_df: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Quarterly data</div>', unsafe_allow_html=True)
    display_columns = [
        "quarter_label",
        "row_type",
        "revenue_estimate_millions",
        "revenue_actual_millions",
        "revenue_surprise_pct",
        "revenue_yoy_growth",
        "eps_estimate",
        "eps_actual",
        "eps_surprise_pct",
        "price_reaction_pct",
    ]
    st.dataframe(
        quarters_df[display_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "quarter_label": "Quarter",
            "row_type": "Type",
            "revenue_estimate_millions": st.column_config.NumberColumn("Revenue estimate", format="$%.1fM"),
            "revenue_actual_millions": st.column_config.NumberColumn("Revenue actual", format="$%.1fM"),
            "revenue_surprise_pct": st.column_config.NumberColumn("Revenue surprise", format="%.1f%%"),
            "revenue_yoy_growth": st.column_config.NumberColumn("Revenue YoY", format="%.1f%%"),
            "eps_estimate": st.column_config.NumberColumn("EPS estimate", format="%.2f"),
            "eps_actual": st.column_config.NumberColumn("EPS actual", format="%.2f"),
            "eps_surprise_pct": st.column_config.NumberColumn("EPS surprise", format="%.1f%%"),
            "price_reaction_pct": st.column_config.NumberColumn("Price reaction", format="%.1f%%"),
        },
    )

    if not additional_df.empty:
        with st.expander("Additional parsed metrics"):
            additional_display_df = additional_df.assign(value=additional_df["value"].astype(str))
            st.dataframe(
                additional_display_df[["quarter_label", "metric_name", "value", "source_cell"]],
                width="stretch",
                hide_index=True,
            )


def _quarters_dataframe(parsed: ParsedWorkbook, analysis: AnalysisResult) -> pd.DataFrame:
    rows = []
    for order, (quarter, quarter_analysis) in enumerate(zip(parsed.quarters, analysis.quarter_analyses)):
        row = {
            "order": order,
            "row_number": quarter.row_number,
            "quarter_label": quarter.quarter_label,
            "quarter_date": quarter.quarter_date,
            "is_forecast": quarter.is_forecast,
            "row_type": "Forecast" if quarter.is_forecast else "Historical",
            "revenue_estimate_millions": quarter.revenue_estimate_millions,
            "revenue_actual_millions": quarter.revenue_actual_millions,
            "rolling_4q_revenue_millions": quarter.rolling_4q_revenue_millions,
            "rolling_4q_revenue_yoy_growth": quarter.rolling_4q_revenue_yoy_growth,
            "revenue_surprise_pct": quarter_analysis.revenue_surprise_pct,
            "revenue_qoq_growth": quarter_analysis.revenue_qoq_growth,
            "revenue_yoy_growth": quarter_analysis.revenue_yoy_growth,
            "eps_estimate": quarter.eps_estimate,
            "eps_actual": quarter.eps_actual,
            "rolling_4q_eps": quarter.rolling_4q_eps,
            "rolling_4q_eps_yoy_growth": quarter.rolling_4q_eps_yoy_growth,
            "eps_surprise_pct": quarter_analysis.eps_surprise_pct,
            "eps_qoq_growth": quarter_analysis.eps_qoq_growth,
            "eps_yoy_growth": quarter_analysis.eps_yoy_growth,
            "rolling_revenue_growth": quarter_analysis.rolling_revenue_growth,
            "rolling_eps_growth": quarter_analysis.rolling_eps_growth,
            "gross_margin": quarter_analysis.gross_margin,
            "operating_margin": quarter_analysis.operating_margin,
            "net_margin": quarter_analysis.net_margin,
            "shares_millions": quarter.shares_millions,
            "total_earnings_millions": quarter.total_earnings_millions,
            "price_before_earnings": quarter.price_before_earnings,
            "price_after_earnings": quarter.price_after_earnings,
            "price_reaction_pct": quarter_analysis.price_reaction_pct,
            "notes": " | ".join(quarter.notes),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    percent_columns = [
        "revenue_surprise_pct",
        "revenue_qoq_growth",
        "revenue_yoy_growth",
        "eps_surprise_pct",
        "eps_qoq_growth",
        "eps_yoy_growth",
        "rolling_revenue_growth",
        "rolling_eps_growth",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "price_reaction_pct",
    ]
    for column in percent_columns:
        if column in df.columns:
            df[column] = df[column] * 100
    return df


def _additional_metrics_dataframe(parsed: ParsedWorkbook) -> pd.DataFrame:
    rows = []
    for order, quarter in enumerate(parsed.quarters):
        for metric in quarter.additional_metrics:
            value_numeric = _coerce_float(metric.value)
            rows.append(
                {
                    "order": order,
                    "quarter_label": quarter.quarter_label,
                    "metric_name": metric.name,
                    "value": metric.value,
                    "value_numeric": value_numeric,
                    "source_cell": metric.source_cell,
                }
            )
    return pd.DataFrame(rows)


def _historical_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "quarter_date" not in df.columns:
        return df
    today = date.today()

    def is_historical(row) -> bool:
        if bool(row.get("is_forecast", False)):
            return False
        quarter_date = row.get("quarter_date")
        if pd.notna(quarter_date):
            return quarter_date <= today
        label = str(row.get("quarter_label", "")).strip()
        if is_estimate_quarter_label(label):
            return False
        if len(label) >= 4 and label[:4].isdigit():
            return int(label[:4]) <= today.year
        return True

    return df[df.apply(is_historical, axis=1)].copy()


def _forecast_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "is_forecast" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["is_forecast"].fillna(False)].copy()


def _chart_rows(
    historical_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    quarter_count: int,
    show_forecast_extension: bool,
) -> pd.DataFrame:
    historical = historical_df.head(quarter_count).copy()
    if not show_forecast_extension or forecast_df.empty:
        return historical.sort_values("order", ascending=False)
    forecast = forecast_df.copy()
    combined = pd.concat([historical, forecast], ignore_index=True)
    return combined.sort_values("order", ascending=False)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_market_snapshot(ticker: str, period: str, _finnhub_api_key: str = "") -> MarketDataSnapshot:
    return YahooFinanceProvider(finnhub_api_key=_finnhub_api_key).get_snapshot(ticker, period=period)


def _api_key_for(name: str) -> str:
    try:
        secret_value = st.secrets.get(name, "")
    except Exception:
        secret_value = ""
    return str(secret_value or os.getenv(name, "")).strip()


def _copy_button(label: str, text: str, key: str) -> None:
    escaped_label = escape(label)
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    escaped_text = (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("</script>", "<\\/script>")
    )
    components.html(
        f"""
        <button id="{safe_key}" class="copy-button">{escaped_label}</button>
        <script>
        const button = document.getElementById("{safe_key}");
        button.onclick = async () => {{
            await navigator.clipboard.writeText(`{escaped_text}`);
            button.innerText = "Copied";
            setTimeout(() => button.innerText = "{escaped_label}", 1400);
        }};
        </script>
        <style>
        .copy-button {{
            width: 100%;
            border: 1px solid rgba(110, 168, 254, .35);
            background: rgba(17, 27, 37, .95);
            color: #f8fafc;
            border-radius: 8px;
            padding: .72rem .8rem;
            font: 700 14px Inter, system-ui, sans-serif;
            cursor: pointer;
            margin: 0 0 .5rem;
        }}
        .copy-button:hover {{
            border-color: rgba(67, 209, 140, .55);
            background: rgba(22, 33, 45, 1);
        }}
        </style>
        """,
        height=50,
    )


def _render_plain_ai_text(text: str) -> None:
    st.markdown(
        f'<div class="plain-ai-text">{escape(text).replace(chr(10), "<br>")}</div>',
        unsafe_allow_html=True,
    )


def _with_length_instruction(question: str, max_tokens: int) -> str:
    word_budget = max(40, int(max_tokens * 0.55))
    return (
        f"{question}\n\n"
        f"Length limit: keep the answer under about {word_budget} words. "
        "If the limit is tight, prioritize the direct conclusion and the most important evidence."
    )


def _clean_ai_response(response: str) -> str:
    boilerplate_fragments = (
        "i can't provide personalized financial advice",
        "i cannot provide personalized financial advice",
        "please keep in mind that this information is based on historical data",
        "may not reflect the current market situation",
        "consult with a financial advisor",
        "do your own research before making any investment decisions",
        "not financial advice",
    )
    cleaned_lines = []
    for line in response.splitlines():
        lowered = line.lower()
        if any(fragment in lowered for fragment in boilerplate_fragments):
            continue
        plain_line = _plain_prose_line(line)
        cleaned_lines.append(_repair_ai_spacing(_dedupe_repeated_phrase(plain_line)))
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or response.strip()


def _plain_prose_line(line: str) -> str:
    cleaned = line.replace("`", "")
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.*?)_", r"\1", cleaned)
    return cleaned


def _dedupe_repeated_phrase(text: str) -> str:
    """Remove obvious repeated substrings from malformed model output."""

    for window in range(260, 39, -1):
        index = 0
        while index + window * 2 <= len(text):
            chunk = text[index : index + window]
            if chunk and text[index + window : index + window * 2] == chunk:
                text = text[: index + window] + text[index + window * 2 :]
                index = max(0, index - window)
                continue
            index += 1
    return text


def _repair_ai_spacing(text: str) -> str:
    """Fix common spacing glitches without trying to rewrite the AI answer."""

    repaired = re.sub(r",(?=[A-Za-z])", ", ", text)
    repaired = re.sub(r"\.(?=[A-Z])", ". ", repaired)
    repaired = re.sub(r"(?<=\d)(?=(the|and|but|which|with|while|because)\b)", " ", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"(?<=[a-z])(?=(the|and|but|which|with|while|because|analyst|market|forward|trailing)\b)", " ", repaired)
    repaired = re.sub(r"\s{2,}", " ", repaired)
    return repaired.strip()


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return cleaned.strip("_") or "stock_research"


def _market_history_dataframe(market_data: MarketDataSnapshot) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in market_data.history
        ]
    )


def _visible_risks(risks: tuple[str, ...]) -> tuple[str, ...]:
    hidden_fragments = (
        "price reaction data is missing",
        "post-earnings price reaction",
    )
    return tuple(
        risk
        for risk in risks
        if not any(fragment in risk.lower() for fragment in hidden_fragments)
    )


def _scorecard(label: str, value: float, caption: str, definition: str) -> None:
    css_class = "good" if value >= 70 else "watch" if value >= 50 else "weak"
    st.markdown(
        f"""
        <details class="score-card {css_class}">
            <summary>
                <span>{escape(label)}</span>
                <strong>{value:.1f}</strong>
                <small>{escape(caption)}</small>
            </summary>
            <p>{escape(definition)}</p>
        </details>
        """,
        unsafe_allow_html=True,
    )


def _metric_tile(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="metric-tile">
            <span>{label}</span>
            <strong>{value}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _analyst_target_tile(target, currency: str | None) -> None:
    value = _price(target.mean if target else None, currency)
    if target is None:
        details = "<p>No analyst target data was available from the market-data sources.</p>"
    else:
        rows = [
            ("Mean target", _price(target.mean, currency)),
            ("Median target", _price(target.median, currency)),
            ("Low target", _price(target.low, currency)),
            ("High target", _price(target.high, currency)),
            ("Analyst count", _number(target.number_of_analysts)),
            ("Recommendation", str(target.recommendation).title() if target.recommendation else "N/A"),
            ("Source", target.source or "Yahoo Finance"),
            ("Last updated", target.last_updated or "N/A"),
        ]
        details = "".join(
            f'<div class="target-detail-row"><span>{escape(label)}</span><strong>{escape(display)}</strong></div>'
            for label, display in rows
        )

    st.markdown(
        f"""
        <details class="metric-tile clickable-metric target-detail-card">
            <summary>
                <span>Analyst target</span>
                <strong>{escape(value)}</strong>
            </summary>
            <div class="target-detail-grid">{details}</div>
        </details>
        """,
        unsafe_allow_html=True,
    )


def _target_upside_tile(target_upside: float | None, target, quote) -> None:
    value = _pct(target_upside * 100) if target_upside is not None else "N/A"
    current_price = _price(quote.current_price, quote.currency)
    target_price = _price((target.mean if target else None), quote.currency)
    definition = (
        f"Target upside compares the current price ({current_price}) with the mean analyst target ({target_price}). "
        "Positive upside means the consensus target is above the current price; negative upside means it is below."
    )
    _clickable_metric_tile("Target upside", value, definition)


def _clickable_metric_tile(label: str, value: str, definition: str) -> None:
    st.markdown(
        f"""
        <details class="metric-tile clickable-metric">
            <summary>
                <span>{escape(label)}</span>
                <strong>{escape(value)}</strong>
            </summary>
            <p>{escape(definition)}</p>
        </details>
        """,
        unsafe_allow_html=True,
    )


def _render_market_strip(market_data: MarketDataSnapshot | None, analysis: AnalysisResult) -> None:
    market_score = analysis.summary_metrics.get("market_score")
    workbook_score = analysis.summary_metrics.get("workbook_only_score")
    if market_data is None and market_score is None:
        return

    columns = st.columns(4)
    with columns[0]:
        _metric_tile("Market score", _number(market_score))
    with columns[1]:
        _clickable_metric_tile(
            "Workbook score",
            _number(workbook_score),
            "The score from the Excel workbook alone, before live market data is blended in. It weighs execution, growth, profitability, financial quality, and management execution.",
        )


def _trend_grid(analysis: AnalysisResult, limit: int | None = None) -> None:
    if not analysis.trends:
        st.markdown('<div class="muted-panel">No strong trend signals detected.</div>', unsafe_allow_html=True)
        return

    columns = st.columns(3)
    trends = analysis.trends[:limit] if limit else analysis.trends
    for index, trend in enumerate(trends):
        with columns[index % 3]:
            direction = trend.direction.lower()
            color_class = "positive" if direction in {"accelerating", "expanding", "improving", "more accurate"} else "negative"
            st.markdown(
                f"""
                <div class="trend-card {color_class}">
                    <span>{trend.name}</span>
                    <strong>{trend.direction.title()}</strong>
                    <small>{trend.description}</small>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _line_chart(
    df: pd.DataFrame,
    title: str,
    series: dict[str, tuple[str, str]],
    y_title: str,
    percent_axis: bool = False,
    height: int = 340,
    split_forecast: bool = False,
) -> go.Figure:
    figure = go.Figure()
    if split_forecast:
        forecast_mask = df["is_forecast"].fillna(False) if "is_forecast" in df.columns else pd.Series(False, index=df.index)
        historical = df[~forecast_mask].copy()
        forecast = df[forecast_mask].copy()
    else:
        historical = df
        forecast = df.iloc[0:0].copy()

    for name, (column, color) in series.items():
        _add_line_trace(figure, historical, name, column, color, dash=None, percent_axis=percent_axis)
        if split_forecast:
            _add_line_trace(
                figure,
                forecast,
                f"Forecast {name.lower()}",
                column,
                _forecast_trace_color(name, color),
                dash="dash",
                percent_axis=percent_axis,
                marker_color=_forecast_marker_color(column),
            )
    _style_chart(figure, title, y_title, percent_axis, height=height, show_legend=False)
    return figure


def _actual_estimate_forecast_chart(
    df: pd.DataFrame,
    title: str,
    actual_label: str,
    actual_column: str,
    estimate_label: str,
    estimate_column: str,
    y_title: str,
    height: int = 340,
) -> go.Figure:
    figure = go.Figure()
    if df.empty:
        _style_chart(figure, title, y_title, False, height=height, show_legend=False)
        return figure

    forecast_mask = df["is_forecast"].fillna(False) if "is_forecast" in df.columns else pd.Series(False, index=df.index)
    historical = df[~forecast_mask].copy()
    forecast = df[forecast_mask].copy()

    _add_line_trace(figure, historical, actual_label, actual_column, BLUE, dash=None)
    _add_line_trace(figure, historical, estimate_label, estimate_column, NEUTRAL, dash=None)

    if not forecast.empty:
        forecast_column = actual_column if forecast[actual_column].notna().any() else estimate_column
        forecast_label = f"Forecast {actual_label.replace('Actual ', '').lower()}"
        _add_line_trace(figure, forecast, forecast_label, forecast_column, FORECAST, dash="dash")

    _style_chart(figure, title, y_title, False, height=height, show_legend=False)
    return figure


def _add_line_trace(
    figure: go.Figure,
    df: pd.DataFrame,
    name: str,
    column: str,
    color: str,
    dash: str | None,
    percent_axis: bool = False,
    marker_color: str | None = None,
) -> None:
    if df.empty or column not in df.columns or df[column].dropna().empty:
        return
    figure.add_trace(
        go.Scatter(
            x=df["quarter_label"],
            y=df[column],
            mode="lines+markers",
            name=name,
            line={
                "color": color,
                "width": 2.6,
                "shape": "spline",
                "smoothing": 0.45,
                **({"dash": dash} if dash else {}),
            },
            marker=_line_marker(dash, marker_color or color),
            hovertemplate=f"{name}<br>%{{x}}<br>%{{y:.2f}}{'%' if percent_axis else ''}<extra></extra>",
        )
    )


def _line_marker(dash: str | None, color: str) -> dict:
    if dash:
        return {
            "size": 7.5,
            "color": color,
            "line": {"color": PLOT_BG, "width": 1.8},
        }
    return {"size": 5.5, "line": {"color": PAPER_BG, "width": 1.2}}


def _forecast_trace_color(name: str, fallback_color: str) -> str:
    if name.lower().startswith("yoy"):
        return POSITIVE
    return fallback_color


def _forecast_marker_color(column: str) -> str | None:
    if column == "rolling_4q_revenue_millions":
        return GOLD
    return None


def _single_series_chart(df: pd.DataFrame, title: str, column: str, y_title: str) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=df["quarter_label"],
            y=df[column],
            mode="lines+markers",
            name=title,
            line={"color": BLUE, "width": 3.0, "shape": "spline", "smoothing": 0.55},
            marker={"size": 7, "line": {"color": PAPER_BG, "width": 1.5}},
        )
    )
    _style_chart(figure, title, y_title, False, show_legend=False)
    return figure


def _market_price_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["close"],
            mode="lines",
            name="Close",
            line={"color": BLUE, "width": 3.0, "shape": "spline", "smoothing": 0.45},
            fill="tozeroy",
            fillcolor="rgba(110, 168, 254, 0.10)",
        )
    )
    _style_chart(figure, f"{ticker} historical price", "Close price", False, show_legend=False)
    return figure


def _bar_chart(
    df: pd.DataFrame,
    title: str,
    series: dict[str, tuple[str, str]],
    y_title: str,
    percent_axis: bool = False,
) -> go.Figure:
    figure = go.Figure()
    for name, (column, color) in series.items():
        if column not in df.columns or df[column].dropna().empty:
            continue
        colors = [
            POSITIVE if value is not None and pd.notna(value) and value >= 0 else NEGATIVE
            for value in df[column]
        ]
        if len(series) > 1:
            colors = [color] * len(df)
        figure.add_trace(
            go.Bar(
                x=df["quarter_label"],
                y=df[column],
                name=name,
                marker_color=colors,
                marker_line_color="rgba(255,255,255,.08)",
                marker_line_width=1,
                opacity=0.9,
                hovertemplate=f"{name}<br>%{{x}}<br>%{{y:.2f}}{'%' if percent_axis else ''}<extra></extra>",
            )
        )
    _style_chart(figure, title, y_title, percent_axis)
    figure.update_layout(barmode="group")
    return figure


def _score_gauge(score: float) -> go.Figure:
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"font": {"color": "#f8fafc", "size": 44}},
            title={"text": "Overall investment score", "font": {"color": "#cbd5e1", "size": 16}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#94a3b8"},
                "bar": {"color": BLUE},
                "bgcolor": "#111827",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 45], "color": "rgba(255, 107, 107, 0.22)"},
                    {"range": [45, 70], "color": "rgba(246, 200, 95, 0.22)"},
                    {"range": [70, 100], "color": "rgba(67, 209, 140, 0.24)"},
                ],
            },
        )
    )
    figure.update_layout(
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        height=330,
        margin={"l": 24, "r": 24, "t": 58, "b": 18},
        font={"family": "Inter, system-ui, sans-serif", "color": "#e5e7eb"},
    )
    return figure


def _style_chart(
    figure: go.Figure,
    title: str,
    y_title: str,
    percent_axis: bool,
    height: int = 340,
    show_legend: bool = True,
) -> None:
    figure.update_layout(
        title={"text": title, "x": 0.02, "font": {"size": 15, "color": "#f8fafc"}},
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        height=height,
        margin={"l": 46, "r": 20, "t": 52, "b": 46},
        showlegend=show_legend,
        legend={"orientation": "h", "y": 1.1, "x": 0, "font": {"color": "#cbd5e1", "size": 11}},
        font={"family": "Inter, system-ui, sans-serif", "color": "#e5e7eb"},
        hovermode="x unified",
        hoverlabel={"bgcolor": "#111b25", "bordercolor": "rgba(148, 163, 184, 0.28)", "font": {"color": "#f8fafc"}},
        transition={"duration": 250},
    )
    figure.update_xaxes(
        title=None,
        showgrid=False,
        showline=True,
        linecolor="rgba(148, 163, 184, 0.22)",
        tickangle=-25,
        tickfont={"color": "#94a3b8", "size": 11},
        nticks=7,
    )
    figure.update_yaxes(
        title=y_title,
        gridcolor=GRID,
        zerolinecolor="rgba(148, 163, 184, 0.32)",
        tickfont={"color": "#94a3b8"},
        ticksuffix="%" if percent_axis else "",
        showline=False,
    )


def _numeric_additional_metrics(additional_df: pd.DataFrame) -> list[str]:
    if additional_df.empty:
        return []
    availability = defaultdict(int)
    for metric_name, metric_df in additional_df.groupby("metric_name"):
        availability[metric_name] = metric_df["value_numeric"].notna().sum()
    return [name for name, count in sorted(availability.items()) if count >= 2]


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool) or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        try:
            numeric = float(value.replace(",", "").strip())
            return numeric if math.isfinite(numeric) else None
        except ValueError:
            return None
    return None


def _money(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    return f"${numeric:,.1f}M"


def _large_money(value: object, currency: str | None = None) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    label = f" {currency}" if currency else ""
    if abs(numeric) >= 1_000_000_000_000:
        return f"{numeric / 1_000_000_000_000:,.2f}T{label}"
    if abs(numeric) >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:,.2f}B{label}"
    if abs(numeric) >= 1_000_000:
        return f"{numeric / 1_000_000:,.2f}M{label}"
    return f"{numeric:,.0f}{label}"


def _price(value: object, currency: str | None = None) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    suffix = f" {currency}" if currency else ""
    return f"{numeric:,.2f}{suffix}"


def _number(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:,.2f}"


def _pct(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:,.1f}%"


def _apply_theme(mode: str = "Dark") -> None:
    is_light = mode.lower().startswith("light")
    bg = "#f7fafc" if is_light else "#080d13"
    bg_bottom = "#edf2f7" if is_light else "#0b1117"
    panel = "#ffffff" if is_light else "#0d141c"
    panel_2 = "#eef4fb" if is_light else "#111b25"
    border = "rgba(15, 23, 42, 0.14)" if is_light else "rgba(148, 163, 184, 0.18)"
    text = "#0f172a" if is_light else "#f8fafc"
    muted = "#526071" if is_light else "#94a3b8"
    sidebar_top = "#ffffff" if is_light else "#070b10"
    sidebar_bottom = "#edf2f7" if is_light else "#0b1117"
    panel_gradient = (
        "linear-gradient(180deg, rgba(255, 255, 255, .96), rgba(239, 246, 255, .94))"
        if is_light
        else "linear-gradient(180deg, rgba(22, 33, 45, .92), rgba(11, 17, 23, .92))"
    )
    hero_glow = (
        "radial-gradient(circle at top left, rgba(37, 99, 235, 0.10), transparent 30rem),"
        "radial-gradient(circle at 82% 8%, rgba(5, 150, 105, 0.08), transparent 24rem),"
        f"linear-gradient(180deg, {bg} 0%, {bg_bottom} 100%)"
    )
    css = """
        <style>
        html,
        body,
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stSidebar"] {
            color-scheme: __COLOR_SCHEME__;
        }
        :root {
            --bg: __BG__;
            --panel: __PANEL__;
            --panel-2: __PANEL_2__;
            --border: __BORDER__;
            --text: __TEXT__;
            --muted: __MUTED__;
            --blue: #6ea8fe;
            --green: #43d18c;
            --red: #ff6b6b;
            --gold: #f6c85f;
        }
        .stApp {
            background: __HERO_GLOW__;
            color: var(--text);
            font-size: 17px;
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, __SIDEBAR_TOP__ 0%, __SIDEBAR_BOTTOM__ 100%);
            border-right: 1px solid var(--border);
        }
        section[data-testid="stSidebar"] * {
            color: var(--text);
        }
        [data-testid="stDeployButton"],
        #MainMenu,
        footer {
            display: none;
        }
        .block-container {
            padding-top: 2.25rem;
            max-width: 1580px;
        }
        .app-hero,
        .dashboard-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1.5rem;
            padding: 1.7rem 0 1.4rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.4rem;
        }
        .app-hero {
            min-height: 55vh;
            align-items: center;
        }
        .eyebrow {
            margin: 0 0 .35rem 0;
            color: var(--blue);
            text-transform: uppercase;
            font-size: .74rem;
            font-weight: 700;
            letter-spacing: .08rem;
        }
        .dashboard-header h1,
        .app-hero h1 {
            margin: 0;
            color: var(--text);
            font-size: clamp(2.2rem, 5vw, 4.3rem);
            line-height: 1;
            letter-spacing: 0;
        }
        .dashboard-header p,
        .hero-copy {
            margin: .65rem 0 0;
            color: var(--muted);
            max-width: 900px;
            font-size: 1.05rem;
        }
        .header-stat {
            min-width: 180px;
            padding: 1.1rem;
            background: rgba(17, 27, 37, .84);
            border: 1px solid var(--border);
            border-radius: 8px;
            text-align: right;
        }
        .header-stat span,
        .metric-tile span,
        .score-card span,
        .trend-card span {
            display: block;
            color: var(--muted);
            font-size: .82rem;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: .05rem;
        }
        .header-stat strong {
            color: var(--text);
            font-size: 1.35rem;
        }
        .score-card,
        .metric-tile,
        .trend-card,
        .news-row,
        .summary-panel,
        .ai-memo,
        .muted-panel,
        .risk-row,
        .error-panel {
            background: __PANEL_GRADIENT__;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.15rem;
            min-height: 126px;
            box-shadow: 0 16px 38px rgba(0, 0, 0, .26);
            backdrop-filter: blur(10px);
        }
        .score-card:hover,
        .metric-tile:hover,
        .trend-card:hover {
            border-color: rgba(110, 168, 254, .34);
            transform: translateY(-1px);
            transition: border-color .18s ease, transform .18s ease;
        }
        .summary-panel {
            padding: 1.4rem 1.5rem;
            min-height: 0;
            border-color: rgba(110, 168, 254, .34);
        }
        .summary-panel h2 {
            color: var(--text);
            font-size: 1.38rem;
            line-height: 1.35;
            margin: 0 0 1rem;
            letter-spacing: 0;
        }
        .summary-columns {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        .summary-columns span {
            color: var(--blue);
            font-size: .76rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .summary-columns ul {
            margin: .55rem 0 0 1rem;
            padding: 0;
            color: var(--text);
        }
        .summary-columns li {
            margin-bottom: .45rem;
        }
        .summary-conclusion {
            margin: 1rem 0 0;
            color: var(--text);
            border-top: 1px solid var(--border);
            padding-top: .9rem;
        }
        .ai-memo {
            min-height: 0;
            color: var(--text);
            line-height: 1.7;
            border-color: rgba(67, 209, 140, .28);
            margin-bottom: .6rem;
            font-size: 1.02rem;
        }
        .plain-ai-text {
            color: var(--text);
            line-height: 1.65;
            font-size: 1rem;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .error-panel {
            min-height: 0;
            margin-top: 1rem;
            border-color: rgba(255, 107, 107, .45);
            color: #fecaca;
        }
        .score-card strong {
            display: block;
            margin: .35rem 0;
            color: var(--text);
            font-size: 2.25rem;
            line-height: 1;
        }
        .score-card summary {
            list-style: none;
            cursor: pointer;
        }
        .clickable-metric summary {
            list-style: none;
            cursor: pointer;
        }
        .score-card summary::-webkit-details-marker {
            display: none;
        }
        .clickable-metric summary::-webkit-details-marker {
            display: none;
        }
        .score-card p {
            margin: .8rem 0 0;
            padding-top: .75rem;
            border-top: 1px solid var(--border);
            color: var(--text);
            line-height: 1.45;
            font-size: .95rem;
        }
        .clickable-metric p {
            margin: .75rem 0 0;
            padding-top: .7rem;
            border-top: 1px solid var(--border);
            color: var(--text);
            line-height: 1.45;
            font-size: .95rem;
        }
        .target-detail-grid {
            margin-top: .75rem;
            padding-top: .7rem;
            border-top: 1px solid var(--border);
            display: grid;
            gap: .48rem;
        }
        .target-detail-row {
            display: flex;
            justify-content: space-between;
            gap: .8rem;
            align-items: baseline;
            color: var(--text);
            font-size: .93rem;
        }
        .target-detail-row span {
            display: inline;
            color: var(--muted);
            font-size: .72rem;
            letter-spacing: .03rem;
        }
        .target-detail-row strong {
            margin: 0;
            color: var(--text);
            font-size: .95rem;
            line-height: 1.25;
            text-align: right;
        }
        .score-card small,
        .trend-card small {
            color: var(--muted);
        }
        .score-card.good {
            border-color: rgba(67, 209, 140, .45);
        }
        .score-card.watch {
            border-color: rgba(246, 200, 95, .45);
        }
        .score-card.weak {
            border-color: rgba(255, 107, 107, .45);
        }
        .metric-tile {
            min-height: 94px;
        }
        .metric-tile strong {
            display: block;
            margin-top: .55rem;
            color: var(--text);
            font-size: 1.55rem;
            line-height: 1.1;
            overflow-wrap: anywhere;
        }
        .trend-card {
            min-height: 150px;
            margin-bottom: 1rem;
        }
        .trend-card strong {
            display: block;
            margin: .55rem 0;
            font-size: 1.2rem;
        }
        .trend-card.positive strong {
            color: var(--green);
        }
        .trend-card.negative strong {
            color: var(--red);
        }
        .risk-row {
            min-height: 0;
            border-color: rgba(255, 107, 107, .35);
            color: #fecaca;
            margin-bottom: .6rem;
        }
        .news-row {
            min-height: 0;
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: flex-start;
            margin-bottom: .65rem;
            box-shadow: none;
        }
        .news-row span {
            display: block;
            color: var(--muted);
            font-size: .75rem;
            text-transform: uppercase;
            font-weight: 800;
            letter-spacing: .04rem;
            margin-bottom: .3rem;
        }
        .news-row strong {
            display: block;
            color: var(--text);
            line-height: 1.3;
        }
        .news-row small {
            display: block;
            color: #cbd5e1;
            margin-top: .35rem;
            line-height: 1.35;
        }
        .news-row a {
            color: var(--blue);
            text-decoration: none;
            font-weight: 800;
            white-space: nowrap;
        }
        .muted-panel {
            min-height: 0;
            color: var(--muted);
        }
        .forecast-note {
            margin: 1rem 0 .75rem;
            border-color: rgba(45, 212, 191, .35);
            color: #dbeafe;
        }
        .section-title {
            margin: 1.55rem 0 .85rem;
            color: var(--text);
            font-weight: 800;
            font-size: 1.12rem;
        }
        .section-title.compact {
            margin-top: 0;
        }
        div[data-testid="stMetric"] {
            background: rgba(17, 27, 37, .82);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: .35rem;
            border-bottom: 1px solid var(--border);
            padding-bottom: .25rem;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px;
            color: var(--muted);
            background: rgba(17, 27, 37, .42);
            border: 1px solid transparent;
        }
        .stTabs [aria-selected="true"] {
            color: var(--text);
            background: rgba(17, 27, 37, .95);
            border-color: rgba(110, 168, 254, .34);
        }
        div[data-baseweb="input"],
        div[data-baseweb="select"] > div,
        textarea {
            background-color: rgba(17, 27, 37, .84) !important;
            border-color: rgba(148, 163, 184, .2) !important;
        }
        @media (max-width: 900px) {
            .dashboard-header {
                display: block;
            }
            .summary-columns {
                grid-template-columns: 1fr;
            }
            .header-stat {
                margin-top: 1rem;
                text-align: left;
            }
            .dashboard-header h1,
            .app-hero h1 {
                font-size: 2.4rem;
            }
        }
        </style>
    """
    replacements = {
        "__COLOR_SCHEME__": "light" if is_light else "dark",
        "__BG__": bg,
        "__PANEL__": panel,
        "__PANEL_2__": panel_2,
        "__BORDER__": border,
        "__TEXT__": text,
        "__MUTED__": muted,
        "__HERO_GLOW__": hero_glow,
        "__SIDEBAR_TOP__": sidebar_top,
        "__SIDEBAR_BOTTOM__": sidebar_bottom,
        "__PANEL_GRADIENT__": panel_gradient,
    }
    for token, value in replacements.items():
        css = css.replace(token, value)
    st.markdown(css, unsafe_allow_html=True)
