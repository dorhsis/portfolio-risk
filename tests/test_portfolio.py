from pathlib import Path

import pytest

from portfolio_risk.portfolio import Holding, PortfolioError, load_portfolio, parse_portfolio


def test_parses_holdings_and_normalizes_tickers() -> None:
    holdings = parse_portfolio("ticker,shares\n aapl ,10\nMSFT,2.5\n")

    assert holdings == [Holding("AAPL", 10.0), Holding("MSFT", 2.5)]


def test_header_is_case_insensitive_and_extra_columns_are_ignored() -> None:
    holdings = parse_portfolio("Ticker,Shares,Note\nNVDA,3,core\n")

    assert holdings == [Holding("NVDA", 3.0)]


def test_header_is_optional() -> None:
    holdings = parse_portfolio("KSPI , 10\naapl,2.5\n")

    assert holdings == [Holding("KSPI", 10.0), Holding("AAPL", 2.5)]


@pytest.mark.parametrize(
    "text",
    [
        "AAPL 40\nMSFT   2\n",
        "AAPL\t40\nMSFT\t2\n",
        "AAPL;40\nMSFT;2\n",
        "ticker;shares\nAAPL;40\nMSFT;2\n",
        '"AAPL","40"\n"MSFT","2"\n',
    ],
    ids=["spaces", "tabs", "semicolons", "semicolon-header", "quoted"],
)
def test_common_separators_are_accepted(text: str) -> None:
    assert parse_portfolio(text) == [Holding("AAPL", 40.0), Holding("MSFT", 2.0)]


def test_byte_order_mark_from_spreadsheet_export_is_ignored() -> None:
    assert parse_portfolio("﻿ticker,shares\nAAPL,1\n") == [Holding("AAPL", 1.0)]


@pytest.mark.parametrize("line", ["AAPL", "BRK B 15"])
def test_line_without_exactly_ticker_and_shares_is_rejected(line: str) -> None:
    with pytest.raises(PortfolioError, match=f"line 2: expected a ticker and shares, got '{line}'"):
        parse_portfolio(f"MSFT 1\n{line}\n")


def test_duplicate_tickers_are_merged() -> None:
    holdings = parse_portfolio("ticker,shares\nAAPL,10\nMSFT,1\naapl,5\n")

    assert holdings == [Holding("AAPL", 15.0), Holding("MSFT", 1.0)]


def test_blank_lines_are_skipped() -> None:
    holdings = parse_portfolio("ticker,shares\n\nAAPL,1\n,\n")

    assert holdings == [Holding("AAPL", 1.0)]


def test_missing_column_is_rejected() -> None:
    with pytest.raises(PortfolioError, match="shares"):
        parse_portfolio("ticker,qty\nAAPL,1\n")


def test_non_numeric_shares_report_line_number() -> None:
    with pytest.raises(PortfolioError, match="line 3"):
        parse_portfolio("ticker,shares\nAAPL,1\nMSFT,ten\n")


@pytest.mark.parametrize("shares", ["0", "-4"])
def test_non_positive_shares_are_rejected(shares: str) -> None:
    with pytest.raises(PortfolioError, match="positive"):
        parse_portfolio(f"ticker,shares\nAAPL,{shares}\n")


@pytest.mark.parametrize("shares", ["nan", "inf"])
def test_non_finite_shares_are_rejected(shares: str) -> None:
    with pytest.raises(PortfolioError, match="finite"):
        parse_portfolio(f"ticker,shares\nAAPL,{shares}\n")


def test_missing_ticker_is_rejected() -> None:
    with pytest.raises(PortfolioError, match="line 2: ticker is empty"):
        parse_portfolio("ticker,shares\n,5\n")


def test_empty_portfolio_is_rejected() -> None:
    with pytest.raises(PortfolioError, match="no holdings"):
        parse_portfolio("ticker,shares\n")


def test_load_portfolio_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.csv"
    path.write_text("ticker,shares\nSPY,4\n")

    assert load_portfolio(path) == [Holding("SPY", 4.0)]
