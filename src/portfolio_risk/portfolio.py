"""Portfolio input: a CSV with `ticker` and `shares` columns, long positions only."""

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path


class PortfolioError(ValueError):
    """The portfolio file is malformed or empty."""


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: float


def load_portfolio(path: Path) -> list[Holding]:
    return parse_portfolio(path.read_text())


def parse_portfolio(text: str) -> list[Holding]:
    reader = csv.DictReader(io.StringIO(text))
    columns = {name.strip().lower(): name for name in reader.fieldnames or []}
    for required in ("ticker", "shares"):
        if required not in columns:
            raise PortfolioError(f"portfolio CSV must have a '{required}' column")

    shares_by_ticker: dict[str, float] = {}
    for row in reader:
        ticker = (row[columns["ticker"]] or "").strip().upper()
        raw_shares = (row[columns["shares"]] or "").strip()
        if not ticker and not raw_shares:
            continue
        if not ticker:
            raise PortfolioError(f"line {reader.line_num}: ticker is empty")
        shares = _parse_shares(raw_shares, line=reader.line_num)
        shares_by_ticker[ticker] = shares_by_ticker.get(ticker, 0.0) + shares

    if not shares_by_ticker:
        raise PortfolioError("portfolio has no holdings")
    return [Holding(ticker, shares) for ticker, shares in shares_by_ticker.items()]


def _parse_shares(raw: str, line: int) -> float:
    try:
        shares = float(raw)
    except ValueError:
        raise PortfolioError(f"line {line}: shares must be a number, got '{raw}'") from None
    if not math.isfinite(shares):
        raise PortfolioError(f"line {line}: shares must be finite, got {raw}")
    if shares <= 0:
        raise PortfolioError(f"line {line}: shares must be positive, got {raw}")
    return shares
