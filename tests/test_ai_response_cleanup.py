from stock_research.dashboard.views import _clean_ai_response


def test_clean_ai_response_repairs_punctuation_spacing() -> None:
    response = "At $1,674,the trailing P/E is 57x,but the forward P/E is 8x."

    assert _clean_ai_response(response) == "At $1,674, the trailing P/E is 57x, but the forward P/E is 8x."


def test_clean_ai_response_leaves_normal_text_alone() -> None:
    response = "I would be cautious here. Revenue growth is slowing, but margins remain solid."

    assert _clean_ai_response(response) == response


def test_clean_ai_response_removes_markdown_markers() -> None:
    response = "**Revenue** was `$20.3B` versus the estimate."

    assert _clean_ai_response(response) == "Revenue was $20.3B versus the estimate."


def test_clean_ai_response_merges_accidental_web_search_line_breaks() -> None:
    response = "I would be constructive.\nRevenue is improving,\nand margins are expanding.\n\nThe risk is valuation."

    assert _clean_ai_response(response) == (
        "I would be constructive. Revenue is improving, and margins are expanding.\n\n"
        "The risk is valuation."
    )
