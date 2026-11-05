"""Build and validate the heldout_v4 question set.

heldout_v4 exists to be run ONCE per release and never tuned against. Every
question is validated mechanically before it is written, so the defects found
in heldout_v3 cannot be repeated:

1. the reference SQL executes under the read-only safety layer and returns
   1..MAX_EXPECTED_ROWS rows (no empty or huge results);
2. if the question does not ask for IDs, the reference returns no ``*_id``
   column; if the result contains a float, the question says it is rounded
   and the reference SQL uses ROUND;
3. when row order matters, the sort key is unique, including at the top-N
   boundary;
4. every question that lists ``wrong`` SQL variants (plausible mistakes such as
   a fan-out join or ``!=`` instead of NOT EXISTS) is proven to discriminate:
   each variant must be REJECTED by both execution match and the relaxed
   metric. At least MIN_DISCRIMINATING_SHARE of the questions must have one;
5. no question or reference duplicates one from another dataset.

Authorship note: this set was written by an AI assistant (Claude) on
3 Nov 2026, after reviewing the failures of heldout_v3. It targets common
Text-to-SQL pitfalls, not the exact heldout_v3 questions, but it is not
authored blind. Its score is meaningful only if nothing is tuned afterwards.

Run:    python scripts/build_heldout_v4.py          (writes tests/heldout_v4_questions.json)
Check:  python scripts/build_heldout_v4.py --check  (fails if the file is stale)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from build_heldout_dataset import (
    MAX_EXPECTED_ROWS,
    check_order_is_unambiguous,
    execute_reference_query,
)
from heldout_v4_specs import SPECS
from scoring import compare, order_required, question_requests_ids

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"
OUTPUT_PATH = PROJECT_ROOT / "tests" / "heldout_v4_questions.json"
OTHER_DATASETS = ("golden_questions.json", "heldout_questions.json", "heldout_v3_questions.json")

MIN_QUESTIONS = 100
MIN_DISCRIMINATING_SHARE = 0.6
MAX_SIMILARITY = 0.7

INDEPENDENCE_NOTE = (
    "Evaluation questions for a single clean run. Do not use this set for "
    "prompt, validator or repair tuning; if you do, retire it and write a new set."
)
AUTHORSHIP_NOTE = (
    "Written by an AI assistant (Claude) on 2026-11-03 after reviewing the "
    "failures of heldout_v3. Reference SQL and wrong-answer variants are "
    "validated mechanically by scripts/build_heldout_v4.py."
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _run(connection: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    cursor = connection.execute(sql)
    return [c[0] for c in cursor.description], [tuple(r) for r in cursor.fetchall()]


def build_tests(connection: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (tests, problems). ``problems`` is empty for a valid set."""
    problems: list[str] = []
    tests: list[dict[str, Any]] = []
    discriminating = 0

    for number, spec in enumerate(SPECS, start=1):
        test_id = f"v4_{number:03d}"
        sql = spec["sql"].strip()
        columns, rows = execute_reference_query(connection, sql)

        test: dict[str, Any] = {
            "id": test_id,
            "question": spec["question"],
            "category": spec["category"],
            "reference_sql": sql,
            "expected_columns": columns,
            "expected_result": rows,
        }

        if "order_key" in spec:
            test["order_key"] = spec["order_key"]

        test["order_sensitive"] = order_required(test)

        if not rows:
            problems.append(f"{test_id}: empty result")

        if len(rows) > MAX_EXPECTED_ROWS:
            problems.append(f"{test_id}: result too large ({len(rows)} rows)")

        if len(set(columns)) != len(columns):
            problems.append(f"{test_id}: duplicate output column names")

        for problem in check_order_is_unambiguous(connection, test):
            problems.append(f"{test_id}: {problem}")

        if not question_requests_ids(spec["question"]):
            ids = [c for c in columns if c.lower() == "id" or c.lower().endswith("_id")]
            if ids:
                problems.append(f"{test_id}: returns {ids} but the question does not ask for IDs")

        has_float = any(isinstance(v, float) for row in rows for v in row.values())
        if has_float and not (
            "rounded to two decimals" in spec["question"].lower()
            and re.search(r"\bROUND\s*\(", sql, re.IGNORECASE)
        ):
            problems.append(f"{test_id}: float result without 'rounded to two decimals' + ROUND")

        # The reference must satisfy every metric against itself.
        flags = compare(test, columns, [tuple(row[c] for c in columns) for row in rows])
        if not all(flags.values()):
            problems.append(f"{test_id}: reference does not match itself under the metrics: {flags}")

        wrong_variants = spec.get("wrong", [])
        accepted = []

        for index, wrong_sql in enumerate(wrong_variants, start=1):
            try:
                wrong_columns, wrong_rows = _run(connection, wrong_sql)
            except sqlite3.Error as exc:
                problems.append(f"{test_id}: wrong[{index}] does not execute: {exc}")
                continue

            result = compare(test, wrong_columns, wrong_rows)
            if result["execution_match"] or result["relaxed"]:
                accepted.append(index)

        if accepted:
            problems.append(f"{test_id}: wrong variant(s) {accepted} are accepted by the metric; question does not discriminate")

        if wrong_variants and not accepted:
            discriminating += 1
            test["common_wrong_sql"] = [w.strip() for w in wrong_variants]

        tests.append(test)

    if len(tests) < MIN_QUESTIONS:
        problems.append(f"only {len(tests)} questions, need {MIN_QUESTIONS}")

    share = discriminating / len(tests) if tests else 0.0
    if share < MIN_DISCRIMINATING_SHARE:
        problems.append(
            f"only {discriminating}/{len(tests)} questions have a verified wrong variant "
            f"(need {MIN_DISCRIMINATING_SHARE:.0%})"
        )

    problems.extend(_cross_dataset_problems(tests))
    return tests, problems


