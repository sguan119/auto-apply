"""tests.test_llm_transport — CLI vs HTTP complete_prompt, no live network."""

from __future__ import annotations

import pytest

from autoapply.core.config import LLMSettings
from autoapply.core.llm.transport import LLMTransportError, _chat_completions_url, complete_prompt


def test_http_reads_openai_compatible_message(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"ranked":[]}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("autoapply.core.llm.transport.httpx.post", fake_post)
    text = complete_prompt(
        "rank these jobs",
        LLMSettings(
            transport="http",
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            timeout=15,
        ),
    )
    assert text == '{"ranked":[]}'
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["json"]["messages"][0]["content"] == "rank these jobs"


def test_http_requires_api_key():
    with pytest.raises(LLMTransportError, match="LLM_API_KEY"):
        complete_prompt(
            "hi",
            LLMSettings(transport="http", base_url="https://api.deepseek.com", api_key=None),
        )


def test_http_requires_base_url():
    with pytest.raises(LLMTransportError, match="base_url"):
        complete_prompt(
            "hi",
            LLMSettings(transport="http", api_key="sk-test", base_url=None),
        )


def test_http_does_not_put_key_in_error(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "nope"

        def raise_for_status(self) -> None:
            raise __import__("httpx").HTTPStatusError(
                "401",
                request=__import__("httpx").Request("POST", "https://api.deepseek.com/v1/chat/completions"),
                response=__import__("httpx").Response(401, text="nope"),
            )

    def fake_post(url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("autoapply.core.llm.transport.httpx.post", fake_post)
    secret = "sk-super-secret-do-not-leak"
    with pytest.raises(LLMTransportError) as exc_info:
        complete_prompt(
            "hi",
            LLMSettings(
                transport="http",
                api_key=secret,
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            ),
        )
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    ("base", "want"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url(base, want):
    assert _chat_completions_url(base) == want
