"""Fama-French five-factor + momentum regression of portfolio excess returns."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_risk.risk import TRADING_DAYS

FACTOR_COLUMNS = ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom")
MIN_OBSERVATIONS = 60


@dataclass(frozen=True)
class FactorExposure:
    loadings: dict[str, float]
    alpha_annual: float
    r_squared: float
    observations: int


def factor_exposures(returns: pd.Series, factors: pd.DataFrame) -> FactorExposure:
    """OLS of (returns - RF) on FACTOR_COLUMNS; `factors` holds decimal daily values and RF."""
    joined = pd.concat([returns.rename("portfolio"), factors], axis=1, join="inner").dropna()
    if len(joined) < MIN_OBSERVATIONS:
        raise ValueError(
            f"need at least {MIN_OBSERVATIONS} overlapping days of returns and factor data, "
            f"got {len(joined)}"
        )

    excess = (joined["portfolio"] - joined["RF"]).to_numpy()
    design = np.column_stack([np.ones(len(joined)), joined[list(FACTOR_COLUMNS)].to_numpy()])
    coefficients, *_ = np.linalg.lstsq(design, excess, rcond=None)

    residuals = excess - design @ coefficients
    total = excess - excess.mean()
    return FactorExposure(
        loadings={name: float(c) for name, c in zip(FACTOR_COLUMNS, coefficients[1:], strict=True)},
        alpha_annual=float(coefficients[0] * TRADING_DAYS),
        r_squared=float(1 - residuals @ residuals / (total @ total)),
        observations=len(joined),
    )
