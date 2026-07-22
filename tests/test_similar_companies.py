from pathlib import Path

from stock_research.similar_companies import CompanyProfile, find_similar_companies, find_similar_companies_from_profiles


def test_find_similar_companies_uses_yahoo_profile_theme_and_industry(tmp_path: Path) -> None:
    for ticker in ("NUE", "STLD", "CLF", "AAPL"):
        (tmp_path / ticker).mkdir()

    profiles = {
        "NUE": CompanyProfile("NUE", "Nucor", "Basic Materials", "Steel", "steel producer"),
        "STLD": CompanyProfile("STLD", "Steel Dynamics", "Basic Materials", "Steel", "steel mills"),
        "CLF": CompanyProfile("CLF", "Cleveland-Cliffs", "Basic Materials", "Steel", "iron ore and steel"),
        "AAPL": CompanyProfile("AAPL", "Apple", "Technology", "Consumer Electronics", "phones and services"),
    }

    results = find_similar_companies(
        tmp_path,
        active_tickers=("NUE", "STLD"),
        theme="steel",
        profile_lookup=profiles.get,
    )

    assert [result.ticker for result in results] == ["CLF"]


def test_find_similar_companies_from_profiles_uses_entire_index_not_alphabetical_slice() -> None:
    profiles = [
        CompanyProfile("AAPL", "Apple", "Technology", "Consumer Electronics", "phones and services"),
        CompanyProfile("NUE", "Nucor", "Basic Materials", "Steel", "steel producer"),
        CompanyProfile("STLD", "Steel Dynamics", "Basic Materials", "Steel", "steel mills"),
        CompanyProfile("X", "United States Steel", "Basic Materials", "Steel", "steel producer"),
    ]

    results = find_similar_companies_from_profiles(profiles, active_tickers=("NUE", "STLD"), theme="steel")

    assert [result.ticker for result in results] == ["X"]
