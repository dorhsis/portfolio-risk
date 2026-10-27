"""Plain-language explanation of a computed report via an OpenAI-compatible chat API.

The model only narrates numbers from `report_to_dict`; it never computes them. One endpoint is
called, so plain `requests` is used instead of a full SDK.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import requests

SYSTEM_PROMPT = """\
Ты объясняешь отчёт о риске инвестиционного портфеля частному инвестору простым русским языком.

Правила:
- Используй только цифры из JSON-отчёта. Ничего не пересчитывай и не придумывай, можно только \
округлять.
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


class LLMError(RuntimeError):
    """The explanation could not be produced."""


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


Post = Callable[..., _Response]


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


def build_messages(report: Mapping[str, Any]) -> list[dict[str, str]]:
    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Отчёт по портфелю:\n{report_json}"},
    ]


def explain(report: Mapping[str, Any], config: LLMConfig, post: Post = requests.post) -> str:
    try:
        response = post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": config.model,
                "messages": build_messages(report),
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


def _json_or_empty(response: _Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
