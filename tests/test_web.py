from typing import Any

import pytest
from conftest import FakeExplainer, FakeLoader
from fastapi.testclient import TestClient

from portfolio_risk.explain import LLMError
from portfolio_risk.market_data import MarketDataError, TickerMatch
from portfolio_risk.report import MarketData
from portfolio_risk.web import MAX_HOLDINGS, MAX_REPORT_CHARS, create_app

PASSWORD = "correct horse battery staple"
PORTFOLIO = "ticker,shares\nAAA,10\nBBB,20\n"
REPORT = {"total_value": 91512.0, "risk": {"beta": 1.28}}
APPLE = TickerMatch("AAPL", "Apple Inc.", "NASDAQ", "stock")


class FakeSearcher:
    """Stands in for Yahoo search: records each query and returns or raises a canned result."""

    def __init__(self, result: list[TickerMatch] | Exception | None = None) -> None:
        self.result = [APPLE] if result is None else result
        self.queries: list[str] = []

    def __call__(self, query: str) -> list[TickerMatch]:
        self.queries.append(query)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(
    loader: Any = None,
    explainer: Any = None,
    env: dict[str, str] | None = None,
    searcher: Any = None,
) -> TestClient:
    app = create_app(
        loader=loader or FakeLoader(),
        explainer=explainer or FakeExplainer(),
        env={"EXPLAIN_PASSWORD": PASSWORD} if env is None else env,
        searcher=searcher or FakeSearcher(),
    )
    return TestClient(app)


def test_report_returns_the_cli_json_contract() -> None:
    response = _client().post("/api/report", json={"portfolio": PORTFOLIO})

    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert {p["ticker"] for p in body["positions"]} == {"AAA", "BBB"}


def test_report_passes_benchmark_and_factor_flag_to_loader() -> None:
    loader = FakeLoader()

    _client(loader=loader).post(
        "/api/report", json={"portfolio": PORTFOLIO, "benchmark": "spy", "factors": False}
    )

    assert loader.calls == [(["AAA", "BBB"], "SPY", False)]


def test_report_accepts_dollar_amounts() -> None:
    response = _client().post("/api/report", json={"portfolio": "AAA $5000\nBBB 20\n"})

    assert response.status_code == 200
    aaa = next(p for p in response.json()["positions"] if p["ticker"] == "AAA")
    assert aaa["value"] == pytest.approx(5000.0)


def test_invalid_portfolio_is_a_client_error_with_the_reason() -> None:
    response = _client().post("/api/report", json={"portfolio": "ticker,shares\nAAA,lots\n"})

    assert response.status_code == 400
    assert "shares must be a number" in response.json()["detail"]


def test_too_many_holdings_are_rejected_before_loading_data() -> None:
    loader = FakeLoader()
    rows = "".join(f"T{i},1\n" for i in range(MAX_HOLDINGS + 1))

    response = _client(loader=loader).post(
        "/api/report", json={"portfolio": f"ticker,shares\n{rows}"}
    )

    assert response.status_code == 400
    assert str(MAX_HOLDINGS) in response.json()["detail"]
    assert loader.calls == []


def test_market_data_failure_is_a_bad_gateway() -> None:
    def failing_loader(tickers: list[str], benchmark: str, include_factors: bool) -> MarketData:
        raise MarketDataError("no price data for: AAA")

    response = _client(loader=failing_loader).post("/api/report", json={"portfolio": PORTFOLIO})

    assert response.status_code == 502
    assert response.json()["detail"] == "no price data for: AAA"


def test_validation_error_detail_is_a_readable_string() -> None:
    response = _client().post("/api/report", json={"portfolio": PORTFOLIO, "lookback_years": 0})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith("lookback_years:")


