"""Market data provider layer with Yahoo Finance as the first implementation."""

from __future__ import annotations

from contextlib import redirect_stderr
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


class MarketDataError(RuntimeError):
    """Raised when market data cannot be retrieved."""


@dataclass(frozen=True)
class MarketQuote:
    """Current market quote and summary values."""

    current_price: float | None
    previous_close: float | None
    open_price: float | None
    day_low: float | None
    day_high: float | None
    fifty_two_week_low: float | None
    fifty_two_week_high: float | None
    market_cap: float | None
    trailing_pe: float | None
    forward_pe: float | None
    beta: float | None
    average_volume: float | None
    dividend_yield: float | None
    currency: str | None
    exchange: str | None


@dataclass(frozen=True)
class AnalystTargets:
    """Analyst price target snapshot when available."""

    low: float | None = None
    mean: float | None = None
    median: float | None = None
    high: float | None = None
    number_of_analysts: int | None = None
    recommendation: str | None = None
    source: str | None = None
    last_updated: str | None = None


@dataclass(frozen=True)
class HistoricalPrice:
    """One historical market price row."""

    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


@dataclass(frozen=True)
class NewsItem:
    """One current company news headline from the market data provider."""

    title: str
    publisher: str | None
    published_at: datetime | None
    link: str | None
    summary: str | None = None


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Complete market data payload returned by a provider."""

    provider: str
    ticker: str
    as_of: datetime
    quote: MarketQuote
    analyst_targets: AnalystTargets | None
    history: tuple[HistoricalPrice, ...] = ()
    news: tuple[NewsItem, ...] = ()
    metadata: dict[str, str | float | int | None] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class MarketDataProvider(Protocol):
    """Provider interface for Yahoo now and FactSet later."""

    name: str

    def get_snapshot(self, ticker: str, period: str = "1y") -> MarketDataSnapshot:
        """Return a market data snapshot for a ticker."""


class YahooFinanceProvider:
    """Yahoo Finance implementation powered by yfinance, with optional Finnhub news."""

    name = "Yahoo Finance"

    def __init__(self, finnhub_api_key: str | None = None) -> None:
        self.finnhub_api_key = (finnhub_api_key or os.getenv("FINNHUB_API_KEY", "")).strip()

    def get_snapshot(self, ticker: str, period: str = "1y") -> MarketDataSnapshot:
        clean_ticker = ticker.strip().upper()
        if not clean_ticker:
            raise MarketDataError("A ticker symbol is required for market data.")

        try:
            import yfinance as yf

            _configure_yfinance_cache(yf)
            yf_ticker = yf.Ticker(clean_ticker)
            warnings = []
            info = _safe_info(yf_ticker, warnings)
            history = _safe_history(yf_ticker, period, warnings)
            analyst_targets = _safe_analyst_targets(yf_ticker, info, warnings)
            analyst_targets = _merge_analyst_targets(
                analyst_targets,
                _safe_finnhub_price_target(clean_ticker, self.finnhub_api_key, warnings),
            )
            news = _safe_finnhub_news(clean_ticker, self.finnhub_api_key, warnings)
            news_provider = "Finnhub" if news else "Yahoo Finance"
            if not news:
                news = _safe_yahoo_news(yf_ticker, warnings)
            quote = MarketQuote(
                current_price=_first_float(info, "currentPrice", "regularMarketPrice"),
                previous_close=_first_float(info, "previousClose", "regularMarketPreviousClose"),
                open_price=_first_float(info, "open", "regularMarketOpen"),
                day_low=_first_float(info, "dayLow", "regularMarketDayLow"),
                day_high=_first_float(info, "dayHigh", "regularMarketDayHigh"),
                fifty_two_week_low=_first_float(info, "fiftyTwoWeekLow"),
                fifty_two_week_high=_first_float(info, "fiftyTwoWeekHigh"),
                market_cap=_first_float(info, "marketCap"),
                trailing_pe=_first_float(info, "trailingPE"),
                forward_pe=_first_float(info, "forwardPE"),
                beta=_first_float(info, "beta"),
                average_volume=_first_float(info, "averageVolume", "averageDailyVolume10Day"),
                dividend_yield=_first_float(info, "dividendYield"),
                currency=_first_text(info, "currency", "financialCurrency"),
                exchange=_first_text(info, "exchange", "fullExchangeName"),
            )
            metadata = {
                "short_name": _first_text(info, "shortName", "longName"),
                "sector": _first_text(info, "sector"),
                "industry": _first_text(info, "industry"),
                "website": _first_text(info, "website"),
                "news_provider": news_provider if news else None,
            }
            if quote.current_price is None:
                warnings.append("Current price was not available from Yahoo Finance.")
            if not history:
                warnings.append("Historical price data was not available from Yahoo Finance.")

            return MarketDataSnapshot(
                provider=self.name,
                ticker=clean_ticker,
                as_of=datetime.now(timezone.utc),
                quote=quote,
                analyst_targets=analyst_targets,
                history=tuple(history),
                news=tuple(news),
                metadata=metadata,
                warnings=tuple(dict.fromkeys(warnings)),
            )
        except Exception as exc:
            raise MarketDataError(f"Yahoo Finance request failed for {clean_ticker}: {exc}") from exc


class FactSetProviderPlaceholder:
    """Placeholder adapter documenting where future FactSet support belongs."""

    name = "FactSet"

    def get_snapshot(self, ticker: str, period: str = "1y") -> MarketDataSnapshot:
        raise MarketDataError(
            "FactSet integration is not configured. Add credentials and implement this provider "
            "behind the MarketDataProvider interface."
        )


def _configure_yfinance_cache(yf) -> None:
    """Point yfinance's sqlite caches at a stable writable project folder."""

    cache_root = (
        Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "StockResearchDashboard" / "Cache"
        if sys.platform.startswith("win")
        else Path.home() / "Library" / "Caches" / "StockResearchDashboard"
    )
    cache_dir = cache_root / "yfinance"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for setter_name in ("set_cache_location", "set_tz_cache_location"):
        setter = getattr(getattr(yf, "cache", None), setter_name, None)
        if setter is None:
            continue
        try:
            setter(str(cache_dir))
        except Exception:
            continue


