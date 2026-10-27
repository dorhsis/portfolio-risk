import json
from typing import Any

import pytest
import requests

from portfolio_risk.explain import LLMConfig, LLMError, build_messages, explain

API_KEY = "LLM_test_secret_key"
CONFIG = LLMConfig(api_key=API_KEY, base_url="https://api.example.com/v1/", model="muse-test")
REPORT = {"total_value": 91512.0, "risk": {"beta": 1.28}}


class FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class FakePost:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _completion(content: str | None, finish_reason: str = "stop") -> FakeResponse:
    message = {"role": "assistant", "content": content}
    return FakeResponse(200, {"choices": [{"message": message, "finish_reason": finish_reason}]})


def test_messages_forbid_recommendations_and_carry_the_report_as_json() -> None:
    system, user = build_messages(REPORT)

    assert system["role"] == "system"
    assert "Не давай рекомендаций" in system["content"]
    assert user["role"] == "user"
    payload = user["content"][user["content"].index("{") :]
    assert json.loads(payload) == REPORT


def test_config_reads_environment_with_defaults() -> None:
    config = LLMConfig.from_env(
        {"LLM_API_KEY": API_KEY, "LLM_BASE_URL": "https://x/v1", "LLM_MODEL": "m"}
    )

    assert config == LLMConfig(api_key=API_KEY, base_url="https://x/v1", model="m")


def test_config_token_budget_can_be_overridden() -> None:
    env = {"LLM_API_KEY": API_KEY, "LLM_BASE_URL": "u", "LLM_MODEL": "m", "LLM_MAX_TOKENS": "900"}

    assert LLMConfig.from_env(env).max_completion_tokens == 900


@pytest.mark.parametrize("raw", ["lots", "0"])
def test_config_rejects_invalid_token_budget(raw: str) -> None:
    env = {"LLM_API_KEY": API_KEY, "LLM_BASE_URL": "u", "LLM_MODEL": "m", "LLM_MAX_TOKENS": raw}

    with pytest.raises(LLMError, match="LLM_MAX_TOKENS must be a positive integer"):
        LLMConfig.from_env(env)


def test_config_repr_hides_the_api_key() -> None:
    assert API_KEY not in repr(CONFIG)


def test_config_names_every_missing_variable() -> None:
    with pytest.raises(LLMError, match="LLM_API_KEY, LLM_MODEL"):
        LLMConfig.from_env({"LLM_BASE_URL": "u"})


def test_explain_posts_chat_completion_and_returns_trimmed_text() -> None:
    post = FakePost(_completion("  Портфель рискованнее рынка.  "))

    text = explain(REPORT, CONFIG, post=post)

    assert text == "Портфель рискованнее рынка."
    call = post.calls[0]
    assert call["url"] == "https://api.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert call["json"]["model"] == "muse-test"
    assert call["json"]["reasoning_effort"] == "low"
    assert call["json"]["max_completion_tokens"] == CONFIG.max_completion_tokens
    assert call["json"]["messages"] == build_messages(REPORT)


def test_http_error_reports_status_and_api_message() -> None:
    body = {"error": {"code": "invalid_api_key", "message": "Unauthorized"}}
    post = FakePost(FakeResponse(401, body))

    with pytest.raises(LLMError, match="HTTP 401.*Unauthorized"):
        explain(REPORT, CONFIG, post=post)


def test_exhausted_token_budget_suggests_raising_it() -> None:
    post = FakePost(_completion(None, finish_reason="length"))

    with pytest.raises(LLMError, match="LLM_MAX_TOKENS"):
        explain(REPORT, CONFIG, post=post)


def test_empty_answer_is_an_error() -> None:
    with pytest.raises(LLMError, match="empty"):
        explain(REPORT, CONFIG, post=FakePost(_completion("")))


def test_network_failure_becomes_llm_error_without_leaking_the_key() -> None:
    post = FakePost(requests.ConnectionError(f"failed with header Bearer {API_KEY}"))

    with pytest.raises(LLMError) as error:
        explain(REPORT, CONFIG, post=post)

    assert API_KEY not in str(error.value)
