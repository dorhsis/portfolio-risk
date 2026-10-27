"""Return-based risk metrics.

Portfolio returns assume the current weights are held constant over the whole window,
which answers "how risky is the portfolio I hold today", not "how did my past trades do".
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class Drawdown:
    depth: float
    peak: pd.Timestamp
    trough: pd.Timestamp


@dataclass(frozen=True)
class ValueAtRisk:
    confidence: float
    var: float
    cvar: float


def aligned_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns on the dates where every ticker has one."""
    return prices.pct_change(fill_method=None).iloc[1:].dropna(how="any")


def portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    combined: pd.Series = returns[weights.index].dot(weights)
    return combined


def annualized_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(TRADING_DAYS))


def beta(portfolio: pd.Series, benchmark: pd.Series) -> float:
    joined = pd.concat([portfolio, benchmark], axis=1, join="inner").dropna()
    covariance = joined.cov().to_numpy()
    return float(covariance[0, 1] / covariance[1, 1])


def wealth_index(returns: pd.Series, start: pd.Timestamp) -> pd.Series:
    growth = (1 + returns).cumprod()
    wealth: pd.Series = pd.concat([pd.Series([1.0], index=pd.DatetimeIndex([start])), growth])
    return wealth


def max_drawdown(wealth: pd.Series) -> Drawdown:
    drawdowns = (wealth / wealth.cummax() - 1).to_numpy()
    trough_at = int(drawdowns.argmin())
    peak_at = int(wealth.to_numpy()[: trough_at + 1].argmax())
    return Drawdown(
        depth=float(drawdowns[trough_at]),
        peak=pd.Timestamp(wealth.index[peak_at]),
        trough=pd.Timestamp(wealth.index[trough_at]),
    )


def historical_var(returns: pd.Series, confidence: float = 0.95) -> ValueAtRisk:
    """One-day VaR and CVaR as positive fractions of portfolio value."""
    cutoff = float(returns.quantile(1 - confidence))
    tail = returns[returns <= cutoff]
    return ValueAtRisk(confidence=confidence, var=-cutoff, cvar=-float(tail.mean()))


def risk_contributions(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Share of total portfolio variance coming from each position; sums to 1."""
    covariance = returns[weights.index].cov().to_numpy()
    w = weights.to_numpy()
    marginal = covariance @ w
    return pd.Series(w * marginal / (w @ marginal), index=weights.index)
