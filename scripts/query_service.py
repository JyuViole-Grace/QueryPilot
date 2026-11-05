"""Application service shared by the HTTP API and other front ends."""

from __future__ import annotations
import sqlite3
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from context_builder import build_context
from sql_generator import DEFAULT_MODEL, generate_sql
from sql_quality import validate_sql_quality
from sql_safety import execute_read_only

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENT_LOG_PATH = Path(
    os.getenv(
        "QUERYPILOT_EVENT_LOG",
        PROJECT_ROOT / "logs" / "query_events.jsonl",
        )
)

MAX_QUALITY_REPAIR_ATTEMPTS = 2

def _is_repairable_sql_error(exc: Exception) -> bool:
    """Return True only for SQLite errors that can plausibly be fixed by rewriting SQL."""
    if not isinstance(exc, sqlite3.Error):
        return False

    message = str(exc).lower()

    repairable_patterns = (
        "syntax error",
        "incomplete input",
        "no such column",
        "no such table",
        "ambiguous column name",
        "misuse of aggregate",
        "misuse of window function",
        "no such function",
        "wrong number of arguments",
    )

    return any(pattern in message for pattern in repairable_patterns)

class SQLQualityError(ValueError):
    """Raised when generated SQL still fails quality checks."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(
            "SQL quality validation failed: " + "; ".join(issues)
        )


def _write_event(event: dict[str, Any]) -> None:
    """Append a privacy-conscious structured event; logging must not break queries."""
    try:
        EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


class QueryService:
    def __init__(
            self,
            generator: Callable[..., str] = generate_sql,
            executor: Callable[[str], dict[str, Any]] = execute_read_only,
            event_writer: Callable[[dict[str, Any]], None] = _write_event,
            quality_validator: Callable[
                [str, str], dict[str, Any]
            ] = validate_sql_quality,
            repairer: Callable[..., str] | None = None,
            max_repair_attempts: int = MAX_QUALITY_REPAIR_ATTEMPTS,
    ) -> None:
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts cannot be negative.")

        self.generator = generator
        self.executor = executor
        self.event_writer = event_writer
        self.quality_validator = quality_validator
        self.repairer = repairer or generator
        self.max_repair_attempts = max_repair_attempts

    def ask(
            self,
            question: str,
            model: str = DEFAULT_MODEL,
    ) -> dict[str, Any]:
        question = question.strip()

        if not question:
            raise ValueError("The question must not be empty.")

        started = time.monotonic()
        context = None
        sql: str | None = None
        error: str | None = None
        repair_attempts = 0

        try:
            context = build_context(question)

            sql = self.generator(
                question,
                model=model,
                context=context,
            )

            last_execution_error: sqlite3.Error | None = None

            while True:
                quality_result = self.quality_validator(question, sql)

                if not quality_result["valid"]:
                    if repair_attempts >= self.max_repair_attempts:
                        if last_execution_error is not None:
                            raise last_execution_error

                        raise SQLQualityError(quality_result["issues"])

                    feedback = "; ".join(quality_result["issues"])
                    repair_attempts += 1

                    sql = self.repairer(
                        question,
                        model=model,
                        context=context,
                        previous_sql=sql,
                        error_feedback=feedback,
                        attempt=repair_attempts,
                    )
                    continue

                try:
                    execution = self.executor(sql)
                    break

                except Exception as exc:
                    if (
                            not _is_repairable_sql_error(exc)
                            or repair_attempts >= self.max_repair_attempts
                    ):
                        raise

                    last_execution_error = exc
                    repair_attempts += 1

                    feedback = (
                        f"SQLite execution error: "
                        f"{type(exc).__name__}: {exc}"
                    )

                    sql = self.repairer(
                        question,
                        model=model,
                        context=context,
                        previous_sql=sql,
                        error_feedback=feedback,
                        attempt=repair_attempts,
                    )

            return {
                "sql": sql,
                "columns": execution["columns"],
                "rows": [list(row) for row in execution["rows"]],
                "truncated": execution["truncated"],
                "execution_time_seconds": execution[
                    "execution_time_seconds"
                ],
                "context_used": bool(context),
                "quality_repair_attempts": repair_attempts,
            }

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise

        finally:
            try:
                self.event_writer(
                    {
                        "timestamp_utc": datetime.now(
                            timezone.utc
                        ).isoformat(timespec="seconds"),
                        "model": model,
                        "question_sha256_prefix": hashlib.sha256(
                            question.encode("utf-8")
                        ).hexdigest()[:16],
                        "question_length": len(question),
                        "sql_sha256_prefix": (
                            hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
                            if sql
                            else None
                        ),
                        "context_used": bool(context),
                        "success": error is None,
                        "error": error,
                        "quality_repair_attempts": repair_attempts,
                        "latency_seconds": round(
                            time.monotonic() - started,
                            4,
                            ),
                    }
                )
            except Exception:
                pass