"""Historical stress tests: replay a past market crash on today's weights.

Holdings that did not trade through the whole scenario (later IPOs) are proxied by
beta * benchmark return, and reported as proxied so the reader knows the number is an estimate.
A long position can lose at most its whole value, so the proxy is floored at -100%: with beta 2
and a 60% market drop the linear estimate alone would be -120%.
"""

from dataclasses import dataclass

import pandas as pd

TOTAL_LOSS = -1.0


@dataclass(frozen=True)
class Scenario:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    portfolio_return: float
    benchmark_return: float
    proxied: list[str]


# S&P 500 peak-to-trough windows.
HISTORICAL_SCENARIOS = (
    Scenario("Крах доткомов", pd.Timestamp("2000-03-24"), pd.Timestamp("2002-10-09")),
    Scenario("Мировой финансовый кризис", pd.Timestamp("2007-10-09"), pd.Timestamp("2009-03-09")),
    Scenario("COVID-обвал", pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
    Scenario("Рост ставок 2022", pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-12")),
)


def run_scenario(
    scenario: Scenario,
    prices: pd.DataFrame,
    weights: pd.Series,
    benchmark: str,
    betas: pd.Series,
) -> ScenarioResult:
    benchmark_return = _window_return(prices[benchmark], scenario)
    if benchmark_return is None:
        raise ValueError(f"benchmark {benchmark} has no prices covering {scenario.name}")

    total = 0.0
    proxied: list[str] = []
    for ticker in map(str, weights.index):
        asset_return = _window_return(prices[ticker], scenario) if ticker in prices else None
        if asset_return is None:
            asset_return = max(float(betas[ticker]) * benchmark_return, TOTAL_LOSS)
            proxied.append(ticker)
        total += float(weights[ticker]) * asset_return

    return ScenarioResult(scenario, total, benchmark_return, proxied)


def _window_return(series: pd.Series, scenario: Scenario) -> float | None:
    history = series.dropna()
    if history.empty or history.index[0] > scenario.start:
        return None
    start_price = float(history.loc[: scenario.start].iloc[-1])
    end_price = float(history.loc[: scenario.end].iloc[-1])
    return end_price / start_price - 1
