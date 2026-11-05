"""Reliable evaluation of SQL generation.

Modes:
- baseline: repair only after SQL execution errors.
- oracle_assisted: repair using reference-derived feedback; upper bound only.
- quality_self_correction: repair after execution errors or deterministic
  SQL quality-validator failures, without reference-derived feedback.

Metrics are defined in scoring.py (strict, execution_match, lenient, relaxed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scoring import compare, wilson_interval
from sql_generator import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    ModelNotFoundError,
    generate_sql,
)
from sql_quality import (
    repair_supplier_rating_alias,
    repair_order_line_items_total_alias,
    repair_cheapest_products_id_alias,
    validate_sql_quality,
)
from sql_safety import execute_read_only
from context_builder import build_context, context_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_questions.json"
HELDOUT_PATH = PROJECT_ROOT / "tests" / "heldout_questions.json"
HELDOUT_V3_PATH = PROJECT_ROOT / "tests" / "heldout_v3_questions.json"
HELDOUT_V4_PATH = PROJECT_ROOT / "tests" / "heldout_v4_questions.json"

DATASETS = {
    "golden": GOLDEN_PATH,
    "heldout": HELDOUT_PATH,
    "heldout_v3": HELDOUT_V3_PATH,
    "heldout_v4": HELDOUT_V4_PATH,
}
REPORT_DIR = PROJECT_ROOT / "reports"

MAX_CORRECTION_RETRIES = 2
MAX_CONSECUTIVE_GENERATION_ERRORS = 3

MODE_BASELINE = "baseline"
MODE_ORACLE = "oracle_assisted"
MODE_QUALITY_REPAIR = "quality_self_correction"

Generator = Callable[..., str]
Executor = Callable[[str], dict[str, Any]]


# ============================================================
# Dataset loading and fingerprints
# ============================================================

def load_golden_dataset(
        path: Path = GOLDEN_PATH,
) -> list[dict[str, Any]]:
    """Load a test list or a JSON object containing a tests key."""
    if not path.exists():
        raise FileNotFoundError(f"Question dataset not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    tests = data["tests"] if isinstance(data, dict) else data

    if not isinstance(tests, list) or not tests:
        raise ValueError("The dataset contains no tests.")

    required = {
        "id",
        "question",
        "category",
        "reference_sql",
        "expected_columns",
        "expected_result",
    }

    for test in tests:
        missing = required - set(test)
        if missing:
            raise ValueError(
                f"Test {test.get('id')} is missing fields: "
                f"{sorted(missing)}"
            )

    return tests


def load_dataset_metadata(
        path: Path = GOLDEN_PATH,
) -> dict[str, Any]:
    """Return dataset metadata outside the test list."""
    data = json.loads(path.read_text(encoding="utf-8"))

    return (
        {key: value for key, value in data.items() if key != "tests"}
        if isinstance(data, dict)
        else {}
    )


def prompt_fingerprint() -> str:
    """Fingerprint the current system prompt."""
    return hashlib.sha256(
        SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()[:16]


def dataset_fingerprint(path: Path = GOLDEN_PATH) -> str:
    """Fingerprint the exact dataset file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

