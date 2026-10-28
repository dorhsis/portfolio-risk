import numpy as np
import pandas as pd
import pytest

from portfolio_risk.market_data import (
    MarketDataError,
    TickerMatch,
    close_prices,
    parse_french_csv,
    search_query,
    search_tickers,
    sector_label,
    ticker_matches,
    to_yahoo_symbol,
)

FRENCH_CSV = (
    "This file was created by using the 202608 CRSP database.\r\n"
    "The Tbill return is the simple daily rate.\r\n"
    "\r\n"
    ",Mkt-RF,SMB,RF\r\n"
    "20260828,   -0.34,   -0.37,    0.01\r\n"
    "20260831,    1.50,   -0.29,    0.02\r\n"
    "\r\n"
    "Copyright 2026 Eugene F. Fama and Kenneth R. French\r\n"
)


def test_parse_french_csv_reads_daily_rows_as_decimals() -> None:
    factors = parse_french_csv(FRENCH_CSV)

    assert list(factors.columns) == ["Mkt-RF", "SMB", "RF"]
    assert list(factors.index) == [pd.Timestamp("2026-08-28"), pd.Timestamp("2026-08-31")]
    assert factors.loc[pd.Timestamp("2026-08-31")].to_dict() == pytest.approx(
        {"Mkt-RF": 0.015, "SMB": -0.0029, "RF": 0.0002}
    )


def test_parse_french_csv_rejects_text_without_a_header_row() -> None:
    with pytest.raises(MarketDataError, match="header"):
        parse_french_csv("not a factor file\r\n")


def test_yahoo_symbol_uses_dash_for_share_classes() -> None:
    assert to_yahoo_symbol("BRK.B") == "BRK-B"
    assert to_yahoo_symbol("AAPL") == "AAPL"


def test_sector_label_prefers_stock_sector() -> None:
    assert sector_label({"quoteType": "EQUITY", "sector": "Technology"}) == "Technology"


def test_sector_label_describes_etfs_by_category() -> None:
    assert sector_label({"quoteType": "ETF", "category": "Large Blend"}) == "ETF: Large Blend"
    assert sector_label({"quoteType": "ETF"}) == "ETF"


def test_sector_label_is_none_when_unknown() -> None:
    assert sector_label({}) is None


def _download(columns: dict[tuple[str, str], list[float]]) -> pd.DataFrame:
    frame = pd.DataFrame(columns, index=pd.bdate_range("2026-10-01", periods=2))
    frame.columns = pd.MultiIndex.from_tuples(list(columns), names=["Price", "Ticker"])
    return frame


def test_close_prices_map_yahoo_symbols_back_to_portfolio_tickers() -> None:
    raw = _download(
        {
            ("Close", "BRK-B"): [500.0, 510.0],
            ("Close", "SPY"): [700.0, 705.0],
            ("High", "SPY"): [701.0, 706.0],
        }
    )

    prices = close_prices(raw, ["BRK.B", "SPY"])

    assert list(prices.columns) == ["BRK.B", "SPY"]
    assert prices["BRK.B"].tolist() == [500.0, 510.0]


def test_close_prices_name_every_ticker_without_data() -> None:
    raw = _download({("Close", "AAPL"): [1.0, 2.0], ("Close", "NOPE"): [np.nan, np.nan]})

    with pytest.raises(MarketDataError, match="NOPE, GONE"):
        close_prices(raw, ["AAPL", "NOPE", "GONE"])


def _stub_network(monkeypatch: pytest.MonkeyPatch, factors_error: Exception | None) -> None:
    import portfolio_risk.market_data as md

    prices = pd.DataFrame(
        {"AAPL": [1.0], "SPY": [2.0]}, index=pd.bdate_range("2026-10-01", periods=1)
    )
    monkeypatch.setattr(md, "fetch_prices", lambda tickers, start: prices)
    monkeypatch.setattr(md, "fetch_sectors", lambda tickers: {"AAPL": "Technology"})

    def fetch_factors() -> pd.DataFrame:
        if factors_error:
            raise factors_error
        return pd.DataFrame({"RF": [0.0]})

    monkeypatch.setattr(md, "fetch_fama_french", fetch_factors)


