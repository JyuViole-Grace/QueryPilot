"""Validate both golden and heldout datasets against the real database."""

import re
import sqlite3

import evaluate_sql as ev
from build_heldout_dataset import MAX_EXPECTED_ROWS, check_order_is_unambiguous
from helpers import make_db
from scoring import order_required
from sql_safety import DATABASE_PATH, is_read_query

DATASETS = {"golden": ev.GOLDEN_PATH, "heldout": ev.HELDOUT_PATH}
MAX_QUESTION_SIMILARITY = 0.7


def load(name):
    return ev.load_golden_dataset(DATASETS[name])


def words(text):
    return set(re.findall(r"\w+", text.lower()))


def squash(sql):
    return " ".join(sql.lower().split())


def test_the_database_file_exists():
    assert DATABASE_PATH.exists()


def test_each_dataset_has_unique_ids_categories_and_enough_questions():
    for name in DATASETS:
        tests = load(name)
        ids = [test["id"] for test in tests]

        assert len(ids) == len(set(ids)), name
        assert all(test["category"] for test in tests), name
        assert len(tests) >= 30, name


def test_every_reference_query_is_read_only_and_reproduces_its_expected_result():
    for name in DATASETS:
        for test in load(name):
            assert is_read_query(test["reference_sql"]), test["id"]

            outcome = ev.evaluate_candidate(test, test["reference_sql"])

            assert outcome["executed"], f"{test['id']}: {outcome['error']}"
            assert outcome["strict"], f"{test['id']}: reference SQL does not reproduce the expected result"


def test_expected_columns_match_the_stored_rows():
    for name in DATASETS:
        for test in load(name):
            for row in test["expected_result"]:
                assert set(row) == set(test["expected_columns"]), test["id"]


def test_questions_that_require_an_order_have_a_deterministic_reference():
    """When order matters, reference SQL must include ORDER BY to make it deterministic."""
    for name in DATASETS:
        required = [test for test in load(name) if order_required(test)]

        assert required, name

        for test in required:
            assert re.search(r"\bORDER\s+BY\b", test["reference_sql"], re.IGNORECASE), test["id"]


# ---------------- heldout dataset: additional guarantees ----------------

def test_heldout_does_not_overlap_the_golden_set():
    golden, heldout = load("golden"), load("heldout")

    assert not {t["id"] for t in golden} & {t["id"] for t in heldout}
    assert not {squash(t["question"]) for t in golden} & {squash(t["question"]) for t in heldout}
    assert not {squash(t["reference_sql"]) for t in golden} & {squash(t["reference_sql"]) for t in heldout}

    for new in heldout:
        for old in golden:
            overlap = words(new["question"]) & words(old["question"])
            similarity = len(overlap) / len(words(new["question"]) | words(old["question"]))

            assert similarity < MAX_QUESTION_SIMILARITY, (
                f"{new['id']} nearly duplicates {old['id']} (similarity {similarity:.2f})")


def test_heldout_covers_every_golden_category():
    golden = {test["category"] for test in load("golden")}
    heldout = {test["category"] for test in load("heldout")}

    assert golden <= heldout


def test_heldout_results_are_neither_empty_nor_huge():
    for test in load("heldout"):
        assert 0 < len(test["expected_result"]) <= MAX_EXPECTED_ROWS, test["id"]


def test_heldout_order_is_fully_determined_by_the_question():
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)

    try:
        for test in load("heldout"):
            assert check_order_is_unambiguous(connection, test) == [], test["id"]
    finally:
        connection.close()


def test_heldout_strict_order_flag_follows_the_question_not_a_blanket_default():
    for test in load("heldout"):
        assert test["order_sensitive"] == order_required(test), test["id"]


def test_heldout_records_the_prompt_version_it_was_created_with():
    metadata = ev.load_dataset_metadata(ev.HELDOUT_PATH)

    assert metadata["role"] == "heldout"
    assert len(metadata["created_with_prompt_sha256_prefix"]) == 16


def test_the_ambiguity_checker_catches_ties_and_accepts_unique_keys():
    connection = sqlite3.connect(make_db())

    try:
        ties = {"question": "Show 2 cities", "reference_sql":
                "SELECT city FROM customers ORDER BY city LIMIT 2", "order_key": ["city"]}
        unique = {"question": "Show 2 customers", "reference_sql":
                  "SELECT id, name FROM customers ORDER BY id LIMIT 2", "order_key": ["id"]}
        no_key = {"question": "Show 2 customers", "reference_sql":
                  "SELECT id FROM customers ORDER BY id LIMIT 2"}
        wrong_key = dict(unique, order_key=["missing"])
        unordered = {"question": "How many customers?", "reference_sql": "SELECT COUNT(*) FROM customers"}

        assert check_order_is_unambiguous(connection, ties)       # Lviv appears at the boundary
        assert check_order_is_unambiguous(connection, unique) == []
        assert check_order_is_unambiguous(connection, no_key)
        assert check_order_is_unambiguous(connection, wrong_key)
        assert check_order_is_unambiguous(connection, unordered) == []
    finally:
        connection.close()
