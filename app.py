"""Web entrypoint: Vercel loads `app` from here, and `uvicorn app:app` serves it locally.

Vercel installs the package itself with `uv sync`, so the app is imported from it rather than
from src/. A local .env supplies EXPLAIN_PASSWORD and LLM_* during development; on Vercel they
come from the project's environment variables.
"""

from dotenv import find_dotenv, load_dotenv

from portfolio_risk.web import create_app

load_dotenv(find_dotenv(usecwd=True))
app = create_app()
