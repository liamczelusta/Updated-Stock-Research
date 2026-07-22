"""Find comparable companies from a local ticker-folder library."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable

from stock_research.workbook_discovery import TickerFolder, discover_ticker_folders


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "co",
    "company",
    "corp",
    "corporation",
    "for",
    "from",
    "group",
    "holdings",
    "inc",
    "incorporated",
    "in",
    "international",
    "is",
    "limited",
    "llc",
    "of",
    "plc",
    "the",
    "to",
}
APP_SUPPORT_DIR = (
    Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "StockResearchDashboard"
    if sys.platform.startswith("win")
    else Path.home() / "Library" / "Application Support" / "StockResearchDashboard"
)
PROFILE_INDEX_PATH = APP_SUPPORT_DIR / "company_profile_index.json"


@dataclass(frozen=True)
class CompanyProfile:
    """Lightweight Yahoo profile fields used for similarity ranking."""

    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class SimilarCompany:
    """One suggested comparable company."""

    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    score: float
    reason: str


@dataclass(frozen=True)
class CompanyProfileIndex:
    """Cached Yahoo profile index for the local ticker-folder library."""

    root: str
    updated_at: str
    profiles: tuple[CompanyProfile, ...]
    missing_tickers: tuple[str, ...] = ()


def available_library_tickers(root: str | Path) -> tuple[str, ...]:
    """Return tickers available in the local folder library."""

    return tuple(folder.ticker for folder in discover_ticker_folders(root))


def find_similar_companies(
    root: str | Path,
    active_tickers: Iterable[str],
    theme: str,
    profile_lookup,
    max_profiles: int = 250,
    max_results: int = 8,
) -> tuple[SimilarCompany, ...]:
    """Rank local-library tickers using Yahoo profile data and a user theme."""

    folders = discover_ticker_folders(root)
    active = {ticker.strip().upper() for ticker in active_tickers if ticker.strip()}
    theme_terms = _terms(theme)
    if not folders or not theme_terms:
        return ()

    active_profiles = [
        profile_lookup(ticker)
        for ticker in sorted(active)
        if ticker
    ]
    reference_terms = set(theme_terms)
    reference_sectors = set()
    reference_industries = set()
    for profile in active_profiles:
        if profile is None:
            continue
        reference_terms.update(_profile_terms(profile))
        if profile.sector:
            reference_sectors.add(profile.sector.lower())
        if profile.industry:
            reference_industries.add(profile.industry.lower())

    candidates = []
    for folder in folders[:max_profiles]:
        if folder.ticker in active:
            continue
        profile = profile_lookup(folder.ticker)
        if profile is None:
            continue
        score, reasons = _score_profile(profile, theme_terms, reference_terms, reference_sectors, reference_industries)
        if score <= 0:
            continue
        candidates.append(
            SimilarCompany(
                ticker=profile.ticker,
                name=profile.name,
                sector=profile.sector,
                industry=profile.industry,
                score=round(score, 1),
                reason="; ".join(reasons[:3]),
            )
        )

    return tuple(sorted(candidates, key=lambda item: (-item.score, item.ticker))[:max_results])


def find_similar_companies_from_profiles(
    profiles: Iterable[CompanyProfile],
    active_tickers: Iterable[str],
    theme: str,
    max_results: int = 8,
) -> tuple[SimilarCompany, ...]:
    """Rank comparable companies from an existing local profile index."""

    active = {ticker.strip().upper() for ticker in active_tickers if ticker.strip()}
    theme_terms = _terms(theme)
    profile_map = {profile.ticker.upper(): profile for profile in profiles}
    if not profile_map or not theme_terms:
        return ()

    reference_terms = set(theme_terms)
    reference_sectors = set()
    reference_industries = set()
    for ticker in active:
        profile = profile_map.get(ticker)
        if profile is None:
            continue
        reference_terms.update(_profile_terms(profile))
        if profile.sector:
            reference_sectors.add(profile.sector.lower())
        if profile.industry:
            reference_industries.add(profile.industry.lower())

    candidates = []
    for profile in profile_map.values():
        if profile.ticker.upper() in active:
            continue
        score, reasons = _score_profile(profile, theme_terms, reference_terms, reference_sectors, reference_industries)
        if score <= 0:
            continue
        candidates.append(
            SimilarCompany(
                ticker=profile.ticker,
                name=profile.name,
                sector=profile.sector,
                industry=profile.industry,
                score=round(score, 1),
                reason="; ".join(reasons[:3]),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.ticker))[:max_results])


def build_company_profile_index(root: str | Path, profile_lookup) -> CompanyProfileIndex:
    """Fetch Yahoo profiles for all valid ticker folders and save them locally."""

    folders = discover_ticker_folders(root)
    profiles = []
    missing = []
    for folder in folders:
        profile = profile_lookup(folder.ticker)
        if profile is None:
            missing.append(folder.ticker)
            continue
        profiles.append(profile)

    index = CompanyProfileIndex(
        root=str(Path(root).expanduser()),
        updated_at=datetime.now(timezone.utc).isoformat(),
        profiles=tuple(sorted(profiles, key=lambda item: item.ticker)),
        missing_tickers=tuple(missing),
    )
    save_company_profile_index(index)
    return index


def load_company_profile_index(root: str | Path) -> CompanyProfileIndex | None:
    """Load the saved company profile index for a root folder, if available."""

    try:
        payload = json.loads(PROFILE_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("root") != str(Path(root).expanduser()):
        return None
    profiles = tuple(_profile_from_payload(item) for item in payload.get("profiles", []) if isinstance(item, dict))
    missing = tuple(item for item in payload.get("missing_tickers", []) if isinstance(item, str))
    return CompanyProfileIndex(
        root=str(payload.get("root", "")),
        updated_at=str(payload.get("updated_at", "")),
        profiles=profiles,
        missing_tickers=missing,
    )


def save_company_profile_index(index: CompanyProfileIndex) -> None:
    """Persist the company profile index locally."""

    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "root": index.root,
        "updated_at": index.updated_at,
        "profiles": [_profile_payload(profile) for profile in index.profiles],
        "missing_tickers": list(index.missing_tickers),
    }
    PROFILE_INDEX_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def yahoo_company_profile(ticker: str) -> CompanyProfile | None:
    """Fetch a lightweight Yahoo Finance company profile."""

    clean_ticker = ticker.strip().upper()
    if not clean_ticker:
        return None
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(clean_ticker)
        try:
            info = yf_ticker.get_info() or {}
        except Exception:
            info = getattr(yf_ticker, "info", {}) or {}
    except Exception:
        return None

    return CompanyProfile(
        ticker=clean_ticker,
        name=_first_text(info, "shortName", "longName"),
        sector=_first_text(info, "sector"),
        industry=_first_text(info, "industry"),
        summary=_first_text(info, "longBusinessSummary"),
    )


def _score_profile(
    profile: CompanyProfile,
    theme_terms: set[str],
    reference_terms: set[str],
    reference_sectors: set[str],
    reference_industries: set[str],
) -> tuple[float, list[str]]:
    text_terms = _profile_terms(profile)
    theme_hits = sorted(theme_terms & text_terms)
    reference_hits = sorted((reference_terms & text_terms) - theme_terms)
    score = 0.0
    reasons = []

    if theme_hits:
        score += 45 + min(20, len(theme_hits) * 5)
        reasons.append(f"matches theme terms: {', '.join(theme_hits[:4])}")
    if profile.industry and profile.industry.lower() in reference_industries:
        score += 25
        reasons.append(f"same industry: {profile.industry}")
    elif profile.sector and profile.sector.lower() in reference_sectors:
        score += 12
        reasons.append(f"same sector: {profile.sector}")
    if reference_hits:
        score += min(15, len(reference_hits) * 2)
        reasons.append(f"overlapping profile terms: {', '.join(reference_hits[:4])}")

    return score, reasons


def _profile_terms(profile: CompanyProfile) -> set[str]:
    return _terms(" ".join(part or "" for part in (profile.name, profile.sector, profile.industry, profile.summary)))


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9&.-]{1,}", text.lower())
        if token not in STOP_WORDS and len(token) > 2
    }


def _first_text(payload: dict, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _profile_payload(profile: CompanyProfile) -> dict[str, str | None]:
    return {
        "ticker": profile.ticker,
        "name": profile.name,
        "sector": profile.sector,
        "industry": profile.industry,
        "summary": profile.summary,
    }


def _profile_from_payload(payload: dict) -> CompanyProfile:
    return CompanyProfile(
        ticker=str(payload.get("ticker", "")).upper(),
        name=_payload_text(payload, "name"),
        sector=_payload_text(payload, "sector"),
        industry=_payload_text(payload, "industry"),
        summary=_payload_text(payload, "summary"),
    )


def _payload_text(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    return str(value).strip() if value is not None and str(value).strip() else None
