"""Plain-language explanation of a computed report via an OpenAI-compatible chat API.

The model only narrates numbers from `report_to_dict`; it never computes them. `explain_checked`
holds it to that: an answer with numbers the report does not contain is sent back once, and
whatever is still missing is returned as unverified. One endpoint is called, so plain `requests`
is used instead of a full SDK.
"""

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import requests
from dotenv import find_dotenv, load_dotenv

from portfolio_risk.grounding import ungrounded_numbers

# The rules stay in Russian whatever the answer language, so every language is held to the same
# rules; only the language of the answer changes.
_PROMPT = """\
Ты объясняешь отчёт о риске инвестиционного портфеля частному инвестору простым {language} языком.

Правила:
- Используй только цифры из JSON-отчёта и ничего не придумывай. Цифры можно округлять, но \
не складывай, не вычитай и не дели их: общая доля нескольких бумаг, разница и «в N раз» — тоже \
пересчёт. Говоря о нескольких бумагах, называй цифру каждой.
- Называй бумаги тикерами из отчёта (AAPL, а не Apple): названий компаний в отчёте нет.
- Не давай рекомендаций купить, продать или держать конкретные бумаги и не прогнозируй цены. \
Описывай, где риск, а не что делать.
- Доли и доходности в JSON — десятичные дроби: 0.15 означает 15%. Суммы — в долларах.
- risk_share — доля позиции в общем риске портфеля. Если она заметно больше weight, позиция \
рискует больше, чем весит, — скажи об этом.
- Сравни волатильность и бету портфеля с бенчмарком.
- Назови самый тяжёлый стресс-сценарий в процентах и долларах. Если у него есть \
proxied_by_beta, предупреди, что для этих бумаг это оценка.
- Если факторы доступны, назови самые заметные перекосы; если нет — не упоминай их.
- 5–7 предложений, без заголовков, списков и markdown."""
LANGUAGES = {"ru": "русским", "en": "английским"}
SYSTEM_PROMPT = _PROMPT.format(language=LANGUAGES["ru"])
_RETRY_PROMPT = """\
В ответе есть цифры, которых нет в отчёте: {numbers}. Перепиши ответ целиком, на том же языке и \
по тем же правилам: бери цифры только из отчёта, округлять можно, но не складывай, не вычитай и \
не дели их."""


class LLMError(RuntimeError):
    """The explanation could not be produced."""


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


@dataclass(frozen=True)
class Explanation:
    text: str
    # Numbers the answer still holds that the report does not, as written in the text.
    unverified: tuple[str, ...] = ()


Post = Callable[..., _Response]
Explainer = Callable[[dict[str, Any]], str]
# (report, answer language) -> explanation checked against the report
CheckedExplainer = Callable[[dict[str, Any], str], Explanation]


@dataclass(frozen=True)
class LLMConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    # Reasoning models spend part of this budget thinking before they answer.
    max_completion_tokens: int = 4000
    reasoning_effort: str = "low"
    timeout_seconds: float = 120

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "LLMConfig":
        required = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise LLMError(f"set {', '.join(missing)} in the environment or .env")
        config = cls(
            api_key=env["LLM_API_KEY"], base_url=env["LLM_BASE_URL"], model=env["LLM_MODEL"]
        )
        raw_budget = env.get("LLM_MAX_TOKENS")
        if raw_budget:
            config = replace(config, max_completion_tokens=_positive_int(raw_budget))
        return config


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise LLMError(f"LLM_MAX_TOKENS must be a positive integer, got {raw!r}")
    return value


def system_prompt(language: str = "ru") -> str:
    prompt = _PROMPT.format(language=LANGUAGES[language])
    if language == "en":
        prompt += "\n- Write the whole answer in English."
    return prompt


def build_messages(report: Mapping[str, Any], language: str = "ru") -> list[dict[str, str]]:
    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": system_prompt(language)},
        {"role": "user", "content": f"Отчёт по портфелю:\n{report_json}"},
    ]


def explain(
    report: Mapping[str, Any],
    config: LLMConfig,
    post: Post = requests.post,
    language: str = "ru",
) -> str:
    """One answer as the model wrote it, without the numbers check: the prompt's own quality."""
    return _complete(build_messages(report, language), config, post)


def explain_checked(
    report: Mapping[str, Any],
    config: LLMConfig,
    post: Post = requests.post,
    language: str = "ru",
    time_budget: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Explanation:
    """An answer whose numbers are checked against the report.

    Numbers the report does not contain are named back to the model once. The retry starts only
    if one more answer as slow as the first fits in `time_budget`, and every call is cut off at
    the budget. If the retry fails or still invents numbers, the answer with fewer of them is
    returned with those numbers listed as unverified.
    """
    started = clock()
    if time_budget is not None:
        config = replace(config, timeout_seconds=min(config.timeout_seconds, time_budget))
    messages = build_messages(report, language)
    first = _checked(_complete(messages, config, post), report)
    if not first.unverified:
        return first

    if time_budget is not None:
        elapsed = clock() - started
        remaining = time_budget - elapsed
        if remaining < elapsed:
            return first
        config = replace(config, timeout_seconds=min(config.timeout_seconds, remaining))
    correction = _RETRY_PROMPT.format(numbers=", ".join(first.unverified))
    retry_messages = [
        *messages,
        {"role": "assistant", "content": first.text},
        {"role": "user", "content": correction},
    ]
    try:
        retried = _checked(_complete(retry_messages, config, post), report)
    except LLMError:
        return first
    return min(retried, first, key=lambda answer: len(answer.unverified))


def _checked(text: str, report: Mapping[str, Any]) -> Explanation:
    return Explanation(text, tuple(ungrounded_numbers(text, report)))


def _complete(messages: list[dict[str, str]], config: LLMConfig, post: Post) -> str:
    try:
        response = post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": config.model,
                "messages": messages,
                "reasoning_effort": config.reasoning_effort,
                "max_completion_tokens": config.max_completion_tokens,
            },
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as error:
        details = str(error).replace(config.api_key, "***")
        raise LLMError(f"LLM API request failed: {details}") from None

    body = _json_or_empty(response)
    if response.status_code != 200:
        message = body.get("error", {}).get("message", "no error details")
        raise LLMError(f"LLM API returned HTTP {response.status_code}: {message}")

    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("LLM API returned an unexpected response shape") from None
    if not content:
        if choice.get("finish_reason") == "length":
            raise LLMError(
                f"model spent all {config.max_completion_tokens} tokens before answering; "
                "raise LLM_MAX_TOKENS"
            )
        raise LLMError("LLM API returned an empty answer")
    return str(content).strip()


def explain_with_env(report: dict[str, Any], language: str = "ru") -> str:
    """Explain with the LLM configured in the environment or a .env in the working directory."""
    return explain(report, _config_from_env(), language=language)


def explain_checked_with_env(
    report: dict[str, Any], language: str = "ru", time_budget: float | None = None
) -> Explanation:
    """`explain_checked` with the LLM configured in the environment or a .env."""
    return explain_checked(report, _config_from_env(), language=language, time_budget=time_budget)


def _config_from_env() -> LLMConfig:
    load_dotenv(find_dotenv(usecwd=True))
    return LLMConfig.from_env(os.environ)


def _json_or_empty(response: _Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
