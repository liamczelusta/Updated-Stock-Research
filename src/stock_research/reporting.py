"""Executive summary and export helpers for one-workbook analysis."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import wrap
from typing import Iterable

from stock_research.dataclasses import AnalysisResult, ParsedWorkbook, QuarterAnalysis, QuarterRecord, is_historical_quarter
from stock_research.market_data import MarketDataSnapshot


@dataclass(frozen=True)
class ExecutiveSummary:
    """Concise report content shown at the top of the app and exported."""

    headline: str
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    market: tuple[str, ...]
    conclusion: str

    @property
    def bullets(self) -> tuple[str, ...]:
        return self.strengths + self.risks + self.market

    def as_text(self) -> str:
        sections = [
            self.headline,
            "",
            "Strengths",
            *[f"- {item}" for item in self.strengths],
            "",
            "Risks / watch items",
            *[f"- {item}" for item in self.risks],
        ]
        if self.market:
            sections.extend(["", "Market context", *[f"- {item}" for item in self.market]])
        sections.extend(["", self.conclusion])
        return "\n".join(sections).strip()


def build_executive_summary(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
) -> ExecutiveSummary:
    """Create a deterministic, analyst-style executive summary."""

    usable = _usable_pairs(parsed, analysis)
    latest_quarter = usable[0][0].quarter_label if usable else "latest quarter"
    strengths = tuple(_strengths(usable, analysis))
    risks = tuple(_risks(usable, analysis))
    market = tuple(_market_context(market_data, analysis))

    score = analysis.scores.overall_investment
    headline = (
        f"{parsed.company.ticker or parsed.company.title} scored {score:.1f}/100 after reviewing "
        f"{len(usable)} usable quarters through {latest_quarter}."
    )
    if analysis.summary_metrics.get("market_data_included"):
        headline += " The score includes current Yahoo Finance market data."

    if score >= 70:
        conclusion = "Overall read-through: strong historical execution, with valuation and current trend quality still worth monitoring."
    elif score >= 50:
        conclusion = "Overall read-through: mixed but usable setup; focus follow-up work on the watch items before forming a view."
    else:
        conclusion = "Overall read-through: weaker setup; the workbook shows enough risk that deeper review is warranted."

    return ExecutiveSummary(
        headline=headline,
        strengths=strengths or ("No major deterministic strength signal was detected.",),
        risks=risks or ("No major deterministic risk signal was detected.",),
        market=market,
        conclusion=conclusion,
    )


def build_complete_report_text(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    market_data: MarketDataSnapshot | None,
    summary: ExecutiveSummary,
) -> str:
    """Build a complete plain-text report for PDF export."""

    quote = market_data.quote if market_data else None
    lines = [
        f"{parsed.company.ticker or parsed.company.title} Research Report",
        "",
        "Executive Summary",
        summary.as_text(),
        "",
        "Scores",
        f"- Overall: {analysis.scores.overall_investment:.1f}",
        f"- Growth: {analysis.scores.growth:.1f}",
        f"- Profitability: {analysis.scores.profitability:.1f}",
        f"- Execution: {analysis.scores.historical_execution:.1f}",
        f"- Financial quality: {analysis.scores.financial_quality:.1f}",
        "",
        "Trend Signals",
        *[f"- {trend.name}: {trend.direction}. {trend.description}" for trend in analysis.trends],
        "",
        "Market Data",
    ]
    if quote:
        lines.extend(
            [
                f"- Current price: {_fmt_number(quote.current_price)} {quote.currency or ''}".strip(),
                f"- Market cap: {_fmt_large_number(quote.market_cap)}",
                f"- 52-week range: {_fmt_number(quote.fifty_two_week_low)} - {_fmt_number(quote.fifty_two_week_high)}",
                f"- Beta: {_fmt_number(quote.beta)}",
                f"- Average volume: {_fmt_large_number(quote.average_volume)}",
                f"- Dividend yield: {_fmt_pct(quote.dividend_yield)}",
            ]
        )
    else:
        lines.append("- Market data was not available.")

    lines.extend(["", "Recent Quarters"])
    for quarter, q_analysis in usable_quarters(parsed, analysis, limit=8):
        lines.append(
            "- "
            f"{quarter.quarter_label}: revenue {_fmt_money_m(quarter.revenue_actual_millions)}, "
            f"EPS {_fmt_number(quarter.eps_actual)}, "
            f"revenue surprise {_fmt_pct(q_analysis.revenue_surprise_pct)}, "
            f"EPS surprise {_fmt_pct(q_analysis.eps_surprise_pct)}"
        )
    return "\n".join(lines).strip()


def build_pdf(title: str, body: str) -> bytes:
    """Render a lightweight, dependency-free PDF report from plain text."""

    pages = _pdf_pages(title, body)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + index * 2} 0 R' for index in range(len(pages)))}] /Count {len(pages)} >>".encode(),
    ]
    for index, page_stream in enumerate(pages):
        page_obj = 3 + index * 2
        content_obj = page_obj + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> "
            f"/F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> >> >> "
            f"/Contents {content_obj} 0 R >>".encode()
        )
        stream = page_stream.encode("latin-1", errors="replace")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode()
    )
    return bytes(output)


def usable_quarters(
    parsed: ParsedWorkbook,
    analysis: AnalysisResult,
    limit: int | None = None,
) -> tuple[tuple[QuarterRecord, QuarterAnalysis], ...]:
    pairs = _usable_pairs(parsed, analysis)
    return tuple(pairs[:limit] if limit else pairs)


def _usable_pairs(parsed: ParsedWorkbook, analysis: AnalysisResult) -> list[tuple[QuarterRecord, QuarterAnalysis]]:
    return [
        (quarter, q_analysis)
        for quarter, q_analysis in zip(parsed.quarters, analysis.quarter_analyses)
        if is_historical_quarter(quarter)
        and (quarter.revenue_actual_millions is not None or quarter.eps_actual is not None)
    ]


def _strengths(pairs: list[tuple[QuarterRecord, QuarterAnalysis]], analysis: AnalysisResult) -> Iterable[str]:
    recent = [q_analysis for _quarter, q_analysis in pairs[:8]]
    revenue_beats = sum(1 for item in recent if item.revenue_surprise_pct is not None and item.revenue_surprise_pct > 0)
    eps_beats = sum(1 for item in recent if item.eps_surprise_pct is not None and item.eps_surprise_pct > 0)
    if recent:
        if revenue_beats >= len(recent) / 2:
            yield f"Revenue exceeded consensus in {revenue_beats} of the last {len(recent)} quarters."
        if eps_beats >= len(recent) / 2:
            yield f"EPS exceeded consensus in {eps_beats} of the last {len(recent)} quarters."

    for trend in analysis.trends:
        direction = trend.direction.lower()
        if direction in {"accelerating", "expanding", "improving", "more accurate", "less reactive"}:
            yield f"{trend.name} is {trend.direction}: {trend.description}"

    if analysis.scores.historical_execution >= 70:
        yield "Management execution remains strong based on recent beat rate and analyst accuracy."


def _risks(pairs: list[tuple[QuarterRecord, QuarterAnalysis]], analysis: AnalysisResult) -> Iterable[str]:
    yielded = False
    recent = [q_analysis for _quarter, q_analysis in pairs[:8]]
    revenue_beats = sum(1 for item in recent if item.revenue_surprise_pct is not None and item.revenue_surprise_pct > 0)
    eps_beats = sum(1 for item in recent if item.eps_surprise_pct is not None and item.eps_surprise_pct > 0)
    if recent and revenue_beats < len(recent) / 2:
        yielded = True
        yield f"Revenue exceeded consensus in only {revenue_beats} of the last {len(recent)} quarters."
    if recent and eps_beats < len(recent) / 2:
        yielded = True
        yield f"EPS exceeded consensus in only {eps_beats} of the last {len(recent)} quarters."

    for trend in analysis.trends:
        direction = trend.direction.lower()
        if direction in {"slowing", "contracting", "worsening", "less accurate", "more reactive"}:
            yielded = True
            yield f"{trend.name} is {trend.direction}: {trend.description}"

    visible_risks = [
        risk
        for risk in analysis.risk_indicators
        if "price reaction data is missing" not in risk.lower()
    ]
    for risk in visible_risks[:3]:
        yielded = True
        yield risk

    latest_eps_growth = pairs[0][1].eps_yoy_growth if pairs else None
    latest_revenue_growth = pairs[0][1].revenue_yoy_growth if pairs else None
    if (
        latest_eps_growth is not None
        and latest_revenue_growth is not None
        and latest_revenue_growth > 0
        and latest_eps_growth < latest_revenue_growth
    ):
        yielded = True
        yield "EPS growth is lagging revenue growth in the latest comparable quarter."

    if not yielded:
        yield "No urgent workbook-based risk flag stood out in the deterministic rules."


def _market_context(market_data: MarketDataSnapshot | None, analysis: AnalysisResult) -> Iterable[str]:
    if market_data is None:
        return
    quote = market_data.quote
    if quote.current_price is not None:
        yield f"Current Yahoo Finance price is {_fmt_number(quote.current_price)} {quote.currency or ''}".strip() + "."
    if quote.fifty_two_week_low is not None and quote.fifty_two_week_high is not None:
        yield f"52-week range is {_fmt_number(quote.fifty_two_week_low)} to {_fmt_number(quote.fifty_two_week_high)}."
    if analysis.summary_metrics.get("market_score") is not None:
        yield f"Market score is {analysis.summary_metrics['market_score']:.1f}, blended into the overall score."
    if quote.forward_pe is not None and quote.forward_pe >= 50:
        yield "Valuation appears elevated based on forward P/E."
    if market_data.news:
        latest = market_data.news[0]
        publisher = f" from {latest.publisher}" if latest.publisher else ""
        yield f"Latest Yahoo Finance headline{publisher}: {latest.title}"


def _fmt_number(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def _fmt_large_number(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:,.2f}T"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    return f"{value:,.0f}"


def _fmt_money_m(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.1f}M"


def _fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:,.1f}%"


def _pdf_pages(title: str, body: str) -> list[str]:
    lines = [title, ""] + [wrapped for line in body.splitlines() for wrapped in (_wrap_pdf_line(line) or [""])]
    pages: list[list[str]] = [[]]
    for line in lines:
        if len(pages[-1]) >= 48:
            pages.append([])
        pages[-1].append(line)

    page_streams = []
    for page_lines in pages:
        stream_lines = ["BT", "/F2 15 Tf", "54 744 Td", f"({_pdf_text(page_lines[0] if page_lines else title)}) Tj"]
        stream_lines.extend(["/F1 9.5 Tf", "0 -24 Td"])
        for line in page_lines[1:]:
            stream_lines.append(f"({_pdf_text(line)}) Tj")
            stream_lines.append("0 -13 Td")
        stream_lines.append("ET")
        page_streams.append("\n".join(stream_lines))
    return page_streams


def _wrap_pdf_line(line: str) -> list[str]:
    if not line:
        return [""]
    return wrap(line, width=92) or [line]


def _pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