def _cross_dataset_problems(tests: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    seen_questions: set[str] = set()
    seen_sql: set[str] = set()

    for test in tests:
        q, s = _squash(test["question"]), _squash(test["reference_sql"])
        if q in seen_questions:
            problems.append(f"{test['id']}: duplicate question inside v4")
        if s in seen_sql:
            problems.append(f"{test['id']}: duplicate reference SQL inside v4")
        seen_questions.add(q)
        seen_sql.add(s)

    tests_dir = PROJECT_ROOT / "tests"

    for name in OTHER_DATASETS:
        path = tests_dir / name
        if not path.exists():
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        others = data["tests"] if isinstance(data, dict) else data

        for test in tests:
            for other in others:
                if _squash(test["reference_sql"]) == _squash(other["reference_sql"]):
                    problems.append(f"{test['id']}: reference SQL identical to {name}:{other['id']}")

                a, b = _words(test["question"]), _words(other["question"])
                if a and b and len(a & b) / len(a | b) >= MAX_SIMILARITY:
                    problems.append(f"{test['id']}: question nearly duplicates {name}:{other['id']}")

    return problems


def build_document(tests: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for test in tests:
        counts[test["category"]] = counts.get(test["category"], 0) + 1

    return {
        "project": "QueryPilot",
        "role": "heldout",
        "version": 4,
        "database": "SQLite",
        "language": "en",
        "data_edition": "english",
        "test_count": len(tests),
        "database_sha256": hashlib.sha256(DATABASE_PATH.read_bytes()).hexdigest(),
        "created_with_prompt_sha256_prefix": None,
        "independence_note": INDEPENDENCE_NOTE,
        "authorship_note": AUTHORSHIP_NOTE,
        "category_counts": dict(sorted(counts.items())),
        "tests": tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the JSON on disk is stale")
    args = parser.parse_args()

    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)

    try:
        tests, problems = build_tests(connection)
    finally:
        connection.close()

    if problems:
        print("heldout_v4 validation failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    text = json.dumps(build_document(tests), ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != text:
            print("tests/heldout_v4_questions.json is stale; rerun build_heldout_v4.py", file=sys.stderr)
            return 1
        print(f"OK: {len(tests)} questions, file is up to date.")
        return 0

    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {len(tests)} questions -> {OUTPUT_PATH}")
    for name, count in sorted(build_document(tests)["category_counts"].items()):
        print(f"  {name:28} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
