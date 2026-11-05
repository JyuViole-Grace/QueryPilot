"""FastAPI entry point for QueryPilot."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from query_service import QueryService, SQLQualityError  # noqa: E402
from sql_generator import (  # noqa: E402
    DEFAULT_MODEL,
    ModelNotFoundError,
    ModelUnavailableError,
)

logger = logging.getLogger("querypilot.api")

app = FastAPI(title="QueryPilot", version="1.0.0", description="Safe local Text-to-SQL demo")
service = QueryService()
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _allowed_models() -> frozenset[str]:
    """Models the API accepts. Override with QUERYPILOT_ALLOWED_MODELS=a,b."""
    raw = os.getenv("QUERYPILOT_ALLOWED_MODELS", "")
    models = {item.strip() for item in raw.split(",") if item.strip()}
    return frozenset(models or {DEFAULT_MODEL})


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=200)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/query")
def query(request: QueryRequest) -> dict:
    if request.model not in _allowed_models():
        raise HTTPException(
            status_code=400,
            detail=f"Model '{request.model}' is not enabled on this server.",
        )

    try:
        return service.ask(request.question, request.model)

    except ModelNotFoundError as exc:
        # The requested model is not installed in Ollama.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    except ModelUnavailableError as exc:
        # Ollama is down or timed out: a server-side dependency problem.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    except SQLQualityError as exc:
        # The model could not produce acceptable SQL for this question.
        raise HTTPException(
            status_code=422,
            detail="The model could not produce a valid query for this question. "
                   "Try rephrasing it. Issues: " + "; ".join(exc.issues),
        ) from exc

    except ValueError as exc:
        # Includes empty questions and rejected (non-read-only) SQL.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except sqlite3.Error as exc:
        logger.warning("Generated SQL failed to execute: %s", exc)
        raise HTTPException(
            status_code=422,
            detail="The generated SQL could not be executed. Try rephrasing the question.",
        ) from exc

    except RuntimeError as exc:
        # Bad reply from Ollama (unexpected format, HTTP error, empty SQL).
        logger.error("Model backend error: %s", exc)
        raise HTTPException(status_code=502, detail="The model backend returned an error.") from exc

    except Exception as exc:  # noqa: BLE001 - last resort, never leak internals
        logger.exception("Unexpected error while answering a question")
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
