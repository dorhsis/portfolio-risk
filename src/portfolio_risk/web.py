"""HTTP API behind the web page: the CLI's JSON report plus a password-gated LLM explanation.

The explanation spends the owner's LLM quota, so it stays off until EXPLAIN_PASSWORD is set on the
server and every call must present it.
"""

import hmac
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from portfolio_risk.explain import Explainer, LLMError, explain_with_env
from portfolio_risk.market_data import Loader, MarketDataError, load_market_data
from portfolio_risk.portfolio import parse_portfolio
from portfolio_risk.report import build_report, report_to_dict

STATIC_DIR = Path(__file__).parent / "static"
# Every holding is a Yahoo download; the cap keeps one request well inside the function time limit.
MAX_HOLDINGS = 50
MAX_PORTFOLIO_CHARS = 20_000
# A real report is a few kilobytes; the cap stops the endpoint relaying arbitrary text to the LLM.
MAX_REPORT_CHARS = 50_000


class ReportRequest(BaseModel):
    portfolio: str = Field(max_length=MAX_PORTFOLIO_CHARS)
    benchmark: str = Field(default="SPY", pattern=r"^[A-Za-z][A-Za-z.\-]{0,9}$")
    lookback_years: int = Field(default=3, ge=1, le=25)
    factors: bool = True


class ExplainRequest(BaseModel):
    report: dict[str, Any]
    password: str = Field(max_length=200)

    @field_validator("report")
    @classmethod
    def _limit_size(cls, report: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(report, ensure_ascii=False)) > MAX_REPORT_CHARS:
            raise ValueError(f"report is longer than {MAX_REPORT_CHARS} characters")
        return report


def create_app(
    loader: Loader = load_market_data,
    explainer: Explainer = explain_with_env,
    env: Mapping[str, str] = os.environ,
) -> FastAPI:
    app = FastAPI(title="Portfolio Risk", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def readable_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"] if part != "body")
        detail = f"{field}: {first['msg']}" if field else str(first["msg"])
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.post("/api/report")
    def report(request: ReportRequest) -> dict[str, Any]:
        try:
            holdings = parse_portfolio(request.portfolio)
            if len(holdings) > MAX_HOLDINGS:
                raise ValueError(f"at most {MAX_HOLDINGS} holdings allowed, got {len(holdings)}")
            benchmark = request.benchmark.upper()
            market = loader([h.ticker for h in holdings], benchmark, request.factors)
            return report_to_dict(build_report(holdings, market, benchmark, request.lookback_years))
        except MarketDataError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

    @app.post("/api/explain")
    def explanation(request: ExplainRequest) -> dict[str, str]:
        expected = env.get("EXPLAIN_PASSWORD")
        if not expected:
            raise HTTPException(
                status_code=503, detail="explanation is disabled: EXPLAIN_PASSWORD is not set"
            )
        if not hmac.compare_digest(request.password.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="wrong password")
        try:
            return {"explanation": explainer(request.report)}
        except LLMError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

    app.frontend("/", directory=STATIC_DIR, fallback=None)
    return app
