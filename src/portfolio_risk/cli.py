"""Command line entry point: `portfolio-risk portfolio.csv [--json] [--explain]`."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from portfolio_risk.explain import Explainer, LLMError, explain_with_env
from portfolio_risk.market_data import Loader, MarketDataError, load_market_data
from portfolio_risk.portfolio import load_portfolio
from portfolio_risk.report import Report, build_report, render_text, report_to_dict


def main(
    argv: Sequence[str] | None = None,
    loader: Loader = load_market_data,
    explainer: Explainer = explain_with_env,
) -> int:
    args = _parser().parse_args(argv)
    benchmark = args.benchmark.upper()
    try:
        holdings = load_portfolio(args.portfolio)
        market = loader([h.ticker for h in holdings], benchmark, not args.no_factors)
        report = build_report(holdings, market, benchmark, args.lookback_years)
    except (OSError, ValueError, MarketDataError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    payload = report_to_dict(report)
    explanation = None
    exit_code = 0
    if args.explain:
        try:
            explanation = explainer(payload)
        except LLMError as error:
            print(f"Ошибка LLM: {error}", file=sys.stderr)
            exit_code = 1

    print(_render(report, payload, explanation, as_json=args.json))
    return exit_code


def _render(report: Report, payload: dict[str, Any], explanation: str | None, as_json: bool) -> str:
    if as_json:
        if explanation is not None:
            payload = {**payload, "explanation": explanation}
        return json.dumps(payload, ensure_ascii=False, indent=2)
    text = render_text(report)
    return f"{text}\n\nОБЪЯСНЕНИЕ\n{explanation}" if explanation is not None else text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portfolio-risk",
        description="Риск-аналитика портфеля американских акций",
    )
    parser.add_argument("portfolio", type=Path, help="CSV с колонками ticker,shares")
    parser.add_argument("--benchmark", default="SPY", help="тикер бенчмарка (по умолчанию SPY)")
    parser.add_argument(
        "--lookback-years",
        type=_positive_int,
        default=3,
        help="окно для оценки риска в годах (по умолчанию 3)",
    )
    parser.add_argument("--json", action="store_true", help="вывести отчёт в JSON")
    parser.add_argument(
        "--no-factors", action="store_true", help="не загружать факторы Fama–French"
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="добавить объяснение от LLM (настройки LLM_* в окружении или .env)",
    )
    return parser


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be positive, got {raw}")
    return value


if __name__ == "__main__":
    sys.exit(main())
