import math

import numpy as np
import pandas as pd
import pytest

from portfolio_risk.risk import (
    aligned_returns,
    annualized_volatility,
    beta,
    historical_var,
    max_drawdown,
    portfolio_returns,
    risk_contributions,
    wealth_index,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", periods=n)


def test_aligned_returns_keep_only_dates_where_every_ticker_has_a_return() -> None:
    prices = pd.DataFrame(
        {"OLD": [100.0, 110.0, 99.0, 99.0], "NEW": [np.nan, np.nan, 50.0, 55.0]},
        index=_dates(4),
    )

    returns = aligned_returns(prices)

    assert list(returns.index) == [_dates(4)[3]]
    assert returns.loc[_dates(4)[3]].to_dict() == pytest.approx({"OLD": 0.0, "NEW": 0.1})


def test_aligned_returns_are_simple_daily_returns() -> None:
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0]}, index=_dates(3))

    assert aligned_returns(prices)["A"].tolist() == pytest.approx([0.10, -0.10])


def test_portfolio_returns_apply_constant_weights() -> None:
    returns = pd.DataFrame({"A": [0.1, 0.0], "B": [-0.1, 0.2]}, index=_dates(2))
    weights = pd.Series({"B": 0.5, "A": 0.5})

    assert portfolio_returns(returns, weights).tolist() == pytest.approx([0.0, 0.1])


def test_annualized_volatility_scales_daily_sample_std_by_sqrt_252() -> None:
    returns = pd.Series([0.01, -0.01, 0.01, -0.01])

    expected = math.sqrt(4 * 0.01**2 / 3) * math.sqrt(252)
    assert annualized_volatility(returns) == pytest.approx(expected)


@pytest.mark.parametrize("multiplier", [2.0, 0.5])
def test_beta_measures_sensitivity_to_benchmark(multiplier: float) -> None:
    benchmark = pd.Series([0.01, -0.02, 0.015, 0.003, -0.007], index=_dates(5))

    assert beta(benchmark * multiplier + 0.001, benchmark) == pytest.approx(multiplier)


def test_beta_uses_only_overlapping_dates() -> None:
    benchmark = pd.Series([0.01, -0.02, 0.015, 0.5], index=_dates(4))
    portfolio = (benchmark * 3).iloc[:3]

    assert beta(portfolio, benchmark) == pytest.approx(3.0)


def test_wealth_index_starts_at_one_on_start_date() -> None:
    returns = pd.Series([0.1, -0.5], index=_dates(3)[1:])

    wealth = wealth_index(returns, start=_dates(3)[0])

    assert wealth.tolist() == pytest.approx([1.0, 1.1, 0.55])
    assert wealth.index[0] == _dates(3)[0]


def test_max_drawdown_finds_deepest_peak_to_trough_decline() -> None:
    wealth = pd.Series([1.0, 1.1, 0.55, 0.66, 0.99, 1.2], index=_dates(6))

    result = max_drawdown(wealth)

    assert result.depth == pytest.approx(-0.5)
    assert result.peak == _dates(6)[1]
    assert result.trough == _dates(6)[2]


def test_max_drawdown_is_zero_for_monotonic_growth() -> None:
    wealth = pd.Series([1.0, 1.1, 1.2], index=_dates(3))

    assert max_drawdown(wealth).depth == 0.0


def test_historical_var_and_cvar_are_positive_losses_from_the_left_tail() -> None:
    returns = pd.Series(np.linspace(-0.10, 0.09, 20))

    result = historical_var(returns, confidence=0.95)

    assert result.var == pytest.approx(0.0905)
    assert result.cvar == pytest.approx(0.10)


def test_risk_contributions_of_uncorrelated_assets_scale_with_weighted_variance() -> None:
    returns = pd.DataFrame(
        {"A": [0.02, -0.02, 0.02, -0.02], "B": [0.01, 0.01, -0.01, -0.01]}, index=_dates(4)
    )
    weights = pd.Series({"A": 0.5, "B": 0.5})

    contributions = risk_contributions(returns, weights)

    assert contributions.to_dict() == pytest.approx({"A": 0.8, "B": 0.2})


def test_risk_contributions_of_identical_assets_equal_their_weights() -> None:
    series = [0.01, -0.03, 0.02, 0.005]
    returns = pd.DataFrame({"A": series, "B": series, "C": series}, index=_dates(4))
    weights = pd.Series({"A": 0.6, "B": 0.3, "C": 0.1})

    contributions = risk_contributions(returns, weights)

    assert contributions.to_dict() == pytest.approx({"A": 0.6, "B": 0.3, "C": 0.1})
    assert list(contributions.index) == ["A", "B", "C"]