def test_explain_returns_the_explanation_for_the_right_password() -> None:
    explainer = FakeExplainer()

    response = _client(explainer=explainer).post(
        "/api/explain", json={"report": REPORT, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json() == {"explanation": "Риск сосредоточен в AAA."}
    assert explainer.reports == [REPORT]
    assert explainer.languages == ["ru"]


def test_explain_answers_in_the_requested_language() -> None:
    explainer = FakeExplainer()

    _client(explainer=explainer).post(
        "/api/explain", json={"report": REPORT, "password": PASSWORD, "language": "en"}
    )

    assert explainer.languages == ["en"]


def test_explain_rejects_an_unsupported_language() -> None:
    explainer = FakeExplainer()

    response = _client(explainer=explainer).post(
        "/api/explain", json={"report": REPORT, "password": PASSWORD, "language": "de"}
    )

    assert response.status_code == 422
    assert explainer.reports == []


def test_explain_rejects_a_wrong_password_without_calling_the_llm() -> None:
    explainer = FakeExplainer()

    response = _client(explainer=explainer).post(
        "/api/explain", json={"report": REPORT, "password": "guess"}
    )

    assert response.status_code == 401
    assert explainer.reports == []


def test_explain_is_disabled_until_a_password_is_configured() -> None:
    explainer = FakeExplainer()

    response = _client(explainer=explainer, env={}).post(
        "/api/explain", json={"report": REPORT, "password": ""}
    )

    assert response.status_code == 503
    assert "EXPLAIN_PASSWORD" in response.json()["detail"]
    assert explainer.reports == []


def test_explain_reports_llm_failure_as_bad_gateway() -> None:
    explainer = FakeExplainer(LLMError("LLM API returned HTTP 401: Unauthorized"))

    response = _client(explainer=explainer).post(
        "/api/explain", json={"report": REPORT, "password": PASSWORD}
    )

    assert response.status_code == 502
    assert "HTTP 401" in response.json()["detail"]


def test_explain_rejects_an_oversized_report() -> None:
    explainer = FakeExplainer()
    report = {"padding": "x" * MAX_REPORT_CHARS}

    response = _client(explainer=explainer).post(
        "/api/explain", json={"report": report, "password": PASSWORD}
    )

    assert response.status_code == 422
    assert explainer.reports == []


def test_home_page_is_served() -> None:
    response = _client().get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/report" in _client().get("/app.js").text


def test_parse_returns_holdings_without_loading_market_data() -> None:
    loader = FakeLoader()

    response = _client(loader=loader).post(
        "/api/parse", json={"portfolio": "aaa 10\nBBB $2500\naaa $100\n"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "holdings": [
            {"ticker": "AAA", "shares": 10.0, "amount": 100.0},
            {"ticker": "BBB", "shares": 0.0, "amount": 2500.0},
        ]
    }
    assert loader.calls == []


def test_parse_reports_the_failing_line() -> None:
    response = _client().post("/api/parse", json={"portfolio": "AAA 1\nBBB lots\n"})

    assert response.status_code == 400
    assert response.json()["detail"].startswith("line 2:")


def test_parse_applies_the_holdings_limit() -> None:
    rows = "".join(f"T{i} 1\n" for i in range(MAX_HOLDINGS + 1))

    response = _client().post("/api/parse", json={"portfolio": rows})

    assert response.status_code == 400
    assert str(MAX_HOLDINGS) in response.json()["detail"]


def test_search_returns_matches_for_the_query() -> None:
    searcher = FakeSearcher()

    response = _client(searcher=searcher).get("/api/search", params={"q": " apple "})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "kind": "stock"}]
    }
    assert searcher.queries == ["apple"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 61])
def test_search_rejects_empty_or_overlong_queries(query: str) -> None:
    searcher = FakeSearcher()

    response = _client(searcher=searcher).get("/api/search", params={"q": query})

    assert response.status_code == 422
    assert searcher.queries == []


def test_search_failure_is_a_bad_gateway() -> None:
    searcher = FakeSearcher(MarketDataError("Yahoo search failed: timed out"))

    response = _client(searcher=searcher).get("/api/search", params={"q": "apple"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Yahoo search failed: timed out"
