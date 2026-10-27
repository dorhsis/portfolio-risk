import pandas as pd
import pytest

from portfolio_risk.correlation import average_pairwise_correlation, highly_correlated_pairs


def _corr() -> pd.DataFrame:
    tickers = ["A", "B", "C"]
    return pd.DataFrame(
        [[1.0, 0.9, 0.1], [0.9, 1.0, 0.85], [0.1, 0.85, 1.0]], index=tickers, columns=tickers
    )


def test_average_pairwise_correlation_ignores_the_diagonal() -> None:
    assert average_pairwise_correlation(_corr()) == pytest.approx((0.9 + 0.1 + 0.85) / 3)


def test_average_pairwise_correlation_of_single_asset_is_undefined() -> None:
    single = pd.DataFrame([[1.0]], index=["A"], columns=["A"])

    assert average_pairwise_correlation(single) is None


def test_highly_correlated_pairs_lists_each_pair_once_strongest_first() -> None:
    pairs = highly_correlated_pairs(_corr(), threshold=0.8)

    assert pairs == [("A", "B", pytest.approx(0.9)), ("B", "C", pytest.approx(0.85))]


def test_highly_correlated_pairs_is_empty_below_threshold() -> None:
    assert highly_correlated_pairs(_corr(), threshold=0.95) == []
