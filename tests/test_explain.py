import json
from typing import Any

import pytest
import requests

from portfolio_risk.explain import (
    SYSTEM_PROMPT,
    Explanation,
    LLMConfig,
    LLMError,
    build_messages,
    explain,
    explain_checked,
)

API_KEY = "LLM_test_secret_key"
CONFIG = LLMConfig(api_key=API_KEY, base_url="https://api.example.com/v1/", model="muse-test")
REPORT = {"total_value": 91512.0, "risk": {"beta": 1.28}}
GROUNDED = "Портфель стоит 91 512 долларов, бета 1,28."
INVENTED = "Портфель стоит 91 512 долларов, а две бумаги вместе весят 66%."


class FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class FakePost:
    """Answers each call with the next canned response; the last one repeats."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        response = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response


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


def test_russian_is_the_default_answer_language() -> None:
    system, _ = build_messages(REPORT)

    assert system["content"] == SYSTEM_PROMPT
    assert "русским" in SYSTEM_PROMPT


def test_prompt_counts_sums_and_ratios_as_recomputing() -> None:
    # An answer added two weights into "together 66%", a number the report does not hold.
    assert "не складывай, не вычитай и не дели" in SYSTEM_PROMPT


def test_prompt_asks_for_tickers_instead_of_company_names() -> None:
    # An answer said "Apple" for AAPL: company names are not in the report.
    assert "Называй бумаги тикерами" in SYSTEM_PROMPT


def test_english_answer_keeps_the_rules_and_asks_for_english() -> None:
    system, _ = build_messages(REPORT, language="en")

    assert "Не давай рекомендаций" in system["content"]
    assert "английским" in system["content"]
    assert "русским" not in system["content"]
    assert "in English" in system["content"]


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


def test_explain_asks_for_the_requested_language() -> None:
    post = FakePost(_completion("The portfolio is riskier than the market."))

    explain(REPORT, CONFIG, post=post, language="en")

    assert post.calls[0]["json"]["messages"] == build_messages(REPORT, language="en")


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


def test_checked_answer_with_report_numbers_only_takes_one_call() -> None:
    post = FakePost(_completion(GROUNDED))

    assert explain_checked(REPORT, CONFIG, post=post) == Explanation(GROUNDED)
    assert len(post.calls) == 1


def test_invented_numbers_are_sent_back_once_by_name() -> None:
    post = FakePost(_completion(INVENTED), _completion(GROUNDED))

    result = explain_checked(REPORT, CONFIG, post=post, language="en")

    assert result == Explanation(GROUNDED)
    first, retry = (call["json"]["messages"] for call in post.calls)
    assert first == build_messages(REPORT, language="en")
    assert retry[:-2] == first
    assert retry[-2] == {"role": "assistant", "content": INVENTED}
    assert retry[-1]["role"] == "user"
    assert "66%" in retry[-1]["content"]


def test_numbers_still_invented_after_the_retry_are_returned_as_unverified() -> None:
    retried = "Портфель стоит 91 512 долларов, а в кризис потеряет 37%."
    post = FakePost(_completion(INVENTED), _completion(retried))

    assert explain_checked(REPORT, CONFIG, post=post) == Explanation(retried, ("37%",))


def test_the_answer_with_fewer_invented_numbers_is_kept() -> None:
    worse = "Портфель стоит 91 512 долларов: вместе 66%, а в кризис минус 37%."
    post = FakePost(_completion(INVENTED), _completion(worse))

    assert explain_checked(REPORT, CONFIG, post=post) == Explanation(INVENTED, ("66%",))


def test_retry_is_skipped_when_a_second_answer_would_overrun_the_time_budget() -> None:
    post = FakePost(_completion(INVENTED), _completion(GROUNDED))
    clock = iter([0.0, 30.0]).__next__

    result = explain_checked(REPORT, CONFIG, post=post, time_budget=50, clock=clock)

    assert result == Explanation(INVENTED, ("66%",))
    assert len(post.calls) == 1


def test_calls_are_cut_off_at_the_time_budget() -> None:
    post = FakePost(_completion(INVENTED), _completion(GROUNDED))
    clock = iter([0.0, 10.0]).__next__

    explain_checked(REPORT, CONFIG, post=post, time_budget=50, clock=clock)

    assert [call["timeout"] for call in post.calls] == [50, 40]


def test_failed_retry_keeps_the_first_answer_with_its_unverified_numbers() -> None:
    post = FakePost(_completion(INVENTED), requests.Timeout("read timed out"))

    assert explain_checked(REPORT, CONFIG, post=post) == Explanation(INVENTED, ("66%",))
