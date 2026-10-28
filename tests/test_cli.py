import json
from pathlib import Path

import pytest
from conftest import FakeExplainer, FakeLoader

from portfolio_risk.cli import main
from portfolio_risk.explain import LLMError
from portfolio_risk.market_data import MarketDataError
from portfolio_risk.report import MarketData


def _portfolio(tmp_path: Path) -> Path:
    path = tmp_path / "portfolio.csv"
    path.write_text("ticker,shares\nAAA,10\nBBB,20\n")
    return path


def test_prints_text_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(_portfolio(tmp_path))], loader=FakeLoader())

    assert exit_code == 0
    assert "ПОРТФЕЛЬ на" in capsys.readouterr().out


def test_json_flag_prints_machine_readable_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(_portfolio(tmp_path)), "--json"], loader=FakeLoader())

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["currency"] == "USD"


def test_passes_tickers_benchmark_and_factor_flag_to_loader(tmp_path: Path) -> None:
    loader = FakeLoader()

    main([str(_portfolio(tmp_path)), "--benchmark", "spy", "--no-factors"], loader=loader)

    assert loader.calls == [(["AAA", "BBB"], "SPY", False)]


def test_missing_portfolio_file_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(tmp_path / "nope.csv")], loader=FakeLoader())

    assert exit_code == 1
    assert "Ошибка" in capsys.readouterr().err


def test_market_data_failure_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_loader(tickers: list[str], benchmark: str, include_factors: bool) -> MarketData:
        raise MarketDataError("no price data for: AAA")

    exit_code = main([str(_portfolio(tmp_path))], loader=failing_loader)

    assert exit_code == 1
    assert "no price data for: AAA" in capsys.readouterr().err


def test_lookback_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([str(_portfolio(tmp_path)), "--lookback-years", "0"], loader=FakeLoader())

    assert exit_info.value.code == 2


def test_explain_flag_appends_explanation_to_text_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    explainer = FakeExplainer()

    exit_code = main([str(_portfolio(tmp_path)), "--explain"], FakeLoader(), explainer.checked)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "ОБЪЯСНЕНИЕ\nРиск сосредоточен в AAA." in out
    assert {p["ticker"] for p in explainer.reports[0]["positions"]} == {"AAA", "BBB"}


def test_explain_flag_adds_explanation_to_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(_portfolio(tmp_path)), "--explain", "--json"], FakeLoader(), FakeExplainer().checked)

    assert json.loads(capsys.readouterr().out)["explanation"] == "Риск сосредоточен в AAA."


def test_explainer_is_not_called_without_the_flag(tmp_path: Path) -> None:
    explainer = FakeExplainer()

    main([str(_portfolio(tmp_path))], FakeLoader(), explainer.checked)

    assert explainer.reports == []


def test_llm_failure_still_prints_report_and_exits_with_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    explainer = FakeExplainer(LLMError("LLM API returned HTTP 401: Unauthorized"))

    exit_code = main([str(_portfolio(tmp_path)), "--explain"], FakeLoader(), explainer.checked)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ПОРТФЕЛЬ на" in captured.out
    assert "HTTP 401" in captured.err


def test_unverified_numbers_are_flagged_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    explainer = FakeExplainer("Вместе 66%.", unverified=("66%",))

    exit_code = main([str(_portfolio(tmp_path)), "--explain"], FakeLoader(), explainer.checked)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ОБЪЯСНЕНИЕ\nВместе 66%." in captured.out
    assert "66%" in captured.err


def test_unverified_numbers_are_listed_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    explainer = FakeExplainer("Вместе 66%.", unverified=("66%",))

    main([str(_portfolio(tmp_path)), "--explain", "--json"], FakeLoader(), explainer.checked)

    assert json.loads(capsys.readouterr().out)["unverified_numbers"] == ["66%"]
