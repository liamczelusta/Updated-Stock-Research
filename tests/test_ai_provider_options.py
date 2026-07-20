from stock_research.ai.providers import _supports_temperature


def test_newer_claude_models_do_not_send_temperature() -> None:
    assert not _supports_temperature("claude-sonnet-5")
    assert not _supports_temperature("claude-opus-4-8")


def test_haiku_keeps_temperature() -> None:
    assert _supports_temperature("claude-haiku-4-5-20251001")
