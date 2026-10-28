from typing import Any

import pytest

from portfolio_risk.grounding import numbers, ungrounded_numbers

# Real numbers from the ADR portfolio, trimmed to two positions and one scenario.
REPORT: dict[str, Any] = {
    "as_of": "2026-10-27",
    "benchmark": "SPY",
    "total_value": 25373.53,
    "window": {"start": "2023-10-27", "observations": 751},
    "positions": [
        {"ticker": "TSM", "value": 8728.8, "weight": 0.344, "risk_share": 0.4113},
        {"ticker": "ASML", "value": 8160.78, "weight": 0.3216, "risk_share": 0.4187},
    ],
    "sectors": {"Technology": 0.8061},
    "concentration": {"effective_positions": 3.8288, "top5_share": 1.0},
    "risk": {
        "volatility_annual": 0.3012,
        "benchmark_volatility_annual": 0.1522,
        "beta": 1.4398,
        "max_drawdown": {"depth": -0.2391, "peak": "2025-02-18", "trough": "2025-04-08"},
        "value_at_risk_1d": {"confidence": 0.95, "var": 0.0289, "var_amount": 733.27},
    },
    "correlation": {"average_pairwise": 0.41, "high_pairs": []},
    "factors": {"loadings": {"Mkt-RF": 1.2435, "HML": -0.4712}},
    "stress_tests": [
        {
            "scenario": "Крах доткомов",
            "start": "2000-03-24",
            "end": "2002-10-09",
            "portfolio_return": -0.7345,
            "portfolio_pnl": -18636.34,
            "proxied_by_beta": ["BABA"],
        }
    ],
}


@pytest.mark.parametrize(
    "text",
    [
        "Портфель стоит около 25 374 долларов, бета 1,44, волатильность 30,1% против 15,2%.",
        "TSM весит 34%, но даёт 41% риска.",
        "Самый тяжёлый сценарий — крах доткомов 2000–2002 годов: минус 73,4%, или 18 636 долларов.",
        "Просадка 23,9% длилась с 18 февраля по 8 апреля 2025 года.",
        "Около 25 тыс. долларов за 3 года, 751 торговый день, 95-процентный VaR.",
        "TSM и ASML весят около 34,4 и 32,2 процента.",
        "Бета и волатильность — 1,44 и 30,1%.",  # the % belongs to the second number only
    ],
)
def test_russian_restatement_of_report_numbers_is_grounded(text: str) -> None:
    assert ungrounded_numbers(text, REPORT) == []


@pytest.mark.parametrize(
    "text",
    [
        "The portfolio is worth about $25,374, with a beta of 1.44 and 30.1% volatility.",
        "TSM weighs 34.4% yet brings 41.1 percent of the risk.",
        "In the dot-com crash it would have lost 73.4%, or $18,636.",
        "The drawdown of 23.9% ran from February 18 to April 8, 2025.",
        "Prices are as of Oct 27, 2026, measured since 27 October 2023.",
        "About $18.6 thousand lost; ASML and TSM weigh 32.2 and 34.4 percent.",
        "On a bad day, seen 5% of the time at 95% confidence, it can lose $733 over 1 day.",
        "The 2001 low, the S&P 500 and the top-5 share are not invented numbers.",
    ],
)
def test_english_restatement_of_report_numbers_is_grounded(text: str) -> None:
    assert ungrounded_numbers(text, REPORT) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The adrs failure: 34.4% + 32.2% summed by the model.
        ("TSM и ASML вместе занимают около 66% стоимости.", ["66%"]),
        ("Together TSM and ASML make up about 66.6% of the value.", ["66.6%"]),
        ("Средняя доходность составила 37%.", ["37%"]),
        ("The trough came on April 5, 2025.", ["April 5, 2025"]),
        ("Дно было 4 апреля.", ["4 апреля"]),
        ("In 2006 the portfolio held up.", ["2006"]),
        ("It is worth about $90 thousand.", ["90 thousand"]),
    ],
)
def test_numbers_missing_from_the_report_are_named(text: str, expected: list[str]) -> None:
    assert ungrounded_numbers(text, REPORT) == expected


def test_lowercase_may_is_a_verb_not_a_date() -> None:
    assert ungrounded_numbers("Losses in the top 5 may exceed $733.", REPORT) == []


def test_percent_and_multiplier_words_set_the_number_kind() -> None:
    parsed = numbers("41 percent, 41%, 41 процент, $18.6 thousand, 1,44")

    assert [n.percent for n in parsed] == [True, True, True, False, False]
    assert [n.value for n in parsed] == pytest.approx([41, 41, 41, 18_600, 1.44])


def test_a_malformed_report_grounds_nothing_instead_of_failing() -> None:
    # /api/explain receives the report from the browser, so any shape can arrive.
    report = {"window": "x", "stress_tests": [{"start": None}], "risk": [], "as_of": 7}

    assert ungrounded_numbers("Бета 1,44 на 27 октября.", report) == ["1,44", "27 октября"]
