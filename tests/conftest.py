import numpy as np
import pandas as pd
import pytest

from portfolio_risk.factors import FACTOR_COLUMNS
from portfolio_risk.report import MarketData

AS_OF = pd.Timestamp("2026-10-26")


def synthetic_market(young_start: str = "2025-01-02") -> MarketData:
    """Seeded one-factor market since 1999: SPY, two old stocks and one recent IPO (NEW)."""
    dates = pd.bdate_range("1999-01-04", AS_OF)
    rng = np.random.default_rng(seed=1)
    market = rng.normal(0.0003, 0.01, len(dates))

    def walk(beta: float, idiosyncratic: float) -> np.ndarray:
        returns = beta * market + rng.normal(0, idiosyncratic, len(dates))
        return 100 * np.cumprod(1 + returns)

    prices = pd.DataFrame(
        {
            "SPY": walk(1.0, 0.0),
            "AAA": walk(1.3, 0.01),
            "BBB": walk(0.7, 0.008),
            "NEW": walk(1.5, 0.02),
        },
        index=dates,
    )
    prices.loc[: pd.Timestamp(young_start) - pd.Timedelta(days=1), "NEW"] = np.nan

    factors = pd.DataFrame(
        rng.normal(0, 0.005, size=(len(dates), len(FACTOR_COLUMNS))),
        index=dates,
        columns=list(FACTOR_COLUMNS),
    )
    factors["Mkt-RF"] = market
    factors["RF"] = 0.0001

    return MarketData(
        prices=prices,
        sectors={"AAA": "Technology", "BBB": "Energy"},
        factors=factors,
    )


@pytest.fixture
def market() -> MarketData:
    return synthetic_market()
