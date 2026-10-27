import numpy as np
import pandas as pd
import pytest

from portfolio_risk.factors import FACTOR_COLUMNS, factor_exposures


def _factors(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed=7)
    data = rng.normal(0, 0.01, size=(n, len(FACTOR_COLUMNS)))
    factors = pd.DataFrame(
        data, columns=list(FACTOR_COLUMNS), index=pd.bdate_range("2023-01-02", periods=n)
    )
    factors["RF"] = 0.0002
    return factors


def test_recovers_exact_loadings_from_noise_free_returns() -> None:
    factors = _factors()
    loadings = {"Mkt-RF": 1.2, "SMB": 0.3, "HML": -0.2, "RMW": 0.0, "CMA": 0.1, "Mom": 0.4}
    excess = sum(factors[name] * value for name, value in loadings.items())
    returns = excess + factors["RF"] + 0.0001

    result = factor_exposures(returns, factors)

    assert result.loadings == pytest.approx(loadings, abs=1e-9)
    assert result.r_squared == pytest.approx(1.0)
    assert result.alpha_annual == pytest.approx(0.0001 * 252)
    assert result.observations == 300


def test_uses_only_dates_present_in_both_series() -> None:
    factors = _factors()
    returns = (factors["Mkt-RF"] + factors["RF"]).iloc[50:]

    result = factor_exposures(returns, factors)

    assert result.observations == 250
    assert result.loadings["Mkt-RF"] == pytest.approx(1.0)


def test_r_squared_is_low_for_returns_unrelated_to_factors() -> None:
    factors = _factors()
    noise = pd.Series(
        np.random.default_rng(seed=99).normal(0, 0.01, len(factors)), index=factors.index
    )

    assert factor_exposures(noise, factors).r_squared < 0.1


def test_rejects_too_short_overlap() -> None:
    factors = _factors(n=20)

    with pytest.raises(ValueError, match="overlapping"):
        factor_exposures(factors["Mkt-RF"], factors)
