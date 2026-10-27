"""How concentrated the portfolio is: position weights, HHI, effective number of positions."""

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from portfolio_risk.portfolio import Holding

UNKNOWN_GROUP = "Unknown"


@dataclass(frozen=True)
class Concentration:
    hhi: float
    effective_positions: float
    top5_share: float


def position_weights(holdings: list[Holding], last_prices: pd.Series) -> pd.Series:
    missing = [h.ticker for h in holdings if h.ticker not in last_prices.index]
    if missing:
        raise ValueError(f"no price for: {', '.join(missing)}")
    values = pd.Series({h.ticker: h.shares * float(last_prices[h.ticker]) for h in holdings})
    return (values / values.sum()).sort_values(ascending=False)


def concentration(weights: pd.Series) -> Concentration:
    hhi = float((weights**2).sum())
    return Concentration(
        hhi=hhi,
        effective_positions=1 / hhi,
        top5_share=float(weights.nlargest(5).sum()),
    )


def group_weights(weights: pd.Series, groups: Mapping[str, str]) -> pd.Series:
    labels = [groups.get(str(ticker), UNKNOWN_GROUP) for ticker in weights.index]
    return weights.groupby(labels).sum().sort_values(ascending=False)
