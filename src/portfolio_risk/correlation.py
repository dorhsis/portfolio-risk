"""Summaries of a correlation matrix: how much the holdings move together."""

import numpy as np
import pandas as pd


def average_pairwise_correlation(corr: pd.DataFrame) -> float | None:
    size = len(corr)
    if size < 2:
        return None
    upper = corr.to_numpy()[np.triu_indices(size, k=1)]
    return float(upper.mean())


def highly_correlated_pairs(
    corr: pd.DataFrame, threshold: float = 0.8
) -> list[tuple[str, str, float]]:
    tickers = [str(t) for t in corr.index]
    values = corr.to_numpy()
    pairs = [
        (tickers[i], tickers[j], float(values[i, j]))
        for i in range(len(tickers))
        for j in range(i + 1, len(tickers))
        if values[i, j] >= threshold
    ]
    return sorted(pairs, key=lambda pair: pair[2], reverse=True)