def _safe_info(yf_ticker, warnings: list[str]) -> dict:
    try:
        with redirect_stderr(StringIO()):
            info = yf_ticker.get_info()
    except Exception:
        warnings.append("Company profile data was not available from Yahoo Finance.")
        try:
            with redirect_stderr(StringIO()):
                info = getattr(yf_ticker, "info", {}) or {}
        except Exception:
            info = {}
    return info or {}


def _safe_history(yf_ticker, period: str, warnings: list[str]) -> list[HistoricalPrice]:
    try:
        with redirect_stderr(StringIO()):
            return _history_rows(yf_ticker.history(period=period, auto_adjust=False))
    except Exception:
        warnings.append("Historical price data was not available from Yahoo Finance.")
        return []


def _safe_analyst_targets(yf_ticker, info: dict, warnings: list[str]) -> AnalystTargets | None:
    try:
        with redirect_stderr(StringIO()):
            return _analyst_targets(yf_ticker, info)
    except Exception:
        warnings.append("Analyst target data was not available from Yahoo Finance.")
        return None


def _safe_finnhub_news(ticker: str, api_key: str, warnings: list[str]) -> list[NewsItem]:
    if not api_key:
        return []

    today = datetime.now(timezone.utc).date()
    params = urlencode(
        {
            "symbol": ticker,
            "from": (today - timedelta(days=30)).isoformat(),
            "to": today.isoformat(),
            "token": api_key,
        }
    )
    url = f"https://finnhub.io/api/v1/company-news?{params}"
    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        warnings.append("Finnhub company news was not available; Yahoo Finance news was used when possible.")
        return []

    news = _finnhub_news_items(payload if isinstance(payload, list) else [])
    if not news:
        warnings.append("Finnhub did not return recent company headlines; Yahoo Finance news was used when possible.")
    return news


def _safe_finnhub_price_target(ticker: str, api_key: str, warnings: list[str]) -> AnalystTargets | None:
    if not api_key:
        return None

    params = urlencode({"symbol": ticker, "token": api_key})
    url = f"https://finnhub.io/api/v1/stock/price-target?{params}"
    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        warnings.append("Finnhub analyst target data was not available.")
        return None

    if not isinstance(payload, dict):
        return None

    target = AnalystTargets(
        low=_first_float(payload, "targetLow", "low"),
        mean=_first_float(payload, "targetMean", "mean"),
        median=_first_float(payload, "targetMedian", "median"),
        high=_first_float(payload, "targetHigh", "high"),
        source="Finnhub",
        last_updated=_first_text(payload, "lastUpdated", "updatedAt"),
    )
    if all(value is None for value in (target.low, target.mean, target.median, target.high, target.last_updated)):
        return None
    return target


def _merge_analyst_targets(primary: AnalystTargets | None, enrichment: AnalystTargets | None) -> AnalystTargets | None:
    if primary is None:
        return enrichment
    if enrichment is None:
        if primary.source:
            return primary
        return AnalystTargets(
            low=primary.low,
            mean=primary.mean,
            median=primary.median,
            high=primary.high,
            number_of_analysts=primary.number_of_analysts,
            recommendation=primary.recommendation,
            source="Yahoo Finance",
            last_updated=primary.last_updated,
        )

    return AnalystTargets(
        low=enrichment.low if enrichment.low is not None else primary.low,
        mean=enrichment.mean if enrichment.mean is not None else primary.mean,
        median=enrichment.median if enrichment.median is not None else primary.median,
        high=enrichment.high if enrichment.high is not None else primary.high,
        number_of_analysts=primary.number_of_analysts,
        recommendation=primary.recommendation,
        source="Finnhub + Yahoo Finance",
        last_updated=enrichment.last_updated or primary.last_updated,
    )