def execute_candidate(
        sql: str,
        executor: Executor | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Execute SQL without accessing reference answers."""
    run = executor or execute_read_only

    outcome: dict[str, Any] = {
        "executed": False,
        "error": None,
        "columns": [],
        "row_count": 0,
        "truncated": False,
    }

    try:
        execution = run(sql)
    except (sqlite3.Error, ValueError) as exc:
        outcome["error"] = f"{type(exc).__name__}: {exc}"
        return outcome, None

    outcome.update({
        "executed": True,
        "columns": execution["columns"],
        "row_count": len(execution["rows"]),
        "truncated": execution["truncated"],
        "execution_time_seconds": execution["execution_time_seconds"],
    })

    if execution["truncated"]:
        outcome["error"] = "Result truncated at the row limit."
        return outcome, None

    return outcome, execution
# ============================================================
# Evaluate one SQL candidate
# ============================================================

def evaluate_candidate(
        test: dict[str, Any],
        sql: str,
        executor: Executor | None = None,
) -> dict[str, Any]:
    """Execute SQL and compare its result against the reference."""
    outcome, execution = execute_candidate(sql, executor)

    outcome.update({
        "strict": False,
        "execution_match": False,
        "lenient": False,
        "relaxed": False,
        "columns_match": False,
    })

    if execution is None:
        return outcome

    outcome.update(
        compare(test, execution["columns"], execution["rows"])
    )

    return outcome


def short_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    """Select the outcome fields included in reports."""
    keys = (
        "executed",
        "error",
        "strict",
        "execution_match",
        "lenient",
        "relaxed",
        "columns_match",
        "columns",
        "row_count",
    )

    return {
        key: outcome.get(key)
        for key in keys
    }


# ============================================================
# Repair feedback
# ============================================================

def build_error_feedback(error: str) -> str:
    """Feedback based only on runtime execution errors."""
    return (
        "The query failed to execute.\n"
        f"SQLite error: {error}\n"
        "Check syntax, table and column names, and table relationships."
    )


def build_oracle_feedback(
        test: dict[str, Any],
        outcome: dict[str, Any],
) -> str:
    """Reference-derived feedback; this is not available at runtime."""
    if not outcome["executed"]:
        return build_error_feedback(
            outcome["error"] or "unknown error"
        )

    return (
        "The result does not match the reference.\n"
        f"Expected columns: {test['expected_columns']}\n"
        f"Actual columns: {outcome['columns']}\n"
        f"Expected row count: {len(test['expected_result'])}\n"
        f"Actual row count: {outcome['row_count']}"
    )

def build_customer_absence_guidance(
        question: str,
        quality_result: dict[str, Any],
) -> str | None:
    """Explain customer-level absence checks during SQL repair."""

    normalized_question = question.casefold()

    is_target_question = (
            "customer" in normalized_question
            and "cancelled" in normalized_question
            and "delivered" in normalized_question
            and any(
        phrase in normalized_question
        for phrase in (
            "no delivered orders",
            "without delivered orders",
            "no orders delivered",
        )
    )
    )

    if not is_target_question:
        return None

    if quality_result["valid"]:
        return None

    return (
        "IMPORTANT SEMANTIC CORRECTION:\n"
        "The question asks for customers who satisfy two independent "
        "conditions at the customer level:\n"
        "1. The customer has at least one cancelled order.\n"
        "2. The customer has zero delivered orders.\n"
        "A row-level condition such as status != 'delivered' does NOT "
        "prove that a customer has no delivered orders. A customer may "
        "have both cancelled and delivered orders.\n"
        "Use a correlated NOT EXISTS subquery against orders for the "
        "absence condition. It must be part of the outer customer "
        "filter and correlated with the current customer's customer_id.\n"
        "Do not build a CTE of non-delivered order rows and use it as "
        "a substitute for the absence check.\n"
        "Keep the cancelled-order existence check separate from the "
        "delivered-order absence check."
    )

def build_quality_feedback(
        question: str,
        sql: str,
        outcome: dict[str, Any],
        quality_result: dict[str, Any],
) -> str:
    """Build repair feedback without using reference answers."""
    parts = [
        "Review and correct the SQL query.",
        f"User question: {question}",
        f"Current SQL: {sql}",
        "Preserve the meaning of the user's question.",
    ]

    if not outcome["executed"]:
        parts.append(
            "The query failed to execute. "
            f"Execution error: {outcome['error'] or 'unknown error'}"
        )

    if not quality_result["valid"]:
        parts.append(
            "The SQL quality validator reported these issues:"
        )
        parts.extend(
            f"- {issue}" for issue in quality_result["issues"]
        )
    semantic_guidance = build_customer_absence_guidance(
        question,
        quality_result,
    )

    if semantic_guidance:
        parts.append(semantic_guidance)
    parts.append(
        "Return only the corrected SQL query. "
        "Do not include explanations or Markdown fences."
    )

    return "\n".join(parts)


# ============================================================
# Evaluate one question and the full dataset
# ============================================================

def same_sql(first: str, second: str) -> bool:
    """Compare SQL while ignoring outer whitespace and trailing semicolons.

    Whitespace inside a query is deliberately preserved because it may
    occur in string literals and affect query results.
    """
    def clean(sql: str) -> str:
        return sql.strip().rstrip(";").strip()

    return clean(first) == clean(second)


EMPTY_OUTCOME = {
    "executed": False,
    "error": None,
    "strict": False,
    "execution_match": False,
    "lenient": False,
    "relaxed": False,
    "columns_match": False,
    "columns": [],
    "row_count": 0,
}


def candidate_score(
        outcome: dict[str, Any],
        quality_result: dict[str, Any],
) -> tuple:
    """Rank SQL candidates without using reference-answer metrics."""
    return (
        bool(outcome["executed"]),
        bool(quality_result["valid"]),
        -len(quality_result["issues"]),
    )


def evaluate_question(
        test: dict[str, Any],
        generate: Generator,
        retries: int,
        oracle: bool,
        executor: Executor | None = None,
        quality_repair: bool = False,
        deterministic_repairs: bool = True,
) -> dict[str, Any]:
    """Generate SQL and optionally repair execution or quality failures.

    baseline:
        Retry only after execution errors.

    oracle_assisted:
        Retry until a strict match, using reference-derived feedback.

    quality_self_correction:
        Retry after execution errors or quality-validator failures.
        Candidate selection does not access reference-answer metrics.
        Reference comparison is performed only after candidate selection.
    """
    if retries < 0:
        raise ValueError("retries must be >= 0.")

    if oracle and quality_repair:
        raise ValueError(
            "oracle and quality_repair modes cannot be enabled together."
        )

    question = test["question"]
    history: list[dict[str, Any]] = []

    mode = (
        MODE_ORACLE if oracle
        else MODE_QUALITY_REPAIR if quality_repair
        else MODE_BASELINE
    )

    result: dict[str, Any] = {
        "test_id": test["id"],
        "question": question,
        "category": test["category"],
        "mode": mode,
        "initial_sql": None,
        "final_sql": None,
        "attempts": 0,
        "generation_attempts": 0,
        "correction_history": history,
        "generation_error": None,
        "stuck_on_same_sql": False,
        "first_attempt": dict(EMPTY_OUTCOME),
        "final": dict(EMPTY_OUTCOME),
    }

    # Initial SQL generation.
    try:
        result["generation_attempts"] += 1
        sql = generate(question)
    except ModelNotFoundError:
        raise
    except Exception as exc:
        result["generation_error"] = (
            f"{type(exc).__name__}: {exc}"
        )
        return result

    # In quality mode, execute without comparing against reference data.
    if quality_repair:
        outcome, execution = execute_candidate(sql, executor)
    else:
        outcome = evaluate_candidate(test, sql, executor)
        execution = None

    result["initial_sql"] = sql
    result["attempts"] = 1

    first_outcome = dict(outcome)
    first_execution = execution

    # Keep the best candidate separately from the current candidate.
    best_sql = sql
    best_outcome = dict(outcome)
    best_execution = execution

    best_quality = (
        validate_sql_quality(question, sql)
        if quality_repair
        else {"valid": True, "issues": []}
    )

    best_score = candidate_score(best_outcome, best_quality)

    # Correction loop.
    while result["attempts"] <= retries:
        quality_result = (
            validate_sql_quality(question, sql)
            if quality_repair
            else {"valid": True, "issues": []}
        )

        if oracle:
            needs_retry = not outcome["strict"]

        elif quality_repair:
            needs_retry = (
                not outcome["executed"]
                or not quality_result["valid"]
            )

        else:
            # Preserve the original baseline behavior.
            needs_retry = not outcome["executed"]

        if not needs_retry:
            break

        if oracle:
            feedback = build_oracle_feedback(test, outcome)

        elif quality_repair:
            feedback = build_quality_feedback(
                question,
                sql,
                outcome,
                quality_result,
            )

        else:
            feedback = build_error_feedback(
                outcome["error"] or "unknown error"
            )

        history.append({
            "attempt": result["attempts"],
            "sql": sql,
            "error": outcome["error"],
            "feedback": feedback,
            "quality_issues": (
                quality_result["issues"] if quality_repair else []
            ),
        })

        # Generate a corrected SQL candidate.
        try:
            result["generation_attempts"] += 1
            new_sql = generate(
                question,
                previous_sql=sql,
                error_feedback=feedback,
                attempt=result["attempts"],
            )

        except ModelNotFoundError:
            raise

        except Exception as exc:
            result["generation_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            break

        # Stop if the model repeats the same query.
        if same_sql(new_sql, sql):
            history[-1]["repeated_same_sql"] = True
            result["stuck_on_same_sql"] = True
            break

        # Evaluate the newly generated candidate.
        sql = new_sql

        if quality_repair:
            outcome, execution = execute_candidate(sql, executor)
        else:
            outcome = evaluate_candidate(test, sql, executor)
            execution = None

        result["attempts"] += 1

        # Validate and compare candidates only in quality mode.
        if quality_repair:
            candidate_quality = validate_sql_quality(
                question,
                sql,
            )

            current_score = candidate_score(
                outcome,
                candidate_quality,
            )

            if current_score > best_score:
                best_sql = sql
                best_outcome = dict(outcome)
                best_execution = execution
                best_quality = candidate_quality
                best_score = current_score

    # Select the best candidate instead of blindly using the last one.
    if quality_repair:
        sql = best_sql
        outcome = dict(best_outcome)
        execution = best_execution

    # Apply narrowly scoped deterministic repairs after LLM attempts.
    deterministic_repair = {
        "attempted": False,
        "applied": False,
        "original_sql": None,
    }

    if (
            quality_repair
            and deterministic_repairs
            and not best_quality["valid"]
    ):
        repaired_sql = sql

        for repair_function in (
                repair_supplier_rating_alias,
                repair_order_line_items_total_alias,
                repair_cheapest_products_id_alias,
        ):
            repaired_sql = repair_function(
                question,
                repaired_sql,
            )

        if not same_sql(repaired_sql, sql):
            deterministic_repair["attempted"] = True
            deterministic_repair["original_sql"] = sql

            repaired_outcome, repaired_execution = execute_candidate(
                repaired_sql,
                executor,
            )

            repaired_quality = validate_sql_quality(
                question,
                repaired_sql,
            )

            if (
                    repaired_quality["valid"]
                    and repaired_outcome["executed"]
                    and repaired_execution is not None
            ):
                deterministic_repair["applied"] = True

                sql = repaired_sql
                outcome = dict(repaired_outcome)
                execution = repaired_execution

    # Reference metrics are calculated only after candidate selection.
    if quality_repair:
        if first_execution is not None:
            first_outcome.update(
                compare(
                    test,
                    first_execution["columns"],
                    first_execution["rows"],
                )
            )

        if execution is not None:
            outcome.update(
                compare(
                    test,
                    execution["columns"],
                    execution["rows"],
                )
            )

    result["first_attempt"] = short_outcome(first_outcome)
    result["deterministic_repair"] = deterministic_repair
    result["final_sql"] = sql
    result["final"] = short_outcome(outcome)

    # Recalculate quality for the actual final SQL.
    if quality_repair:
        result["final_quality"] = validate_sql_quality(
            question,
            sql,
        )

    return result


# ============================================================
# Summary and metrics
# ============================================================

def summarize(
        results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize first-attempt and post-repair metrics."""
    total = len(results)
    keys = ("executed", "strict", "execution_match", "lenient")

    stages = {
        stage: {
            key: sum(
                1 for item in results if item[stage][key]
            )
            for key in keys
        }
        for stage in ("first_attempt", "final")
    }

    # Older reports have no "relaxed" flag; rescore them to populate it.
    for stage in stages:
        stages[stage]["relaxed"] = sum(
            1 for item in results if item[stage].get("relaxed")
        )

    categories: dict[str, dict[str, int]] = {}

    for item in results:
        entry = categories.setdefault(item["category"], {
            "total": 0,
            "first_attempt_execution_match": 0,
            "final_execution_match": 0,
        })

        entry["total"] += 1

        entry["first_attempt_execution_match"] += int(
            item["first_attempt"].get("execution_match") is True
        )

        entry["final_execution_match"] += int(
            item["final"].get("execution_match") is True
        )

    repair_attempts = sum(
        int(
            item.get("deterministic_repair", {}).get(
                "attempted",
                item.get("deterministic_repair", {}).get(
                    "applied",
                    False,
                ),
            )
        )
        for item in results
    )

    repairs_applied = sum(
        int(
            item.get("deterministic_repair", {}).get(
                "applied",
                False,
            )
        )
        for item in results
    )

    repair_successes = sum(
        int(
            item.get("deterministic_repair", {}).get(
                "applied",
                False,
            )
            and item.get("final", {}).get(
                "execution_match",
                False,
            )
        )
        for item in results
    )
    return {
        "deterministic_repair_attempts": repair_attempts,
        "deterministic_repairs": repairs_applied,
        "deterministic_repair_successes": repair_successes,
        "total": total,
        "stages": stages,
        "by_category": categories,
        "average_attempts": round(
            sum(item["attempts"] for item in results) / total,
            2,
            ) if total else 0,
        "average_generation_attempts": round(
            sum(
                item.get("generation_attempts", item.get("attempts", 1))
                for item in results
            ) / total,
            2,
            ) if total else 0,
        "stuck_on_same_sql": sum(
            1 for item in results if item.get("stuck_on_same_sql")
        ),
        "quality_valid_after_repair": (
            sum(
                1 for item in results
                if item.get("final_quality", {}).get("valid", False)
            )
            if any("final_quality" in item for item in results)
            else None
        ),
    }


def print_summary(
        summary: dict[str, Any],
        title: str,
) -> None:
    total = summary["total"]

    def cell(count: int) -> str:
        return (
            f"{count:>2}/{total} ({count / total:>4.0%})"
            if total else "-"
        )

    labels = (
        ("strict", "strict (column names + order)"),
        ("execution_match", "execution match (EX)"),
        ("lenient", "lenient (extra columns allowed)"),
        ("relaxed", "relaxed (float tol., optional IDs)"),
        ("executed", "SQL executed without errors"),
    )

    print()
    print("=" * 72)
    print(title)
    print("=" * 72)
    print(
        f"{'Metric':30} "
        f"{'First attempt':>18} "
        f"{'After repair':>20}"
    )

    for key, label in labels:
        first = summary["stages"]["first_attempt"][key]
        final = summary["stages"]["final"][key]

        print(
            f"{label:30} "
            f"{cell(first):>18} "
            f"{cell(final):>20}"
        )

    if total:
        low1, high1 = wilson_interval(
            summary["stages"]["first_attempt"]["execution_match"],
            total,
        )

        low2, high2 = wilson_interval(
            summary["stages"]["final"]["execution_match"],
            total,
        )

        print(
            f"\nEX, 95% confidence interval: "
            f"first attempt {low1:.0%}-{high1:.0%}, "
            f"after repair {low2:.0%}-{high2:.0%}"
        )

        print(
            "(With this sample size, a difference of 1–2 questions "
            "may be noise.)"
        )

    print(f"\nAverage attempts: {summary['average_attempts']}")
    print(
        "Average generation attempts: "
        f"{summary['average_generation_attempts']}"
    )

    if summary.get("stuck_on_same_sql"):
        print(
            "The model repeated the same SQL after feedback: "
            f"{summary['stuck_on_same_sql']}"
        )

    if summary.get("quality_valid_after_repair") is not None:
        print(
            "Quality validator passed after repair: "
            f"{summary['quality_valid_after_repair']}/{total}"
        )
    if summary.get("deterministic_repair_attempts", 0) > 0:
        print("\nDeterministic repair metrics:")
        print(
            "  Attempts: "
            f"{summary['deterministic_repair_attempts']}"
        )
        print(
            "  Repairs applied: "
            f"{summary['deterministic_repairs']}"
        )
        print(
            "  Execution matches after repair: "
            f"{summary['deterministic_repair_successes']}"
        )
    print("\nBy category (EX, first attempt -> after repair):")

    for name, entry in sorted(summary["by_category"].items()):
        print(
            f"  {name:26} "
            f"{entry['first_attempt_execution_match']}/{entry['total']}"
            f" -> {entry['final_execution_match']}/{entry['total']}"
        )


# ============================================================
# Full dataset evaluation
# ============================================================

def run_evaluation(
        tests: list[dict[str, Any]],
        generate: Generator,
        retries: int = MAX_CORRECTION_RETRIES,
        oracle: bool = False,
        executor: Executor | None = None,
        verbose: bool = True,
        quality_repair: bool = False,
        deterministic_repairs: bool = True,
        checkpoint=None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate the dataset and return results and summary."""
    results: list[dict[str, Any]] = []
    consecutive_errors = 0

    for test in tests:
        item = evaluate_question(
            test,
            generate,
            retries,
            oracle,
            executor,
            quality_repair=quality_repair,
            deterministic_repairs=deterministic_repairs,
        )

        results.append(item)

        if checkpoint is not None:
            checkpoint(results, summarize(results))

        consecutive_errors = (
            consecutive_errors + 1
            if item["generation_error"]
            else 0
        )

        if consecutive_errors >= MAX_CONSECUTIVE_GENERATION_ERRORS:
            raise RuntimeError(
                f"{consecutive_errors} consecutive generation errors; "
                "evaluation stopped. "
                f"Last error: {item['generation_error']}"
            )

        if verbose:
            mark = (
                "OK  " if item["final"]["execution_match"] else "FAIL"
            )

            print(
                f"[{mark}] {test['id']} "
                f"attempts={item['attempts']}  "
                f"{test['question'][:60]}"
            )

    return results, summarize(results)


# ============================================================
# Report saving
# ============================================================

def save_report(
        model: str,
        oracle: bool,
        retries: int,
        results: list[dict[str, Any]],
        summary: dict[str, Any],
        partial: bool = False,
        dataset: str = "golden",
        report_name: str | None = None,
        quality_repair: bool = False,
        deterministic_repairs: bool = True,
        resample_on_repeat: bool = False,
) -> Path:
    """Save a report without overwriting reports from other modes."""
    if oracle and quality_repair:
        raise ValueError(
            "oracle and quality_repair modes cannot be enabled together."
        )

    directory = REPORT_DIR / "scratch" if partial else REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)

    metadata = load_dataset_metadata(DATASETS[dataset])
    dataset_version = metadata.get("version", "unknown")
    prefix = "" if dataset == "golden" else f"{dataset}_"

    mode_name = (
        MODE_ORACLE if oracle
        else MODE_QUALITY_REPAIR if quality_repair
        else MODE_BASELINE
    )

    repair_suffix = (
        "_no_deterministic"
        if quality_repair and not deterministic_repairs
        else ""
    )

    default_name = (
       f"{prefix}{mode_name}{repair_suffix}"
       f"_v{dataset_version}_evaluation.json"
    )

    if report_name:
        if (
                Path(report_name).name != report_name
                or not report_name.endswith(".json")
        ):
            raise ValueError(
                "--report-name must be a JSON filename "
                "without a directory path."
            )

        path = directory / report_name

    else:
        path = directory / default_name

    report = {
        "model": model,
        "mode": mode_name,
        "oracle_assisted": oracle,
        "quality_repair_enabled": quality_repair,
        "deterministic_repairs_enabled": (
                quality_repair and deterministic_repairs
        ),
        "max_correction_retries": retries,
        "dataset": dataset,
        "dataset_version": dataset_version,
        "dataset_language": metadata.get("language"),
        "dataset_test_count": metadata.get("test_count", len(results)),
        "dataset_sha256_prefix": dataset_fingerprint(DATASETS[dataset]),
        "prompt_sha256_prefix": prompt_fingerprint(),
        "context_version": context_version(),
        "resample_on_repeat_enabled": resample_on_repeat,
        "created_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "summary": summary,
        "results": results,
    }

    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return path


# ============================================================
# Modes that do not require a model
# ============================================================

def run_reference_tests(
        executor: Executor | None = None,
        path: Path = GOLDEN_PATH,
) -> list[dict[str, Any]]:
    """Verify that reference SQL reproduces stored expected results."""
    results = []

    for test in load_golden_dataset(path):
        outcome = evaluate_candidate(
            test,
            test["reference_sql"],
            executor,
        )

        results.append({
            "test_id": test["id"],
            "passed": outcome["strict"],
            "error": outcome["error"],
        })

        print(
            f"[{'OK  ' if outcome['strict'] else 'FAIL'}] "
            f"{test['id']}  {outcome['error'] or ''}"
        )

    passed = sum(
        1 for item in results if item["passed"]
    )

    print(f"\nReference queries: {passed}/{len(results)}")

    return results


def rescore_report(
        path: Path,
        tests: list[dict[str, Any]] | None = None,
        executor: Executor | None = None,
        dataset: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-score a saved report without calling the model."""
    report = json.loads(path.read_text(encoding="utf-8"))

    if report.get("critic_observe_enabled") or report.get("mode") == "critic_observe":
        print(
            "[INFO] This report was made with the semantic critic, which has "
            "been removed. Its reviews are ignored; only the saved SQL is re-scored."
        )

    report_dataset = report.get("dataset")

    if report_dataset is not None:
        if report_dataset not in DATASETS:
            raise ValueError(
                f"Unknown dataset in report: {report_dataset!r}."
            )

        dataset_path = DATASETS[report_dataset]
        saved_fingerprint = report.get("dataset_sha256_prefix")

        if not saved_fingerprint:
            raise ValueError(
                "The report contains dataset metadata but no dataset "
                "fingerprint. Cannot verify dataset compatibility."
            )

        current_fingerprint = dataset_fingerprint(dataset_path)

        if saved_fingerprint != current_fingerprint:
            raise ValueError(
                "Dataset fingerprint mismatch. The dataset has changed "
                "since this report was created. Re-scoring is unsafe."
            )

        selected_tests = load_golden_dataset(dataset_path)

    elif tests is not None:
        print(
            "[WARN] Legacy report has no dataset metadata. "
            "Using the explicitly supplied test set."
        )
        selected_tests = tests

    else:
        fallback_dataset = dataset or "golden"

        if fallback_dataset not in DATASETS:
            raise ValueError(
                f"Unknown fallback dataset: {fallback_dataset!r}."
            )

        print(
            "[WARN] Legacy report has no dataset metadata. "
            f"Using selected dataset: {fallback_dataset}."
        )

        selected_tests = load_golden_dataset(
            DATASETS[fallback_dataset]
        )

    by_id = {
        test["id"]: test
        for test in selected_tests
    }

    results = []

    for entry in report["results"]:
        test = by_id.get(entry["test_id"])

        if test is None:
            print(
                f"[WARN] Test {entry['test_id']} was not found; skipping"
            )
            continue

        final_sql = (
                entry.get("final_sql")
                or entry.get("generated_sql")
        )

        initial_sql = (
                entry.get("initial_sql")
                or final_sql
        )

        first = (
            short_outcome(
                evaluate_candidate(test, initial_sql, executor)
            )
            if initial_sql
            else dict(EMPTY_OUTCOME)
        )

        final = (
            first
            if final_sql == initial_sql
            else short_outcome(
                evaluate_candidate(test, final_sql, executor)
            )
            if final_sql
            else dict(EMPTY_OUTCOME)
        )

        item = {
            "test_id": test["id"],
            "question": test["question"],
            "category": test["category"],
            "initial_sql": initial_sql,
            "final_sql": final_sql,
            "attempts": entry.get("attempts", 1),
            "first_attempt": first,
            "final": final,
        }

        if "deterministic_repair" in entry:
            item["deterministic_repair"] = entry[
                "deterministic_repair"
            ]

        if report.get("quality_repair_enabled") and final_sql:
            item["final_quality"] = validate_sql_quality(
                test["question"],
                final_sql,
            )

        results.append(item)

    return results, summarize(results)


# ============================================================
# Report comparison
# ============================================================

def sign_test_p_value(improved: int, regressed: int) -> float:
    """Exact two-sided sign test."""
    changed = improved + regressed

    if changed == 0:
        return 1.0

    smaller = min(improved, regressed)

    tail = sum(
        math.comb(changed, k)
        for k in range(smaller + 1)
    ) / 2 ** changed

    return min(1.0, 2 * tail)


def compare_reports(
        path_a: Path,
        path_b: Path,
) -> dict[str, Any]:
    """Compare reports question by question."""
    def load(path: Path) -> tuple[dict[str, bool], dict[str, Any]]:
        report = json.loads(path.read_text(encoding="utf-8"))
        verdicts = {}

        for item in report["results"]:
            final = item.get("final")

            if (
                    not isinstance(final, dict)
                    or "execution_match" not in final
            ):
                raise ValueError(
                    f"{path} has no final.execution_match field: "
                    "re-score the report first with --rescore."
                )

            verdicts[item["test_id"]] = bool(
                final["execution_match"]
            )

        return verdicts, report

    first, report_a = load(path_a)
    second, report_b = load(path_b)

    dataset_a = report_a.get("dataset")
    dataset_b = report_b.get("dataset")

    fingerprint_a = report_a.get("dataset_sha256_prefix")
    fingerprint_b = report_b.get("dataset_sha256_prefix")

    metadata_a = bool(dataset_a or fingerprint_a)
    metadata_b = bool(dataset_b or fingerprint_b)

    if metadata_a != metadata_b:
        raise ValueError(
            "Cannot compare reports: dataset metadata is missing "
            "from one report. Re-score both reports with --rescore."
        )

    if metadata_a:
        if not dataset_a or not fingerprint_a:
            raise ValueError(
                f"{path_a} has incomplete dataset metadata."
            )

        if not dataset_b or not fingerprint_b:
            raise ValueError(
                f"{path_b} has incomplete dataset metadata."
            )

        if dataset_a != dataset_b:
            raise ValueError(
                "Cannot compare reports from different datasets: "
                f"{dataset_a!r} != {dataset_b!r}."
            )

        if fingerprint_a != fingerprint_b:
            raise ValueError(
                "Cannot compare reports: dataset fingerprints differ. "
                "The underlying datasets may have changed."
            )

    common = sorted(set(first) & set(second))

    improved = [
        tid for tid in common
        if not first[tid] and second[tid]
    ]

    regressed = [
        tid for tid in common
        if first[tid] and not second[tid]
    ]

    return {
        "compared": len(common),
        "only_in_first": sorted(set(first) - set(second)),
        "only_in_second": sorted(set(second) - set(first)),
        "improved": improved,
        "regressed": regressed,
        "unchanged": len(common) - len(improved) - len(regressed),
        "p_value": sign_test_p_value(
            len(improved),
            len(regressed),
        ),
    }


def print_comparison(result: dict[str, Any]) -> None:
    print(f"Questions compared: {result['compared']}")

    print(
        f"Improved ({len(result['improved'])}): "
        f"{', '.join(result['improved']) or '-'}"
    )

    print(
        f"Regressed ({len(result['regressed'])}): "
        f"{', '.join(result['regressed']) or '-'}"
    )

    print(f"Unchanged: {result['unchanged']}")
    print(f"Sign test: p = {result['p_value']:.4f}")

    if result["only_in_first"] or result["only_in_second"]:
       print("[!] The question sets differ; comparison is incomplete.")

    conclusion = (
       "is statistically significant"
        if result["p_value"] < 0.05
        else "has no statistically significant difference detected"
    )


# ============================================================
# Model generator
# ============================================================

# When the model answers a repair request with the SAME SQL it was told to fix
# (stuck_on_same_sql in reports), optionally ask again with some randomness.
RESAMPLE_TEMPERATURE = float(os.getenv("QUERYPILOT_RESAMPLE_TEMPERATURE", "0.7"))
RESAMPLE_TRIES = 2
RESAMPLE_SEED_BASE = 1000  # fixed seeds keep resampled runs reproducible


def make_generator(model: str, resample_on_repeat: bool = False) -> Generator:
    """Create a generator backed by the selected Ollama model.

    With ``resample_on_repeat`` the generator re-asks (temperature
    RESAMPLE_TEMPERATURE, fixed seeds) up to RESAMPLE_TRIES times when a repair
    answer equals the previous SQL. ``generate.resample_count`` counts those
    extra requests. Off by default, so default runs are unchanged.
    """

    def generate(
            question: str,
            previous_sql: str | None = None,
            error_feedback: str | None = None,
            attempt: int = 0,
    ) -> str:
        context = build_context(question)

        def ask(**sampling: Any) -> str:
            return generate_sql(
                question,
                model=model,
                previous_sql=previous_sql,
                error_feedback=error_feedback,
                attempt=attempt,
                context=context,
                **sampling,
            )

        sql = ask()

        if resample_on_repeat and previous_sql is not None and same_sql(sql, previous_sql):
            for index in range(RESAMPLE_TRIES):
                generate.resample_count += 1
                sql = ask(
                    temperature=RESAMPLE_TEMPERATURE,
                    seed=RESAMPLE_SEED_BASE + attempt * 10 + index,
                )

                if not same_sql(sql, previous_sql):
                    break

        return sql

    generate.resample_count = 0

    return generate


# ============================================================
# Command-line interface
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="QueryPilot: SQL generation evaluation"
    )

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--all-reference",
        action="store_true",
        help="Verify reference queries (no model required).",
    )

    group.add_argument(
        "--all-model",
        action="store_true",
        help="Evaluate the model on the full dataset.",
    )

    group.add_argument(
        "--test-id",
        help="Evaluate the model on one question, e.g. q09.",
    )

    group.add_argument(
        "--rescore",
        metavar="REPORT",
        help="Re-score a saved report without calling the model.",
    )

    group.add_argument(
        "--sql",
        help="Evaluate custom SQL for the question specified by --question-id.",
    )

    group.add_argument(
        "--compare",
        nargs=2,
        metavar=("REPORT_A", "REPORT_B"),
        help="Compare two reports question by question.",
    )

    parser.add_argument(
        "--question-id",
        help="Question ID for --sql.",
    )

    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        default="golden",
        help="Dataset: golden (development), heldout, or heldout_v3 (evaluation only).",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model (default: {DEFAULT_MODEL}).",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=MAX_CORRECTION_RETRIES,
        help="Maximum number of repair attempts per query.",
    )

    parser.add_argument(
        "--oracle-hints",
        action="store_true",
        help="UPPER BOUND: use reference-derived hints.",
    )

    parser.add_argument(
        "--quality-repair",
        action="store_true",
        help=(
            "Enable quality self-correction: retry after execution errors "
            "and heuristic SQL quality-validator failures."
        ),
    )

    parser.add_argument(
        "--no-deterministic-repair",
        action="store_true",
        help="Disable question-specific deterministic SQL repairs.",
    )

    parser.add_argument(
        "--resample-on-repeat",
        action="store_true",
        help=(
            "If a repair answer repeats the previous SQL, ask again with a "
            "higher temperature and a fixed seed (up to 2 extra requests)."
        ),
    )

    parser.add_argument(
        "--report-name",
        metavar="FILE.json",
        help="Report filename in reports/; preserves other runs.",
    )

    args = parser.parse_args()

    try:
        if args.retries < 0:
            raise ValueError("--retries must be >= 0.")

        if args.oracle_hints and args.quality_repair:
            raise ValueError(
                "--oracle-hints and --quality-repair are separate modes "
                "and cannot be used together."
            )
        if (
                args.no_deterministic_repair
                and not args.quality_repair
        ):
            raise ValueError(
               "--no-deterministic-repair requires --quality-repair."
            )

        dataset_path = DATASETS[args.dataset]

        # Compare two existing reports.
        if args.compare:
            print_comparison(
                compare_reports(
                    Path(args.compare[0]),
                    Path(args.compare[1]),
                )
            )
            return 0

        # Run reference tests without a model.
        if args.all_reference:
            results = run_reference_tests(path=dataset_path)

            return 0 if all(
                item["passed"] for item in results
            ) else 1

        # Re-score an existing report without calling the model.
        if args.rescore:
            results, summary = rescore_report(
                Path(args.rescore),
                dataset=args.dataset,
            )

            print_summary(
                summary,
                f"Re-scoring report {args.rescore}",
            )

            return 0

        # Evaluate custom SQL for a single question.
        if args.sql:
            if not args.question_id:
                parser.error("--sql requires --question-id.")

            test = next(
                (
                    item for item in load_golden_dataset(dataset_path)
                    if item["id"] == args.question_id
                ),
                None,
            )

            if test is None:
                raise ValueError(
                    f"Question {args.question_id!r} was not found."
                )

            outcome = evaluate_candidate(test, args.sql)

            print(
                json.dumps(
                    outcome,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

            return 0 if outcome["execution_match"] else 1

        # Load the selected dataset.
        tests = load_golden_dataset(dataset_path)

        if args.dataset == "heldout":
            created_with = load_dataset_metadata(
                dataset_path
            ).get("created_with_prompt_sha256_prefix")

            current = prompt_fingerprint()

            print(
                "[heldout] The prompt matches the version used to create "
                "the questions."
                if created_with == current
                else (
                    "[heldout] The prompt changed after the questions "
                    f"were created ({created_with} -> {current}). "
                    "Record the prompt version with the results."
                )
            )

        # Select one question if --test-id was provided.
        if args.test_id:
            tests = [
                item for item in tests
                if item["id"] == args.test_id
            ]

            if not tests:
                raise ValueError(
                    f"Question {args.test_id!r} was not found."
                )

        if args.oracle_hints:
            print(
                "[!] ORACLE-HINT MODE. "
                "This is an upper bound, not system accuracy."
            )

        if args.quality_repair:
            print(
                "[!] QUALITY SELF-CORRECTION MODE. "
                "Feedback uses execution errors and heuristic quality "
                "checks, not reference results."
            )

        generator = make_generator(args.model, resample_on_repeat=args.resample_on_repeat)

        # Run model evaluation.
        results, summary = run_evaluation(
            tests,
            generator,
            retries=args.retries,
            oracle=args.oracle_hints,
            quality_repair=args.quality_repair,
            deterministic_repairs=not args.no_deterministic_repair,
            checkpoint=lambda current_results, current_summary: save_report(
                args.model,
                args.oracle_hints,
                args.retries,
                current_results,
                current_summary,
                partial=True,
                dataset=args.dataset,
                report_name=args.report_name,
                quality_repair=args.quality_repair,
                deterministic_repairs=not args.no_deterministic_repair,
                resample_on_repeat=args.resample_on_repeat,
            ),
        )

        if args.resample_on_repeat:
            print(f"[resample] extra model requests after a repeated SQL: {generator.resample_count}")

        if args.oracle_hints:
            mode_title = "with reference hints (UPPER BOUND)"

        elif args.quality_repair:
            mode_title = "quality self-correction"

        else:
            mode_title = (
                "baseline (repair only after execution errors)"
            )

        print_summary(
            summary,
            f"{args.model}: {mode_title}",
        )

        # Save partial runs separately.
        partial = bool(args.test_id)

        report_path = save_report(
            args.model,
            args.oracle_hints,
            args.retries,
            results,
            summary,
            partial=partial,
            dataset=args.dataset,
            report_name=args.report_name,
            quality_repair=args.quality_repair,
            deterministic_repairs=not args.no_deterministic_repair,
            resample_on_repeat=args.resample_on_repeat,
        )

        print(f"\nReport: {report_path}")

        if partial:
            print(
                "(Partial run: the main report in reports/ "
                "was not overwritten.)"
            )

        return 0

    except (
            FileNotFoundError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
            OSError,
    ) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())