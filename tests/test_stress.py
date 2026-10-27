import numpy as np
import pandas as pd
import pytest

from portfolio_risk.stress import HISTORICAL_SCENARIOS, Scenario, run_scenario

SCENARIO = Scenario("Test crash", pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-05"))
DATES = pd.bdate_range("2024-01-01", "2024-01-08")  # Mon 1st .. Mon 8th


def _prices(**columns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=DATES)


def test_uses_actual_prices_when_every_holding_traded_through_the_scenario() -> None:
    prices = _prices(
        A=[100, 100, 100, 80, 50, 50],
        B=[10, 10, 10, 11, 12, 12],
        SPY=[200, 200, 200, 180, 150, 150],
    )
    weights = pd.Series({"A": 0.6, "B": 0.4})

    result = run_scenario(SCENARIO, prices, weights, benchmark="SPY", betas=pd.Series(dtype=float))

    assert result.portfolio_return == pytest.approx(0.6 * -0.5 + 0.4 * 0.2)
    assert result.benchmark_return == pytest.approx(-0.25)
    assert result.proxied == []


def test_holdings_without_history_are_proxied_by_beta_times_benchmark() -> None:
    nan = np.nan
    prices = _prices(
        A=[100, 100, 100, 80, 50, 50],
        B=[nan, nan, nan, nan, 12, 12],
        SPY=[200, 200, 200, 180, 150, 150],
    )
    weights = pd.Series({"A": 0.6, "B": 0.4})

    result = run_scenario(SCENARIO, prices, weights, benchmark="SPY", betas=pd.Series({"B": 1.5}))

    assert result.portfolio_return == pytest.approx(0.6 * -0.5 + 0.4 * 1.5 * -0.25)
    assert result.proxied == ["B"]


def test_scenario_dates_on_non_trading_days_use_the_last_prior_close() -> None:
    weekend = Scenario("Weekend", pd.Timestamp("2024-01-06"), pd.Timestamp("2024-01-07"))
    prices = _prices(A=[100, 100, 100, 100, 90, 70], SPY=[1, 1, 1, 1, 1, 1])

    result = run_scenario(weekend, prices, pd.Series({"A": 1.0}), "SPY", pd.Series(dtype=float))

    assert result.portfolio_return == pytest.approx(0.0)


def test_benchmark_without_history_cannot_run_the_scenario() -> None:
    nan = np.nan
    prices = _prices(A=[1, 1, 1, 1, 1, 1], SPY=[nan, nan, nan, nan, 1, 1])

    with pytest.raises(ValueError, match="SPY"):
        run_scenario(SCENARIO, prices, pd.Series({"A": 1.0}), "SPY", pd.Series(dtype=float))


def test_historical_scenarios_are_chronological_and_well_formed() -> None:
    starts = [s.start for s in HISTORICAL_SCENARIOS]

    assert starts == sorted(starts)
    assert all(s.start < s.end for s in HISTORICAL_SCENARIOS)