def _safe_yahoo_news(yf_ticker, warnings: list[str]) -> list[NewsItem]:
    raw_news = None
    for attr_name in ("get_news", "news"):
        try:
            with redirect_stderr(StringIO()):
                attr = getattr(yf_ticker, attr_name, None)
                raw_news = attr() if callable(attr) else attr
            if raw_news:
                break
        except Exception:
            raw_news = None
            continue

    news = _news_items(raw_news or [])
    if not news:
        warnings.append("Company news was not available from Yahoo Finance.")
    return news


def _history_rows(history_df: pd.DataFrame) -> list[HistoricalPrice]:
    if history_df is None or history_df.empty:
        return []
    rows = []
    for index, row in history_df.tail(260).iterrows():
        date_value = index.date().isoformat() if hasattr(index, "date") else str(index)
        rows.append(
            HistoricalPrice(
                date=date_value,
                open=_float_or_none(row.get("Open")),
                high=_float_or_none(row.get("High")),
                low=_float_or_none(row.get("Low")),
                close=_float_or_none(row.get("Close")),
                volume=_int_or_none(row.get("Volume")),
            )
        )
    return rows


def _news_items(raw_news: list[dict]) -> list[NewsItem]:
    items = []
    for payload in raw_news[:12]:
        content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
        title = _first_text(content, "title")
        if not title:
            continue
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        link = content.get("canonicalUrl") or content.get("clickThroughUrl") or payload.get("link")
        if isinstance(link, dict):
            link = link.get("url")
        published_at = _published_at(content.get("pubDate") or payload.get("providerPublishTime"))
        summary = _compact_text(_first_text(content, "summary", "description"), max_chars=1200)
        items.append(
            NewsItem(
                title=title,
                publisher=_first_text(provider, "displayName") or _first_text(payload, "publisher"),
                published_at=published_at,
                link=str(link).strip() if link else None,
                summary=summary,
            )
        )
    return items


def _finnhub_news_items(raw_news: list[dict]) -> list[NewsItem]:
    items = []
    for payload in raw_news[:12]:
        title = _first_text(payload, "headline")
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                publisher=_first_text(payload, "source"),
                published_at=_published_at(payload.get("datetime")),
                link=_first_text(payload, "url"),
                summary=_compact_text(_first_text(payload, "summary"), max_chars=1200),
            )
        )
    return items


def _compact_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _published_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _analyst_targets(yf_ticker, info: dict) -> AnalystTargets | None:
    target_payload = _targets_from_methods(yf_ticker)
    low = _first_float(target_payload, "low", "targetLowPrice")
    mean_value = _first_float(target_payload, "mean", "targetMeanPrice")
    median = _first_float(target_payload, "median", "targetMedianPrice")
    high = _first_float(target_payload, "high", "targetHighPrice")
    count = _first_int(target_payload, "numberOfAnalysts", "number_of_analysts")
    recommendation = _first_text(info, "recommendationKey", "recommendationMean")

    if all(value is None for value in (low, mean_value, median, high, count, recommendation)):
        low = _first_float(info, "targetLowPrice")
        mean_value = _first_float(info, "targetMeanPrice")
        median = _first_float(info, "targetMedianPrice")
        high = _first_float(info, "targetHighPrice")
        count = _first_int(info, "numberOfAnalystOpinions")
        recommendation = _first_text(info, "recommendationKey")

    if all(value is None for value in (low, mean_value, median, high, count, recommendation)):
        return None

    return AnalystTargets(
        low=low,
        mean=mean_value,
        median=median,
        high=high,
        number_of_analysts=count,
        recommendation=str(recommendation) if recommendation is not None else None,
        source="Yahoo Finance",
    )


def _targets_from_methods(yf_ticker) -> dict:
    for attr_name in ("analyst_price_targets", "get_analyst_price_targets"):
        attr = getattr(yf_ticker, attr_name, None)
        if attr is None:
            continue
        try:
            payload = attr() if callable(attr) else attr
            if isinstance(payload, dict):
                return payload
            if hasattr(payload, "to_dict"):
                return payload.to_dict()
        except Exception:
            continue
    return {}


def _first_float(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        converted = _float_or_none(value)
        if converted is not None:
            return converted
    return None


def _first_int(payload: dict, *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        converted = _int_or_none(value)
        if converted is not None:
            return converted
    return None


def _first_text(payload: dict, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _float_or_none(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
