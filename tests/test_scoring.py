from helpers import make_test
from scoring import MAX_COLUMNS_FOR_SUBSET, compare, order_required, rows_equal, wilson_interval

ROWS = [("Lviv", 2), ("Kyiv", 1)]


def test_identical_result_passes_every_metric():
    outcome = compare(make_test(), ["city", "customer_count"], ROWS)

    assert outcome["strict"] and outcome["execution_match"] and outcome["lenient"]
    assert outcome["columns_match"]


def test_alias_difference_fails_only_the_strict_metric():
    outcome = compare(make_test(), ["city", "n"], ROWS)

    assert outcome["strict"] is False
    assert outcome["columns_match"] is False
    assert outcome["execution_match"] is True


def test_row_order_is_ignored_when_the_question_does_not_ask_for_it():
    test = make_test(order_sensitive=False)

    assert compare(test, ["city", "customer_count"], list(reversed(ROWS)))["execution_match"]


def test_row_order_matters_for_top_n_questions():
    test = make_test(
        question="Show the first 2 cities",
        reference_sql="SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city ORDER BY 2 DESC LIMIT 2",
    )

    assert compare(test, ["city", "customer_count"], ROWS)["execution_match"]
    assert not compare(test, ["city", "customer_count"], list(reversed(ROWS)))["execution_match"]


def test_wrong_values_fail_everything():
    outcome = compare(make_test(), ["city", "customer_count"], [("Lviv", 3), ("Kyiv", 1)])

    assert not outcome["strict"] and not outcome["execution_match"] and not outcome["lenient"]


def test_duplicates_are_counted():
    test = make_test(
        expected_columns=["x"], expected_result=[{"x": 1}, {"x": 1}], reference_sql="SELECT 1",
    )

    assert compare(test, ["x"], [(1,), (1,)])["execution_match"]
    assert not compare(test, ["x"], [(1,)])["execution_match"]
    assert not compare(test, ["x"], [(1,), (1,), (1,)])["execution_match"]


def test_floats_are_compared_with_rounding_and_none_is_supported():
    test = make_test(
        expected_columns=["avg"], expected_result=[{"avg": 0.1 + 0.2}, {"avg": None}], reference_sql="SELECT 1",
    )

    assert compare(test, ["avg"], [(0.3,), (None,)])["execution_match"]
    assert not compare(test, ["avg"], [(0.3,), (0,)])["execution_match"]


def test_lenient_accepts_extra_and_reordered_columns_but_ex_does_not():
    extra = compare(make_test(), ["city", "name", "customer_count"], [("Lviv", "A", 2), ("Kyiv", "B", 1)])
    assert extra["lenient"] and not extra["execution_match"]

    swapped = compare(make_test(), ["customer_count", "city"], [(2, "Lviv"), (1, "Kyiv")])
    assert swapped["lenient"] and not swapped["execution_match"]


def test_lenient_still_rejects_missing_columns_and_wrong_data():
    assert not compare(make_test(), ["city"], [("Lviv",), ("Kyiv",)])["lenient"]
    assert not compare(make_test(), ["city", "extra", "customer_count"], [("Lviv", "A", 9), ("Kyiv", "B", 1)])["lenient"]


def test_lenient_gives_up_on_very_wide_results():
    width = MAX_COLUMNS_FOR_SUBSET + 1
    columns = [f"c{i}" for i in range(width)]
    rows = [tuple([("Lviv", 2)[0], 2] + [0] * (width - 2)), tuple(["Kyiv", 1] + [0] * (width - 2))]

    assert not compare(make_test(), columns, rows)["lenient"]


def test_empty_results_match_each_other():
    test = make_test(expected_result=[])

    assert compare(test, ["city", "customer_count"], [])["execution_match"]
    assert not compare(test, ["city", "customer_count"], [("Lviv", 2)])["execution_match"]


def test_order_required_rules():
    assert order_required(make_test(reference_sql="SELECT 1 FROM t ORDER BY a LIMIT 5"))
    assert order_required(make_test(question="Show the first 10 orders"))
    assert order_required(make_test(question="Sort products by price"))
    assert not order_required(make_test(question="How many orders are there for each status?"))
    assert not order_required(make_test(reference_sql="SELECT 1 FROM t ORDER BY a"))  # ORDER BY without LIMIT

    # An explicit field takes precedence over heuristics
    assert not order_required(make_test(question="Show the first 10", order_required=False))
    assert order_required(make_test(question="How many?", order_required=True))


