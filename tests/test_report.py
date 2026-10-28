import dataclasses
import json

import pandas as pd
import pytest
from conftest import AS_OF, synthetic_market

from portfolio_risk.portfolio import Holding
from portfolio_risk.report import (
    InsufficientHistoryError,
    MarketData,
    build_report,
    render_text,
    report_to_dict,
)
from portfolio_risk.stress import HISTORICAL_SCENARIOS

OLD_HOLDINGS = [Holding("AAA", 10), Holding("BBB", 20)]


def test_positions_weights_and_risk_shares_each_sum_to_one(market: MarketData) -> None:
    report = build_report(OLD_HOLDINGS, market)

    assert sum(p.weight for p in report.positions) == pytest.approx(1.0)
    assert sum(p.risk_share for p in report.positions) == pytest.approx(1.0)


def test_total_value_uses_latest_prices(market: MarketData) -> None:
    report = build_report(OLD_HOLDINGS, market)

    last = market.prices.iloc[-1]
    assert report.total_value == pytest.approx(10 * last["AAA"] + 20 * last["BBB"])
    assert report.as_of == AS_OF


def test_dollar_amounts_become_shares_at_the_latest_price(market: MarketData) -> None:
    report = build_report([Holding("AAA", amount=5000.0), Holding("BBB", 20)], market)

    aaa = next(p for p in report.positions if p.ticker == "AAA")
    assert aaa.value == pytest.approx(5000.0)
    assert aaa.shares == pytest.approx(5000.0 / market.prices["AAA"].iloc[-1])


def test_window_spans_the_lookback_when_history_is_long(market: MarketData) -> None:
    report = build_report(OLD_HOLDINGS, market, lookback_years=3)

    assert abs(report.window_start - (AS_OF - pd.DateOffset(years=3))) <= pd.Timedelta(days=4)
    assert 3 * 250 < report.observations < 3 * 263


def test_recent_ipo_shortens_the_window_to_its_history(market: MarketData) -> None:
    report = build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market)

    assert report.window_start >= pd.Timestamp("2025-01-02")


def test_too_little_common_history_is_rejected() -> None:
    market = synthetic_market(young_start="2026-09-15")

    with pytest.raises(InsufficientHistoryError, match="NEW"):
        build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market)


def test_stress_tests_cover_every_scenario_and_flag_proxied_holdings(market: MarketData) -> None:
    report = build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market)

    assert [r.scenario for r in report.stress] == list(HISTORICAL_SCENARIOS)
    assert all(r.proxied == ["NEW"] for r in report.stress)


def test_factor_exposure_is_computed_when_factor_data_is_present(market: MarketData) -> None:
    report = build_report(OLD_HOLDINGS, market)

    assert report.factor_exposure is not None
    weights = {p.ticker: p.weight for p in report.positions}
    expected_market_beta = 1.3 * weights["AAA"] + 0.7 * weights["BBB"]
    assert report.factor_exposure.loadings["Mkt-RF"] == pytest.approx(expected_market_beta, abs=0.1)


def test_missing_factor_data_is_explained_instead_of_failing(market: MarketData) -> None:
    without = dataclasses.replace(market, factors=None, factor_error="Ken French site is down")

    report = build_report(OLD_HOLDINGS, without)

    assert report.factor_exposure is None
    assert report.factor_note == "Ken French site is down"


def test_portfolio_may_hold_the_benchmark_itself(market: MarketData) -> None:
    report = build_report([Holding("SPY", 3)], market)

    assert report.beta == pytest.approx(1.0)
    assert report.positions[0].ticker == "SPY"


def test_missing_benchmark_prices_are_rejected(market: MarketData) -> None:
    with pytest.raises(ValueError, match="QQQ"):
        build_report(OLD_HOLDINGS, market, benchmark="QQQ")


def test_unmapped_tickers_fall_into_unknown_sector(market: MarketData) -> None:
    report = build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market)

    assert set(report.sectors) == {"Technology", "Energy", "Unknown"}


def test_report_dict_names_each_stress_scenario_by_a_stable_key(market: MarketData) -> None:
    payload = report_to_dict(build_report(OLD_HOLDINGS, market))

    assert [t["key"] for t in payload["stress_tests"]] == [s.key for s in HISTORICAL_SCENARIOS]


def test_report_dict_is_json_serializable(market: MarketData) -> None:
    payload = report_to_dict(build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market))

    decoded = json.loads(json.dumps(payload))
    assert decoded["benchmark"] == "SPY"
    assert {p["ticker"] for p in decoded["positions"]} == {"AAA", "BBB", "NEW"}
    assert len(decoded["stress_tests"]) == len(HISTORICAL_SCENARIOS)


def test_text_report_shows_key_sections_and_proxy_notes(market: MarketData) -> None:
    report = build_report([*OLD_HOLDINGS, Holding("NEW", 5)], market)

    text = render_text(report)

    for expected in ("AAA", "Вклад в риск", "Эффективное число позиций", "VaR 95%", "Бета"):
        assert expected in text
    for scenario in HISTORICAL_SCENARIOS:
        assert scenario.name in text
    assert "оценка через бету: NEW" in text


def test_text_report_explains_missing_factors(market: MarketData) -> None:
    without = dataclasses.replace(market, factors=None, factor_error="timeout")

    assert "Факторы недоступны: timeout" in render_text(build_report(OLD_HOLDINGS, without))
