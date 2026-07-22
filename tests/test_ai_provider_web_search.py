from stock_research.ai.providers import AISettings, ClaudeMessagesClient


def test_claude_client_adds_web_search_tool_when_enabled() -> None:
    captured = {}

    class CapturingClient(ClaudeMessagesClient):
        def _create_message(self, request_params: dict) -> object:
            captured.update(request_params)
            return {"content": [{"type": "text", "text": "ok"}]}

    client = CapturingClient(
        AISettings(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            api_key="test",
            max_tokens=200,
            web_search_enabled=True,
            web_search_max_uses=2,
        )
    )

    assert client.complete("system", "payload") == "ok"
    assert captured["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}]
    assert captured["tool_choice"] == {"type": "tool", "name": "web_search"}