def test_rows_equal_directly():
    assert rows_equal([(1,), (2,)], [(2,), (1,)], ordered=False)
    assert not rows_equal([(1,), (2,)], [(2,), (1,)], ordered=True)
    assert not rows_equal([(1,)], [(1,), (1,)], ordered=False)


def test_order_keywords_are_whole_words_not_substrings():
    assert not order_required(make_test(question="How many orders were placed in the first quarter of 2026?"))
    assert order_required(make_test(question="Show the first 10 orders"))
    assert order_required(make_test(question="Show the 5 most recent deliveries"))
    assert order_required(make_test(question="Show products in descending price order"))
    assert not order_required(make_test(question="How many orders are there for each status?"))


def test_wilson_interval_known_values_and_edges():
    low, high = wilson_interval(16, 30)
    assert abs(low - 0.3614) < 0.001 and abs(high - 0.6977) < 0.001
    assert low < 16 / 30 < high

    assert wilson_interval(0, 30)[0] == 0.0
    assert abs(wilson_interval(0, 30)[1] - 0.1135) < 0.001
    assert wilson_interval(30, 30)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_interval_narrows_with_more_questions():
    narrow = wilson_interval(160, 300)
    wide = wilson_interval(16, 30)

    assert narrow[1] - narrow[0] < wide[1] - wide[0]


# ---------------------------------------------------------------------------
# relaxed metric
# ---------------------------------------------------------------------------

def _ratings_test(**overrides):
    return make_test(
        question="Show supplier names and average ratings.",
        expected_columns=["supplier_name", "average_rating"],
        expected_result=[
            {"supplier_name": "A", "average_rating": 4.63},
            {"supplier_name": "B", "average_rating": 4.52},
        ],
        order_sensitive=False,
        **overrides,
    )


def test_relaxed_forgives_rounding_that_the_question_did_not_specify():
    rows = [("A", 4.625), ("B", 4.5238095)]
    outcome = compare(_ratings_test(), ["name", "avg"], rows)

    assert not outcome["execution_match"]
    assert outcome["relaxed"]


def test_relaxed_still_rejects_wrong_values():
    rows = [("A", 4.2), ("B", 4.52)]
    assert not compare(_ratings_test(), ["name", "avg"], rows)["relaxed"]


def test_relaxed_does_not_forgive_integer_differences():
    test = make_test()
    rows = [("Lviv", 3), ("Kyiv", 1)]  # reference: Lviv 2
    assert not compare(test, ["city", "customer_count"], rows)["relaxed"]


def _ids_test(question):
    return make_test(
        question=question,
        expected_columns=["customer_id", "full_name"],
        expected_result=[
            {"customer_id": 1, "full_name": "Anna"},
            {"customer_id": 2, "full_name": "Boris"},
        ],
    )


def test_relaxed_lets_the_model_omit_ids_the_question_did_not_ask_for():
    test = _ids_test("Which customers placed orders? Show their names.")
    outcome = compare(test, ["full_name"], [("Anna",), ("Boris",)])

    assert not outcome["lenient"]
    assert outcome["relaxed"]


def test_relaxed_requires_ids_when_the_question_asks_for_them():
    test = _ids_test("Which customers placed orders? Show their IDs and names.")
    outcome = compare(test, ["full_name"], [("Anna",), ("Boris",)])

    assert not outcome["relaxed"]


def test_relaxed_never_forgives_a_missing_non_id_column():
    test = make_test()
    outcome = compare(test, ["city"], [("Lviv",), ("Kyiv",)])

    assert not outcome["relaxed"]


def test_relaxed_respects_row_order_when_order_matters():
    test = make_test(question="Show the top 2 cities by customer count.")
    rows = [("Kyiv", 1), ("Lviv", 2)]

    assert not compare(test, ["city", "customer_count"], rows)["relaxed"]
    assert compare(test, ["city", "customer_count"], list(reversed(rows)))["relaxed"]


def test_execution_match_always_implies_relaxed():
    outcome = compare(make_test(), ["city", "customer_count"], [("Lviv", 2), ("Kyiv", 1)])
    assert outcome["execution_match"] and outcome["relaxed"]


def test_relaxed_handles_empty_results():
    test = make_test(expected_result=[])
    assert compare(test, ["city", "customer_count"], [])["relaxed"]
    assert not compare(test, ["city", "customer_count"], [("Lviv", 1)])["relaxed"]
