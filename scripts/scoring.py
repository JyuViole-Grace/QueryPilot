"""Compare query results with the reference.

Three metrics, from strictest to most permissive:

strict           - column names and rows match (row order is considered
                   when order_sensitive is enabled in the dataset).
execution_match  - the primary metric (EX). Column names are ignored because
                   the model cannot infer an alias that is not specified in the question.
                   Row order matters only when it is part of the meaning
                   of the question (see order_required).
lenient          - like EX, but allows extra columns and a different column order
                   provided the reference values can be found
                   among the returned columns.
relaxed          - like lenient, but also (a) treats floats as equal within
                   RELAXED_FLOAT_TOLERANCE, because a question rarely states
                   a rounding precision, and (b) lets the model omit reference
                   identifier columns (``*_id``) when the question does not
                   ask for IDs. It never forgives wrong rows, wrong values
                   or missing non-identifier columns.

``relaxed`` was introduced after a manual review of heldout_v3 failures
(see README, "Benchmark status"). Treat it as a development metric until it
is confirmed on a fresh set; ``execution_match`` stays the headline metric.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from itertools import combinations, permutations
from typing import Any, Iterable

# Very wide results have too many column combinations to check.
MAX_COLUMNS_FOR_SUBSET = 8

# Floats within this distance are equal under the relaxed metric. It covers
# ROUND(x, 2) in the reference versus an unrounded value from the model.
RELAXED_FLOAT_TOLERANCE = 0.0051

# A question that mentions IDs requires the identifier columns.
ID_REQUEST_REGEX = re.compile(r"\b(?:ids?|identifiers?)\b", re.IGNORECASE)

# Bound the subset search over optional identifier columns.
MAX_OPTIONAL_ID_COLUMNS = 3

# English phrases indicating that row order matters.
# Use whole-word patterns to avoid confusing a time period with a top-N request.
ORDER_PATTERNS = (
    r"\bsort(?:ed|ing)?\b",
    r"\b(?:ascending|descending)\b",
    r"\btop\s+\d+\b",
    r"\b(?:first|last)\s+\d+\b",
    r"\b(?:highest|lowest)\b",
    r"\b(?:most expensive|least expensive|cheapest|most recent|most recently|latest|earliest)\b",
)
ORDER_REGEX = re.compile("|".join(ORDER_PATTERNS), re.IGNORECASE)


def normalize_value(value: Any) -> Any:
    """Normalize a value for comparison."""
    if isinstance(value, float):
        return round(value, 8)

    return value


def normalize_rows(rows: Iterable[Iterable[Any]]) -> list[tuple[Any, ...]]:
    return [tuple(normalize_value(value) for value in row) for row in rows]


def rows_equal(
        actual: Iterable[Iterable[Any]],
        expected: Iterable[Iterable[Any]],
        ordered: bool,
) -> bool:
    """Compare row collections as lists or multisets, depending on order sensitivity."""
    actual_rows = normalize_rows(actual)
    expected_rows = normalize_rows(expected)

    if len(actual_rows) != len(expected_rows):
        return False

    if ordered:
        return actual_rows == expected_rows

    return Counter(actual_rows) == Counter(expected_rows)


def order_required(test: dict[str, Any]) -> bool:
    """Determine whether row order is part of the question meaning.

    An explicit order_required field takes precedence. Otherwise, order matters
    if the reference uses LIMIT (top-N) or the question explicitly requests sorting.
    """
    if "order_required" in test:
        return bool(test["order_required"])

    has_limit = re.search(r"\bLIMIT\b", test.get("reference_sql", ""), re.IGNORECASE)
    question = test.get("question", "").lower()

    return bool(has_limit) or ORDER_REGEX.search(question) is not None


def expected_rows(test: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Convert reference rows to tuples ordered by expected_columns."""
    columns = test["expected_columns"]

    return [
        tuple(row[column] for column in columns)
        for row in test["expected_result"]
    ]


def columns_subset_match(
        actual_columns: list[str],
        actual_rows: list[tuple[Any, ...]],
        expected: list[tuple[Any, ...]],
        ordered: bool,
) -> bool:
    """Check whether returned columns contain the reference column set."""
    wanted = len(expected[0]) if expected else 0
    available = len(actual_columns)

    if wanted == 0 or available < wanted or available > MAX_COLUMNS_FOR_SUBSET:
        return False

    if len(actual_rows) != len(expected):
        return False

    for chosen in permutations(range(available), wanted):
        projected = [tuple(row[index] for index in chosen) for row in actual_rows]

        if rows_equal(projected, expected, ordered):
            return True

    return False


