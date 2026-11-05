"""Guarantees for heldout_v4, the set meant to be run once and never tuned on."""

import hashlib
import json
import sqlite3

import build_heldout_v4 as builder
import evaluate_sql as ev
from build_heldout_dataset import check_order_is_unambiguous
from sql_safety import DATABASE_PATH


def load():
    return ev.load_golden_dataset(ev.HELDOUT_V4_PATH)


def test_dataset_is_registered_and_large_enough():
    assert ev.DATASETS["heldout_v4"] == ev.HELDOUT_V4_PATH

    tests = load()
    ids = [t["id"] for t in tests]

    assert len(tests) >= 100
    assert len(ids) == len(set(ids))
    assert len({t["category"] for t in tests}) >= 8


def test_metadata_describes_an_untuned_set_and_matches_the_database():
    metadata = ev.load_dataset_metadata(ev.HELDOUT_V4_PATH)

    assert metadata["role"] == "heldout" and metadata["version"] == 4
    assert "Do not use this set" in metadata["independence_note"]
    assert "Claude" in metadata["authorship_note"]
    assert metadata["database_sha256"] == hashlib.sha256(DATABASE_PATH.read_bytes()).hexdigest(), (
        "The database changed after heldout_v4 was built; rebuild the set or restore the database."
    )


def test_every_reference_reproduces_its_expected_result():
    for test in load():
        outcome = ev.evaluate_candidate(test, test["reference_sql"])

        assert outcome["executed"], f"{test['id']}: {outcome['error']}"
        assert outcome["strict"] and outcome["relaxed"], test["id"]


def test_every_recorded_wrong_answer_is_rejected_by_the_metrics():
    checked = 0

    for test in load():
        for wrong_sql in test.get("common_wrong_sql", []):
            outcome = ev.evaluate_candidate(test, wrong_sql)

            assert outcome["executed"], test["id"]
            assert not outcome["execution_match"], f"{test['id']}: wrong SQL passes EX"
            assert not outcome["relaxed"], f"{test['id']}: wrong SQL passes relaxed"
            checked += 1

    assert checked >= 90


def test_most_questions_are_proven_to_discriminate():
    tests = load()
    share = sum(1 for t in tests if t.get("common_wrong_sql")) / len(tests)

    assert share >= builder.MIN_DISCRIMINATING_SHARE


def test_results_are_neither_empty_nor_huge_and_order_is_unambiguous():
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)

    try:
        for test in load():
            assert 0 < len(test["expected_result"]) <= builder.MAX_EXPECTED_ROWS, test["id"]
            assert check_order_is_unambiguous(connection, test) == [], test["id"]
    finally:
        connection.close()


def test_the_json_file_is_exactly_what_the_builder_produces():
    """Fails when the specs, the database or the validation rules changed without a rebuild."""
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)

    try:
        tests, problems = builder.build_tests(connection)
    finally:
        connection.close()

    assert problems == []

    expected_text = json.dumps(builder.build_document(tests), ensure_ascii=False, indent=2) + "\n"
    assert builder.OUTPUT_PATH.read_text(encoding="utf-8") == expected_text


def test_validation_rejects_bad_specs():
    """The builder's own rules must actually bite."""
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    original = list(builder.SPECS)

    try:
        builder.SPECS[:] = [
            # unrequested ID column
            {"category": "t", "question": "Show the products.", "sql": "SELECT product_id, name FROM products"},
            # float without 'rounded to two decimals' and ROUND
            {"category": "t", "question": "What is the average price?", "sql": "SELECT AVG(price_cents) AS a FROM products"},
            # wrong variant that gives the same answer: question does not discriminate
            {"category": "t", "question": "How many products are there?",
             "sql": "SELECT COUNT(*) AS n FROM products",
             "wrong": ["SELECT COUNT(product_id) AS n FROM products"]},
            # empty result
            {"category": "t", "question": "Which products cost less than zero cents?",
             "sql": "SELECT name FROM products WHERE price_cents < 0"},
        ]
        _, problems = builder.build_tests(connection)
    finally:
        builder.SPECS[:] = original
        connection.close()

    text = "\n".join(problems)

    assert "does not ask for IDs" in text
    assert "ROUND" in text
    assert "does not discriminate" in text
    assert "empty result" in text
