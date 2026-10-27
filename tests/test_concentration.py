import pandas as pd
import pytest

from portfolio_risk.concentration import concentration, group_weights, position_weights
from portfolio_risk.portfolio import Holding


def test_position_weights_use_market_value_and_sort_descending() -> None:
    holdings = [Holding("AAPL", 10), Holding("MSFT", 15)]
    last_prices = pd.Series({"AAPL": 100.0, "MSFT": 200.0})

    weights = position_weights(holdings, last_prices)

    assert list(weights.index) == ["MSFT", "AAPL"]
    assert weights["MSFT"] == pytest.approx(0.75)
    assert weights["AAPL"] == pytest.approx(0.25)


def test_position_weights_require_a_price_for_every_holding() -> None:
    with pytest.raises(ValueError, match="TSLA"):
        position_weights([Holding("TSLA", 1)], pd.Series({"AAPL": 1.0}))


def test_equal_weights_have_effective_count_equal_to_position_count() -> None:
    weights = pd.Series({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})

    result = concentration(weights)

    assert result.hhi == pytest.approx(0.25)
    assert result.effective_positions == pytest.approx(4.0)
    assert result.top5_share == pytest.approx(1.0)


def test_concentrated_portfolio_has_fewer_effective_positions_than_holdings() -> None:
    weights = pd.Series({"A": 0.5, "B": 0.2, "C": 0.1, "D": 0.1, "E": 0.05, "F": 0.05})

    result = concentration(weights)

    assert result.hhi == pytest.approx(0.315)
    assert result.effective_positions == pytest.approx(1 / 0.315)
    assert result.top5_share == pytest.approx(0.95)


def test_group_weights_sum_by_group_and_label_unmapped_tickers() -> None:
    weights = pd.Series({"AAPL": 0.4, "MSFT": 0.3, "XOM": 0.2, "ZZZ": 0.1})
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}

    result = group_weights(weights, sectors)

    assert result.to_dict() == pytest.approx({"Technology": 0.7, "Energy": 0.2, "Unknown": 0.1})
    assert list(result.index) == ["Technology", "Energy", "Unknown"]