def test_load_market_data_skips_factors_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from portfolio_risk.market_data import load_market_data

    _stub_network(monkeypatch, factors_error=None)

    market = load_market_data(["AAPL"], "SPY", include_factors=False)

    assert market.factors is None
    assert market.factor_error is not None and "--no-factors" in market.factor_error


def test_load_market_data_survives_factor_download_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    from portfolio_risk.market_data import load_market_data

    _stub_network(monkeypatch, factors_error=requests.ConnectionError("dartmouth down"))

    market = load_market_data(["AAPL"], "SPY", include_factors=True)

    assert market.factors is None
    assert market.factor_error is not None and "dartmouth down" in market.factor_error
    assert market.sectors == {"AAPL": "Technology"}


def test_ticker_matches_keep_us_stocks_and_etfs_under_portfolio_symbols() -> None:
    quotes = [
        {
            "symbol": "AAPL",
            "longname": "Apple Inc.",
            "quoteType": "EQUITY",
            "exchange": "NMS",
            "exchDisp": "NASDAQ",
        },
        {
            "symbol": "SAAPL=F",
            "shortname": "Apple Futures",
            "quoteType": "FUTURE",
            "exchange": "CME",
            "exchDisp": "Chicago Mercantile Exchange",
        },
        {
            "symbol": "AAPL.TO",
            "longname": "Apple Inc.",
            "quoteType": "EQUITY",
            "exchange": "TOR",
            "exchDisp": "Toronto",
        },
        {
            "symbol": "BRK-B",
            "shortname": "Berkshire Hathaway Inc.",
            "longname": None,
            "quoteType": "EQUITY",
            "exchange": "NYQ",
            "exchDisp": "NYSE",
        },
        {
            "symbol": "VXUS",
            "longname": "Vanguard Total International Stock ETF",
            "quoteType": "ETF",
            "exchange": "NGM",
            "exchDisp": "NASDAQ",
        },
        {
            "symbol": "VTSAX",
            "longname": "Vanguard Total Stock Mkt Idx Adm",
            "quoteType": "MUTUALFUND",
            "exchange": "NAS",
            "exchDisp": "Nasdaq",
        },
        {
            "symbol": "AAPL",
            "longname": "Apple Inc.",
            "quoteType": "EQUITY",
            "exchange": "NMS",
            "exchDisp": "NASDAQ",
        },
    ]

    assert ticker_matches(quotes) == [
        TickerMatch("AAPL", "Apple Inc.", "NASDAQ", "stock"),
        TickerMatch("BRK.B", "Berkshire Hathaway Inc.", "NYSE", "stock"),
        TickerMatch("VXUS", "Vanguard Total International Stock ETF", "NASDAQ", "etf"),
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("BRK.B", "BRK-B"),
        ("bf.b", "bf-b"),
        ("apple", "apple"),
        ("amazon.com", "amazon.com"),
        ("kaspi.kz", "kaspi.kz"),
    ],
)
def test_search_query_spells_share_classes_the_yahoo_way(query: str, expected: str) -> None:
    assert search_query(query) == expected


def test_search_tickers_turns_any_yahoo_failure_into_market_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portfolio_risk.market_data as md

    def failing_search(query: str, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(md.yf, "Search", failing_search)

    with pytest.raises(MarketDataError, match="timed out"):
        search_tickers("apple")


def test_search_tickers_reports_an_answer_without_quotes_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portfolio_risk.market_data as md

    class ThrottledSearch:
        def __init__(self, query: str, **kwargs: object) -> None:
            self.response = {"finance": {"error": {"code": "Too Many Requests"}}}
            self.quotes: list[dict[str, object]] = []

    monkeypatch.setattr(md.yf, "Search", ThrottledSearch)

    with pytest.raises(MarketDataError, match="no quote list"):
        search_tickers("apple")
