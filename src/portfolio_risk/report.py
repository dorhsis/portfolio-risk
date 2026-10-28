"""Assemble every metric into one Report and render it as Russian text or a JSON-ready dict.

The dict is the contract for anything downstream (API, LLM summaries): numbers are computed
here, never by the consumer.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from portfolio_risk.concentration import (
    Concentration,
    concentration,
    group_weights,
    position_weights,
)
from portfolio_risk.correlation import average_pairwise_correlation, highly_correlated_pairs
from portfolio_risk.factors import FactorExposure, factor_exposures
from portfolio_risk.portfolio import Holding
from portfolio_risk.risk import (
    Drawdown,
    ValueAtRisk,
    aligned_returns,
    annualized_volatility,
    beta,
    historical_var,
    max_drawdown,
    portfolio_returns,
    risk_contributions,
    wealth_index,
)
from portfolio_risk.stress import HISTORICAL_SCENARIOS, ScenarioResult, run_scenario

MIN_OBSERVATIONS = 60
CORRELATION_ALERT = 0.8
FACTOR_LABELS = {
    "Mkt-RF": "Рынок",
    "SMB": "Малые компании",
    "HML": "Value",
    "RMW": "Прибыльность",
    "CMA": "Консервативные инвестиции",
    "Mom": "Моментум",
}


class InsufficientHistoryError(ValueError):
    """The holdings share too few trading days to estimate risk."""


@dataclass(frozen=True)
class MarketData:
    prices: pd.DataFrame
    sectors: Mapping[str, str]
    factors: pd.DataFrame | None
    factor_error: str | None = None


@dataclass(frozen=True)
class Position:
    ticker: str
    shares: float
    price: float
    value: float
    weight: float
    risk_share: float
    beta: float
    volatility: float


@dataclass(frozen=True)
class Report:
    as_of: pd.Timestamp
    benchmark: str
    total_value: float
    window_start: pd.Timestamp
    observations: int
    positions: list[Position]
    sectors: dict[str, float]
    concentration: Concentration
    volatility: float
    benchmark_volatility: float
    beta: float
    drawdown: Drawdown
    value_at_risk: ValueAtRisk
    average_correlation: float | None
    correlated_pairs: list[tuple[str, str, float]]
    factor_exposure: FactorExposure | None
    factor_note: str | None
    stress: list[ScenarioResult]


def build_report(
    holdings: list[Holding],
    market: MarketData,
    benchmark: str = "SPY",
    lookback_years: int = 3,
) -> Report:
    prices = market.prices
    columns = list(dict.fromkeys([*(h.ticker for h in holdings), benchmark]))
    _require_prices(prices, columns)

    as_of = pd.Timestamp(prices.index[-1])
    last_prices = prices[columns].ffill().iloc[-1]
    # From here on every holding is a share count, whichever way it was entered.
    holdings = [Holding(h.ticker, h.shares_at(float(last_prices[h.ticker]))) for h in holdings]
    weights = position_weights(holdings, last_prices)

    window = prices.loc[as_of - pd.DateOffset(years=lookback_years) :, columns]
    returns = aligned_returns(window)
    if len(returns) < MIN_OBSERVATIONS:
        raise InsufficientHistoryError(_short_history_message(prices, columns, len(returns)))
    window_start = pd.Timestamp(window.index[window.index < returns.index[0]][-1])

    portfolio = portfolio_returns(returns, weights)
    benchmark_returns = returns[benchmark]
    risk_shares = risk_contributions(returns, weights)
    shares = {h.ticker: h.shares for h in holdings}
    positions = [
        Position(
            ticker=ticker,
            shares=shares[ticker],
            price=float(last_prices[ticker]),
            value=shares[ticker] * float(last_prices[ticker]),
            weight=float(weights[ticker]),
            risk_share=float(risk_shares[ticker]),
            beta=beta(returns[ticker], benchmark_returns),
            volatility=annualized_volatility(returns[ticker]),
        )
        for ticker in map(str, weights.index)
    ]
    betas = pd.Series({p.ticker: p.beta for p in positions})
    correlations = returns[weights.index].corr()
    factor_exposure, factor_note = _factor_exposure(portfolio, market)

    return Report(
        as_of=as_of,
        benchmark=benchmark,
        total_value=sum(p.value for p in positions),
        window_start=window_start,
        observations=len(returns),
        positions=positions,
        sectors={str(k): float(v) for k, v in group_weights(weights, market.sectors).items()},
        concentration=concentration(weights),
        volatility=annualized_volatility(portfolio),
        benchmark_volatility=annualized_volatility(benchmark_returns),
        beta=beta(portfolio, benchmark_returns),
        drawdown=max_drawdown(wealth_index(portfolio, window_start)),
        value_at_risk=historical_var(portfolio),
        average_correlation=average_pairwise_correlation(correlations),
        correlated_pairs=highly_correlated_pairs(correlations, CORRELATION_ALERT),
        factor_exposure=factor_exposure,
        factor_note=factor_note,
        stress=[run_scenario(s, prices, weights, benchmark, betas) for s in HISTORICAL_SCENARIOS],
    )


def _require_prices(prices: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in prices.columns or prices[c].isna().all()]
    if missing:
        raise ValueError(f"no prices for: {', '.join(missing)}")


def _short_history_message(prices: pd.DataFrame, columns: list[str], observations: int) -> str:
    first_dates = {c: pd.Timestamp(prices[c].dropna().index[0]) for c in columns}
    youngest = max(first_dates, key=lambda c: first_dates[c])
    return (
        f"only {observations} trading days of common history, need {MIN_OBSERVATIONS}; "
        f"youngest holding is {youngest}, trading since {first_dates[youngest]:%Y-%m-%d}"
    )


def _factor_exposure(
    portfolio: pd.Series, market: MarketData
) -> tuple[FactorExposure | None, str | None]:
    if market.factors is None:
        return None, market.factor_error or "factor data was not loaded"
    try:
        return factor_exposures(portfolio, market.factors), None
    except ValueError as error:
        return None, str(error)


def report_to_dict(report: Report) -> dict[str, Any]:
    var = report.value_at_risk
    exposure = report.factor_exposure
    return {
        "as_of": f"{report.as_of:%Y-%m-%d}",
        "benchmark": report.benchmark,
        "currency": "USD",
        "total_value": report.total_value,
        "window": {"start": f"{report.window_start:%Y-%m-%d}", "observations": report.observations},
        "positions": [vars(p) for p in report.positions],
        "sectors": report.sectors,
        "concentration": vars(report.concentration),
        "risk": {
            "volatility_annual": report.volatility,
            "benchmark_volatility_annual": report.benchmark_volatility,
            "beta": report.beta,
            "max_drawdown": {
                "depth": report.drawdown.depth,
                "peak": f"{report.drawdown.peak:%Y-%m-%d}",
                "trough": f"{report.drawdown.trough:%Y-%m-%d}",
            },
            "value_at_risk_1d": {
                "confidence": var.confidence,
                "var": var.var,
                "cvar": var.cvar,
                "var_amount": var.var * report.total_value,
                "cvar_amount": var.cvar * report.total_value,
            },
        },
        "correlation": {
            "average_pairwise": report.average_correlation,
            "alert_threshold": CORRELATION_ALERT,
            "high_pairs": [list(pair) for pair in report.correlated_pairs],
        },
        "factors": vars(exposure) if exposure else None,
        "factors_note": report.factor_note,
        "stress_tests": [
            {
                "scenario": r.scenario.name,
                "key": r.scenario.key,
                "start": f"{r.scenario.start:%Y-%m-%d}",
                "end": f"{r.scenario.end:%Y-%m-%d}",
                "portfolio_return": r.portfolio_return,
                "portfolio_pnl": r.portfolio_return * report.total_value,
                "benchmark_return": r.benchmark_return,
                "proxied_by_beta": r.proxied,
            }
            for r in report.stress
        ],
    }


def render_text(report: Report) -> str:
    lines = [
        f"ПОРТФЕЛЬ на {report.as_of:%Y-%m-%d} · {_money(report.total_value)} "
        f"· бенчмарк {report.benchmark}",
        f"Окно анализа: {report.window_start:%Y-%m-%d} → {report.as_of:%Y-%m-%d} "
        f"(торговых дней: {report.observations})",
        "",
        "ПОЗИЦИИ",
        f"{'Тикер':<8}{'Доля':>8}{'Вклад в риск':>15}{'Бета':>7}{'Волатильность':>16}",
    ]
    lines += [
        f"{p.ticker:<8}{_pct(p.weight):>8}{_pct(p.risk_share):>15}{p.beta:>7.2f}"
        f"{_pct(p.volatility):>16}"
        for p in report.positions
    ]

    c = report.concentration
    lines += [
        "",
        "КОНЦЕНТРАЦИЯ",
        f"Эффективное число позиций: {c.effective_positions:.1f} из {len(report.positions)}",
        f"Топ-5 позиций: {_pct(c.top5_share)}",
        "Секторы: " + " · ".join(f"{name} {_pct(w)}" for name, w in report.sectors.items()),
    ]

    dd, var = report.drawdown, report.value_at_risk
    lines += [
        "",
        "РИСК",
        f"Волатильность (год): {_pct(report.volatility)} · {report.benchmark}: "
        f"{_pct(report.benchmark_volatility)}",
        f"Бета к {report.benchmark}: {report.beta:.2f}",
        f"Макс. просадка: {_pct(dd.depth)} ({dd.peak:%Y-%m-%d} → {dd.trough:%Y-%m-%d})",
        f"VaR 95% (1 день): {_pct(var.var)} ≈ {_money(var.var * report.total_value)} · "
        f"CVaR: {_pct(var.cvar)} ≈ {_money(var.cvar * report.total_value)}",
    ]

    lines += ["", "КОРРЕЛЯЦИИ"]
    if report.average_correlation is not None:
        lines.append(f"Средняя попарная корреляция: {report.average_correlation:.2f}")
    pairs = ", ".join(f"{a}–{b} {rho:.2f}" for a, b, rho in report.correlated_pairs)
    lines.append(f"Пары с корреляцией ≥ {CORRELATION_ALERT:.2f}: {pairs or 'нет'}")

    lines.append("")
    exposure = report.factor_exposure
    if exposure is None:
        lines.append(f"Факторы недоступны: {report.factor_note}")
    else:
        lines += [
            f"ФАКТОРЫ (Fama–French 5 + Momentum · R² {exposure.r_squared:.2f} · "
            f"дней: {exposure.observations})",
            " · ".join(
                f"{FACTOR_LABELS[name]} {value:+.2f}" for name, value in exposure.loadings.items()
            ),
        ]

    lines += ["", "СТРЕСС-ТЕСТЫ (сегодняшние веса в прошлых кризисах)"]
    for r in report.stress:
        period = f"{r.scenario.start:%Y-%m-%d} → {r.scenario.end:%Y-%m-%d}"
        lines.append(
            f"{r.scenario.name:<27}{period:<26}{_pct(r.portfolio_return):>8}"
            f"{_money(r.portfolio_return * report.total_value):>14}"
            f"   {report.benchmark} {_pct(r.benchmark_return)}"
        )
        if r.proxied:
            lines.append(f"{'':<4}* оценка через бету: {', '.join(r.proxied)}")
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"