def question_requests_ids(question: str) -> bool:
    """Return True if the question explicitly asks for IDs or identifiers."""
    return ID_REQUEST_REGEX.search(question or "") is not None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def values_close(first: Any, second: Any, tolerance: float) -> bool:
    """Equal values, or floats within the tolerance."""
    if first == second:
        return True

    if _is_number(first) and _is_number(second) and (
            isinstance(first, float) or isinstance(second, float)
    ):
        if math.isnan(first) or math.isnan(second):
            return False

        return abs(first - second) <= tolerance

    return False


def _rows_close(
        first: tuple[Any, ...],
        second: tuple[Any, ...],
        tolerance: float,
) -> bool:
    return len(first) == len(second) and all(
        values_close(a, b, tolerance) for a, b in zip(first, second)
    )


def rows_close(
        actual: list[tuple[Any, ...]],
        expected: list[tuple[Any, ...]],
        ordered: bool,
        tolerance: float = RELAXED_FLOAT_TOLERANCE,
) -> bool:
    """Compare rows with a float tolerance, as lists or as multisets."""
    if len(actual) != len(expected):
        return False

    if ordered:
        return all(
            _rows_close(a, b, tolerance) for a, b in zip(actual, expected)
        )

    # Fast path: exact multiset equality.
    if rows_equal(actual, expected, ordered=False):
        return True

    unmatched = list(expected)

    for row in actual:
        for index, candidate in enumerate(unmatched):
            if _rows_close(row, candidate, tolerance):
                del unmatched[index]
                break
        else:
            return False

    return True


def relaxed_match(
        test: dict[str, Any],
        actual_columns: list[str],
        actual_rows: list[tuple[Any, ...]],
) -> bool:
    """Relaxed comparison: float tolerance and optional identifier columns."""
    expected = expected_rows(test)
    rows = [tuple(row) for row in actual_rows]

    if len(rows) != len(expected):
        return False

    if not expected:
        return True

    ordered = order_required(test)
    reference_columns = list(test["expected_columns"])
    width = len(reference_columns)
    available = len(actual_columns)

    if available == 0 or available > MAX_COLUMNS_FOR_SUBSET:
        return False

    optional: list[int] = []

    if not question_requests_ids(test.get("question", "")):
        optional = [
            index
            for index, name in enumerate(reference_columns)
            if name.casefold() == "id" or name.casefold().endswith("_id")
        ][:MAX_OPTIONAL_ID_COLUMNS]

    for dropped_count in range(len(optional) + 1):
        for dropped in combinations(optional, dropped_count):
            kept = [index for index in range(width) if index not in dropped]

            if not kept or len(kept) > available:
                continue

            target = [tuple(row[index] for index in kept) for row in expected]

            for chosen in permutations(range(available), len(kept)):
                projected = [tuple(row[index] for index in chosen) for row in rows]

                if rows_close(projected, target, ordered):
                    return True

    return False


def compare(
        test: dict[str, Any],
        actual_columns: list[str],
        actual_rows: list[tuple[Any, ...]],
) -> dict[str, bool]:
    """Return strict, execution_match, lenient, relaxed, and columns_match flags."""
    expected = expected_rows(test)
    expected_columns = list(test["expected_columns"])

    columns_match = list(actual_columns) == expected_columns
    strict_ordered = bool(test.get("order_sensitive", False))
    ordered = order_required(test)

    strict = columns_match and rows_equal(actual_rows, expected, strict_ordered)
    execution_match = rows_equal(actual_rows, expected, ordered)
    lenient = execution_match or columns_subset_match(
        list(actual_columns),
        normalize_rows(actual_rows),
        normalize_rows(expected),
        ordered,
    )

    relaxed = lenient or relaxed_match(test, list(actual_columns), actual_rows)

    return {
        "strict": strict,
        "execution_match": execution_match,
        "lenient": lenient,
        "relaxed": relaxed,
        "columns_match": columns_match,
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Calculate the 95% Wilson confidence interval for a proportion.

    With 30 questions, the interval is wide; a difference of one or two questions
    (about 3–7 percentage points) may be noise.
    """
    if total <= 0:
        return 0.0, 0.0

    share = successes / total
    denominator = 1 + z * z / total
    center = (share + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        share * (1 - share) / total + z * z / (4 * total * total)
    ) / denominator

    return max(0.0, center - margin), min(1.0, center + margin)
