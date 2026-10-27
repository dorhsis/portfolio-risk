"""Portfolio input: one holding per line, a ticker and a number of shares, long positions only.

The `ticker,shares` header is optional; with it, column order is free and extra columns are
ignored. Values may be separated by commas, semicolons, tabs or spaces, so a CSV export, a paste
from a spreadsheet and a hand-typed `AAPL 40` all work.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

HEADER_NAMES = ("ticker", "shares")
# Semicolons and tabs win over commas: spreadsheets in many locales export with them.
DELIMITERS = (";", "\t", ",")


class PortfolioError(ValueError):
    """The portfolio file is malformed or empty."""


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: float


class _Line(NamedTuple):
    number: int
    text: str
    cells: list[str]


class _Entry(NamedTuple):
    line: int
    ticker: str
    shares: str


def load_portfolio(path: Path) -> list[Holding]:
    return parse_portfolio(path.read_text())


def parse_portfolio(text: str) -> list[Holding]:
    # Spreadsheet apps prepend a byte order mark to UTF-8 CSV exports.
    text = text.removeprefix("﻿")
    lines = [
        _Line(number, line.strip(), cells)
        for number, line in enumerate(text.splitlines(), start=1)
        if any(cells := _split(line))
    ]
    if lines and _is_header(lines[0].cells):
        entries = _entries_under_header(lines[0].cells, lines[1:])
    else:
        entries = [_entry_without_header(line) for line in lines]

    shares_by_ticker: dict[str, float] = {}
    for entry in entries:
        if not entry.ticker and not entry.shares:
            continue
        if not entry.ticker:
            raise PortfolioError(f"line {entry.line}: ticker is empty")
        # Caught here, a typo costs an instant error instead of a slow market-data miss.
        if any(char.isspace() for char in entry.ticker):
            raise PortfolioError(
                f"line {entry.line}: ticker must not contain spaces, got '{entry.ticker}'"
            )
        ticker = entry.ticker.upper()
        shares = _parse_shares(entry.shares, line=entry.line)
        shares_by_ticker[ticker] = shares_by_ticker.get(ticker, 0.0) + shares

    if not shares_by_ticker:
        raise PortfolioError("portfolio has no holdings")
    return [Holding(ticker, shares) for ticker, shares in shares_by_ticker.items()]


def _split(line: str) -> list[str]:
    for delimiter in DELIMITERS:
        if delimiter in line:
            return [cell.strip() for cell in next(csv.reader([line], delimiter=delimiter))]
    return line.split()


def _is_header(cells: list[str]) -> bool:
    return any(cell.lower() in HEADER_NAMES for cell in cells)


def _entries_under_header(header: list[str], lines: list[_Line]) -> list[_Entry]:
    columns = [cell.lower() for cell in header]
    for required in HEADER_NAMES:
        if required not in columns:
            raise PortfolioError(f"portfolio CSV must have a '{required}' column")
    ticker_at, shares_at = columns.index("ticker"), columns.index("shares")
    return [
        _Entry(line.number, _cell(line.cells, ticker_at), _cell(line.cells, shares_at))
        for line in lines
    ]


def _entry_without_header(line: _Line) -> _Entry:
    if len(line.cells) != 2:
        raise PortfolioError(f"line {line.number}: expected a ticker and shares, got '{line.text}'")
    ticker, shares = line.cells
    return _Entry(line.number, ticker, shares)


def _cell(cells: list[str], index: int) -> str:
    return cells[index] if index < len(cells) else ""


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
