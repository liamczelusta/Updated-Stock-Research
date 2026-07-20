from datetime import datetime, timezone

from stock_research.market_data import _compact_text, _finnhub_news_items


def test_finnhub_news_preserves_compact_summary() -> None:
    payload = [
        {
            "headline": "Company raises guidance",
            "source": "Finnhub",
            "datetime": 1783516500,
            "url": "https://example.com/news",
            "summary": "  Revenue   guidance improved after stronger demand.  ",
        }
    ]

    item = _finnhub_news_items(payload)[0]

    assert item.title == "Company raises guidance"
    assert item.publisher == "Finnhub"
    assert item.published_at == datetime.fromtimestamp(1783516500, timezone.utc)
    assert item.summary == "Revenue guidance improved after stronger demand."


def test_compact_text_caps_long_news_summary() -> None:
    text = _compact_text("x" * 1400, max_chars=1200)

    assert text is not None
    assert len(text) == 1200
    assert text.endswith("...")
