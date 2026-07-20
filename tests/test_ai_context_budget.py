import json

from stock_research.ai.providers import _cap_payload


def test_payload_trimming_preserves_early_market_news() -> None:
    evidence = {
        "company": {"ticker": "TEST"},
        "scores": {"overall_investment": 70},
        "market_data": {
            "news": [
                {
                    "title": "Company raises guidance",
                    "summary": "Management lifted guidance after stronger demand.",
                }
            ]
        },
        "loaded_workbook_comparison": [{"ticker": f"T{i}", "notes": "x" * 500} for i in range(40)],
    }
    payload = (
        "Evidence packet:\n"
        f"{json.dumps(evidence)}\n\n"
        "User question:\n"
        "What does the news say?"
    )

    trimmed = _cap_payload(payload, max_chars=1800)

    assert "Company raises guidance" in trimmed
    assert "Management lifted guidance" in trimmed
    assert "What does the news say?" in trimmed
