"""Market data adapters: Yahoo Finance prices and sectors, Ken French factor library.

Yahoo Finance (via yfinance) is free and fine for a prototype, but its terms forbid commercial
use: swap `fetch_prices` / `fetch_sectors` for a licensed provider before shipping a product.
"""

import io
import logging
import re
import warnings
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Literal, NamedTuple

import pandas as pd
import requests
import yfinance as yf

from portfolio_risk.factors import FACTOR_COLUMNS
from portfolio_risk.report import MarketData

# Early enough to cover every historical stress scenario.
HISTORY_START = pd.Timestamp("1999-12-01")
_FRENCH_FTP = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FIVE_FACTORS_URL = f"{_FRENCH_FTP}/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOMENTUM_URL = f"{_FRENCH_FTP}/F-F_Momentum_Factor_daily_CSV.zip"
_DATE_ROW = re.compile(r"^\d{8},")

# (tickers, benchmark, include_factors) -> MarketData; injected so callers can be tested offline.
Loader = Callable[[list[str], str, bool], MarketData]

# Yahoo exchange codes of US venues: Nasdaq tiers, NYSE, NYSE American, NYSE Arca, Cboe BZX.
US_EXCHANGES = frozenset({"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"})
QUOTE_KINDS: dict[str, Literal["stock", "etf"]] = {"EQUITY": "stock", "ETF": "etf"}
_SHARE_CLASS = re.compile(r"[A-Za-z]{1,5}\.[A-Za-z]")


class TickerMatch(NamedTuple):
    symbol: str
    name: str
    exchange: str
    kind: Literal["stock", "etf"]


# query -> matches; injected so the web API can be tested offline.
Searcher = Callable[[str], list[TickerMatch]]


class MarketDataError(RuntimeError):
    """A data source returned nothing usable."""


def load_market_data(tickers: list[str], benchmark: str, include_factors: bool) -> MarketData:
    """Everything a report needs; factor data is optional and its absence is explained."""
    prices = fetch_prices(list(dict.fromkeys([*tickers, benchmark])), start=HISTORY_START)
    sectors = fetch_sectors(tickers)
    if not include_factors:
        return MarketData(prices, sectors, factors=None, factor_error="disabled with --no-factors")
    try:
        factors = fetch_fama_french()
    except (MarketDataError, requests.RequestException, zipfile.BadZipFile) as error:
        return MarketData(
            prices, sectors, factors=None, factor_error=f"Ken French download failed: {error}"
        )
    return MarketData(prices, sectors, factors)


def to_yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def from_yahoo_symbol(symbol: str) -> str:
    return symbol.replace("-", ".")


def fetch_prices(tickers: Sequence[str], start: pd.Timestamp) -> pd.DataFrame:
    """Split- and dividend-adjusted daily closes, one column per ticker."""
    symbols = [to_yahoo_symbol(t) for t in tickers]
    with _quiet_yfinance():
        raw = yf.download(symbols, start=start, auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        raise MarketDataError("Yahoo Finance returned no price data")
    return close_prices(raw, tickers)


def close_prices(raw: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    closes = pd.DataFrame(raw["Close"])
    ticker_by_symbol = {to_yahoo_symbol(t): t for t in tickers}
    missing = [
        ticker
        for symbol, ticker in ticker_by_symbol.items()
        if symbol not in closes.columns or closes[symbol].isna().all()
    ]
    if missing:
        raise MarketDataError(f"no price data for: {', '.join(missing)}")
    prices = closes[list(ticker_by_symbol)].rename(columns=ticker_by_symbol)
    prices.columns.name = None
    return prices


def search_tickers(query: str) -> list[TickerMatch]:
    """US stocks and ETFs whose ticker or name matches the query, best match first."""
    try:
        with _quiet_yfinance():
            search = yf.Search(search_query(query), max_results=10, news_count=0, timeout=8)
    except Exception as error:  # yfinance raises transport and parsing errors of many types
        raise MarketDataError(f"Yahoo search failed: {error}") from None
    # A throttled or failed answer still parses, so tell it from "nothing matched" here.
    if "quotes" not in search.response:
        raise MarketDataError("Yahoo search answered with no quote list")
    return ticker_matches(search.quotes)


def search_query(query: str) -> str:
    """Share classes are BRK.B in a portfolio but BRK-B on Yahoo, which finds only the latter."""
    return to_yahoo_symbol(query) if _SHARE_CLASS.fullmatch(query) else query


def ticker_matches(quotes: Sequence[Mapping[str, Any]]) -> list[TickerMatch]:
    matches: dict[str, TickerMatch] = {}
    for quote in quotes:
        kind = QUOTE_KINDS.get(str(quote.get("quoteType")))
        if kind is None or quote.get("exchange") not in US_EXCHANGES:
            continue
        symbol = from_yahoo_symbol(str(quote["symbol"]))
        name = quote.get("longname") or quote.get("shortname") or symbol
        exchange = quote.get("exchDisp") or quote["exchange"]
        matches.setdefault(symbol, TickerMatch(symbol, str(name), str(exchange), kind))
    return list(matches.values())


def fetch_sectors(tickers: Sequence[str]) -> dict[str, str]:
    """Sector per ticker; tickers whose lookup fails are left out and reported as Unknown."""
    sectors: dict[str, str] = {}
    for ticker in tickers:
        try:
            with _quiet_yfinance():
                info = yf.Ticker(to_yahoo_symbol(ticker)).info
        except Exception:  # noqa: BLE001 - a missing sector must not abort the whole report
            continue
        label = sector_label(info)
        if label:
            sectors[ticker] = label
    return sectors


def sector_label(info: Mapping[str, object]) -> str | None:
    if info.get("quoteType") == "ETF":
        category = info.get("category")
        return f"ETF: {category}" if category else "ETF"
    sector = info.get("sector")
    return str(sector) if sector else None


def fetch_fama_french(timeout: float = 30) -> pd.DataFrame:
    """Daily Fama-French five factors, momentum and the risk-free rate, as decimals."""
    five = parse_french_csv(_download_zipped_text(FIVE_FACTORS_URL, timeout))
    momentum = parse_french_csv(_download_zipped_text(MOMENTUM_URL, timeout))
    factors = five.join(momentum, how="inner")
    missing = [c for c in (*FACTOR_COLUMNS, "RF") if c not in factors.columns]
    if missing:
        raise MarketDataError(f"Ken French data is missing columns: {', '.join(missing)}")
    return factors


def parse_french_csv(text: str) -> pd.DataFrame:
    """Parse a Ken French daily file: prose, a ',col,...' header, YYYYMMDD rows in percent."""
    lines = text.splitlines()
    header_at = next((i for i, line in enumerate(lines) if line.startswith(",")), None)
    if header_at is None:
        raise MarketDataError("Ken French file has no ',column' header row")
    columns = [name.strip() for name in lines[header_at].split(",")[1:]]

    dates: list[str] = []
    values: list[list[float]] = []
    for line in lines[header_at + 1 :]:
        if not _DATE_ROW.match(line):
            break
        date, *row = line.split(",")
        dates.append(date)
        values.append([float(v) for v in row])

    index = pd.to_datetime(dates, format="%Y%m%d")
    return pd.DataFrame(values, index=index, columns=columns) / 100


def _download_zipped_text(url: str, timeout: float) -> str:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return archive.read(archive.namelist()[0]).decode("latin-1")


@contextmanager
def _quiet_yfinance() -> Iterator[None]:
    """Mute yfinance's own logging and deprecation noise; failures surface as MarketDataError."""
    logger = logging.getLogger("yfinance")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        logger.setLevel(previous_level)
