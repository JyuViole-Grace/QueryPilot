import contextlib
import io
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import evaluate_sql as ev
from helpers import (BROKEN_SQL, GOOD_SQL, GOOD_SQL_OTHER_ALIAS, WRONG_SQL,
                     executor_for, make_db, make_test)
from sql_generator import ModelNotFoundError

SECRET = "SECRET_ALIAS"


def secret_test():
    """Test whether a unique column name leaks reference information."""
    return make_test(
        expected_columns=["city", SECRET],
        expected_result=[{"city": "Lviv", SECRET: 2}, {"city": "Kyiv", SECRET: 1}],
    )


class Scripted:
    """Generator stub that returns predefined SQL and records calls."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, question, previous_sql=None, error_feedback=None, attempt=0):
        self.calls.append({"previous_sql": previous_sql, "feedback": error_feedback, "attempt": attempt})
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]

        if isinstance(answer, Exception):
            raise answer

        return answer


def run(test, generate, oracle=False, retries=2):
    return ev.evaluate_question(test, generate, retries, oracle, executor_for(make_db()))


def test_baseline_does_not_retry_a_wrong_but_executable_query():
    generate = Scripted(WRONG_SQL, GOOD_SQL)
    result = run(make_test(), generate)

    assert len(generate.calls) == 1
    assert result["attempts"] == 1
    assert result["correction_history"] == []
    assert result["first_attempt"]["executed"] is True
    assert result["final"]["execution_match"] is False
    assert result["mode"] == "baseline"


def test_baseline_retries_only_on_sql_errors_and_never_leaks_the_reference():
    generate = Scripted(BROKEN_SQL, GOOD_SQL)
    result = run(secret_test(), generate)

    assert result["attempts"] == 2
    assert result["first_attempt"]["executed"] is False
    assert result["final"]["execution_match"] is True

    feedback = generate.calls[1]["feedback"]
    assert "no such column" in feedback.lower()           # SQLite error text
    assert SECRET not in feedback                          # no reference column names
    assert "Expected" not in feedback                       # expected row count
    assert SECRET not in json.dumps(result["correction_history"], ensure_ascii=False)


def test_oracle_mode_gives_reference_hints_and_is_labelled():
    generate = Scripted(GOOD_SQL_OTHER_ALIAS, f"SELECT city, COUNT(*) AS {SECRET} FROM customers GROUP BY city")
    result = run(secret_test(), generate, oracle=True)

    assert result["mode"] == "oracle_assisted"
    assert result["first_attempt"]["execution_match"] is True    # values match
    assert result["first_attempt"]["strict"] is False            # but the alias differs
    assert SECRET in generate.calls[1]["feedback"]               # reference-derived hint
    assert result["attempts"] == 2
    assert result["final"]["strict"] is True


def test_retries_are_capped():
    generate = Scripted("SELECT missing_a FROM customers", "SELECT missing_b FROM customers",
                        "SELECT missing_c FROM customers", "SELECT missing_d FROM customers")
    result = run(make_test(), generate, retries=2)

    assert result["attempts"] == 3
    assert len(generate.calls) == 3
    assert result["final"]["executed"] is False


def test_a_model_that_repeats_the_same_sql_is_stopped_instead_of_looping():
    generate = Scripted(BROKEN_SQL, BROKEN_SQL + " ;", GOOD_SQL)   # same SQL with different whitespace
    result = run(make_test(), generate, retries=2)

    assert result["stuck_on_same_sql"] is True
    assert len(generate.calls) == 2                      # third call is unnecessary
    assert result["attempts"] == 1                       # no new candidate was produced
    assert result["correction_history"][0]["repeated_same_sql"] is True
    assert result["final"]["executed"] is False


def test_same_sql_ignores_only_outer_whitespace_and_trailing_semicolons():
    assert ev.same_sql("SELECT 1", "SELECT 1")
    assert ev.same_sql("  SELECT 1\n", "SELECT 1;")
    assert ev.same_sql("SELECT 1 ;", "SELECT 1")
    assert ev.same_sql("SELECT 1;;", "SELECT 1")
    assert not ev.same_sql("SELECT 1", "SELECT 2")
    assert not ev.same_sql("SELECT 'a'", "SELECT 'A'")   # case matters inside string literals


def test_same_sql_keeps_whitespace_inside_string_literals():
    """Regression: whitespace in a literal changes results, so queries differ."""
    one_space, two_spaces = "SELECT 'a b'", "SELECT 'a  b'"
    tab, newline = "SELECT 'a\tb'", "SELECT 'a\nb'"

    assert not ev.same_sql(one_space, two_spaces)
    assert not ev.same_sql(one_space, tab)
    assert not ev.same_sql(one_space, newline)
    assert not ev.same_sql(tab, newline)
    assert not ev.same_sql("SELECT ' x'", "SELECT 'x'")   # whitespace at the edge of a literal
    assert not ev.same_sql("SELECT 'x '", "SELECT 'x'")

    # these really are different results
    connection = sqlite3.connect(":memory:")
    assert connection.execute(one_space).fetchone() != connection.execute(two_spaces).fetchone()
    connection.close()


def test_a_query_that_differs_only_inside_a_literal_is_not_treated_as_a_repeat():
    # Both queries fail, so baseline continues the repair loop.
    # They differ only by whitespace inside a literal, so they are different queries.
    first = "SELECT missing FROM customers WHERE city = 'a  b'"
    second = "SELECT missing FROM customers WHERE city = 'a b'"
    generate = Scripted(first, second, GOOD_SQL)

    result = run(make_test(), generate, retries=2)

    assert result["stuck_on_same_sql"] is False
    assert len(generate.calls) == 3                 # the second query is not treated as a repeat
    assert result["attempts"] == 3
    assert result["final"]["execution_match"] is True


def test_a_generation_error_is_recorded_and_the_run_continues():
    tests = [make_test(id="a"), make_test(id="b")]
    generate = Scripted(RuntimeError("Ollama hiccup"), GOOD_SQL)

    results, summary = ev.run_evaluation(
        tests, generate, executor=executor_for(make_db()), verbose=False)

    assert results[0]["generation_error"].startswith("RuntimeError")
    assert results[0]["final"]["execution_match"] is False
    assert results[1]["final"]["execution_match"] is True
    assert summary["stages"]["final"]["execution_match"] == 1


def test_repeated_generation_errors_stop_the_run_instead_of_producing_a_report_of_zeros():
    tests = [make_test(id=f"t{i}") for i in range(6)]
    generate = Scripted(RuntimeError("connection refused"))

    with pytest.raises(RuntimeError) as error:
        ev.run_evaluation(tests, generate, executor=executor_for(make_db()), verbose=False)

    assert "connection refused" in str(error.value)
    assert len(generate.calls) == ev.MAX_CONSECUTIVE_GENERATION_ERRORS


def test_a_missing_model_stops_immediately():
    with pytest.raises(ModelNotFoundError):
        run(make_test(), Scripted(ModelNotFoundError("ollama pull x")))


def test_summary_counts_metrics_and_categories():
    tests = [make_test(id="a", category="joins"), make_test(id="b", category="joins"),
             make_test(id="c", category="sorting")]
    generate = Scripted(GOOD_SQL, WRONG_SQL, GOOD_SQL_OTHER_ALIAS)

    _, summary = ev.run_evaluation(
        tests, generate, executor=executor_for(make_db()), verbose=False)

    final = summary["stages"]["final"]
    assert summary["total"] == 3
    assert final["execution_match"] == 2     # a and c
    assert final["strict"] == 1              # only a: c has a different alias
    assert summary["by_category"]["joins"] == {
        "total": 2, "first_attempt_execution_match": 1, "final_execution_match": 1}
    assert summary["by_category"]["sorting"]["final_execution_match"] == 1
    assert summary["average_attempts"] == 1
    assert summary["stuck_on_same_sql"] == 0


def test_truncated_results_are_never_counted_as_correct():
    outcome = ev.evaluate_candidate(
        make_test(expected_result=[]),
        "SELECT * FROM customers",
        lambda sql: {"columns": ["id"], "rows": [], "truncated": True, "execution_time_seconds": 0},
    )

    assert outcome["execution_match"] is False
    assert "truncated" in outcome["error"]


def test_save_report_is_labelled_and_separated_by_mode():
    original = ev.REPORT_DIR
    ev.REPORT_DIR = Path(tempfile.mkdtemp(prefix="qp_reports_"))

    try:
        results, summary = ev.run_evaluation(
            [make_test()], Scripted(GOOD_SQL), executor=executor_for(make_db()), verbose=False)
        baseline = ev.save_report("m", False, 2, results, summary)
        oracle = ev.save_report("m", True, 2, results, summary)
    finally:
        reports_dir = ev.REPORT_DIR
        ev.REPORT_DIR = original

    scratch = None
    original = ev.REPORT_DIR
    ev.REPORT_DIR = Path(tempfile.mkdtemp(prefix="qp_reports_"))

    try:
        scratch = ev.save_report("m", False, 2, results, summary, partial=True)
        scratch_parent = scratch.parent.name
        main_dir_files = [item.name for item in ev.REPORT_DIR.iterdir()]
    finally:
        ev.REPORT_DIR = original

    assert scratch_parent == "scratch"                    # does not replace the main report
    assert main_dir_files == ["scratch"]
    assert baseline.name == "baseline_v2_evaluation.json"
    assert oracle.name == "oracle_assisted_v2_evaluation.json"
    assert json.loads(baseline.read_text(encoding="utf-8"))["oracle_assisted"] is False
    assert json.loads(oracle.read_text(encoding="utf-8"))["oracle_assisted"] is True
    assert len(list(reports_dir.iterdir())) == 2


def test_save_report_supports_a_custom_json_filename():
    original = ev.REPORT_DIR
    ev.REPORT_DIR = Path(tempfile.mkdtemp(prefix="qp_reports_"))

    try:
        results, summary = ev.run_evaluation(
            [make_test()], Scripted(GOOD_SQL), executor=executor_for(make_db()), verbose=False)
        path = ev.save_report("test", False, 0, results, summary, report_name="comparison_run.json")
        assert path.name == "comparison_run.json"

        with pytest.raises(ValueError):
            ev.save_report("test", False, 0, results, summary, report_name="../escape.json")
    finally:
        ev.REPORT_DIR = original


def test_rescore_reads_old_and_new_report_formats():
    path = Path(tempfile.mkdtemp(prefix="qp_rescore_")) / "old.json"
    path.write_text(json.dumps({"results": [
        {"test_id": "t1", "initial_sql": BROKEN_SQL, "generated_sql": GOOD_SQL, "attempts": 2},
    ]}), encoding="utf-8")

    results, summary = ev.rescore_report(path, [make_test()], executor_for(make_db()))

    assert results[0]["first_attempt"]["executed"] is False
    assert results[0]["final"]["execution_match"] is True
    assert summary["stages"]["first_attempt"]["execution_match"] == 0
    assert summary["stages"]["final"]["execution_match"] == 1

    legacy = Path(tempfile.mkdtemp(prefix="qp_rescore_")) / "legacy.json"
    legacy.write_text(json.dumps({"results": [{"test_id": "t1", "generated_sql": WRONG_SQL}]}), encoding="utf-8")

    results, _ = ev.rescore_report(legacy, [make_test()], executor_for(make_db()))
    assert results[0]["initial_sql"] == WRONG_SQL
    assert results[0]["final"]["execution_match"] is False


def test_load_golden_dataset_validates_structure():
    directory = Path(tempfile.mkdtemp(prefix="qp_golden_"))

    good = directory / "good.json"
    good.write_text(json.dumps({"tests": [make_test()]}), encoding="utf-8")
    assert ev.load_golden_dataset(good)[0]["id"] == "t1"

    as_list = directory / "list.json"
    as_list.write_text(json.dumps([make_test()]), encoding="utf-8")
    assert len(ev.load_golden_dataset(as_list)) == 1

    bad = directory / "bad.json"
    bad.write_text(json.dumps({"tests": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_golden_dataset(bad)

    empty = directory / "empty.json"
    empty.write_text(json.dumps({"tests": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_golden_dataset(empty)

    with pytest.raises(FileNotFoundError):
        ev.load_golden_dataset(directory / "missing.json")


def test_sign_test_p_values():
    assert ev.sign_test_p_value(0, 0) == 1.0
    assert abs(ev.sign_test_p_value(5, 0) - 0.0625) < 1e-9
    assert abs(ev.sign_test_p_value(3, 1) - 0.625) < 1e-9
    assert ev.sign_test_p_value(2, 2) == 1.0
    assert ev.sign_test_p_value(10, 0) < 0.01


def write_report(verdicts):
    path = Path(tempfile.mkdtemp(prefix="qp_compare_")) / "report.json"
    path.write_text(json.dumps({"results": [
        {"test_id": tid, "final": {"execution_match": ok}} for tid, ok in verdicts.items()
    ]}), encoding="utf-8")

    return path


def test_compare_reports_lists_what_improved_and_regressed():
    first = write_report({"t1": True, "t2": False, "t3": False, "t4": True})
    second = write_report({"t1": True, "t2": True, "t3": False, "t4": False, "t5": True})

    result = ev.compare_reports(first, second)

    assert result["improved"] == ["t2"]
    assert result["regressed"] == ["t4"]
    assert result["unchanged"] == 2
    assert result["compared"] == 4
    assert result["only_in_second"] == ["t5"]
    assert result["p_value"] == 1.0


def test_compare_reports_refuses_old_report_formats():
    legacy = Path(tempfile.mkdtemp(prefix="qp_compare_")) / "legacy.json"
    legacy.write_text(json.dumps({"results": [{"test_id": "t1", "passed": True}]}), encoding="utf-8")

    with pytest.raises(ValueError):
        ev.compare_reports(legacy, write_report({"t1": True}))


def test_heldout_reports_get_their_own_file_and_record_the_prompt_version():
    original = ev.REPORT_DIR
    ev.REPORT_DIR = Path(tempfile.mkdtemp(prefix="qp_reports_"))

    try:
        results, summary = ev.run_evaluation(
            [make_test()], Scripted(GOOD_SQL), executor=executor_for(make_db()), verbose=False)
        path = ev.save_report("m", False, 2, results, summary, dataset="heldout")
        golden = ev.save_report("m", False, 2, results, summary)
    finally:
        ev.REPORT_DIR = original

    report = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "heldout_baseline_v2_evaluation.json"
    assert golden.name == "baseline_v2_evaluation.json"
    assert report["dataset"] == "heldout"
    assert report["prompt_sha256_prefix"] == ev.prompt_fingerprint()


def test_prompt_fingerprint_is_stable_and_follows_the_prompt():
    original = ev.SYSTEM_PROMPT

    try:
        first = ev.prompt_fingerprint()
        assert first == ev.prompt_fingerprint() and len(first) == 16

        ev.SYSTEM_PROMPT = original + " changed"
        assert ev.prompt_fingerprint() != first
    finally:
        ev.SYSTEM_PROMPT = original


def test_dataset_metadata_excludes_the_tests_and_tolerates_the_list_format():
    directory = Path(tempfile.mkdtemp(prefix="qp_meta_"))

    with_meta = directory / "a.json"
    with_meta.write_text(json.dumps({"role": "heldout", "tests": [make_test()]}), encoding="utf-8")
    assert ev.load_dataset_metadata(with_meta) == {"role": "heldout"}

    as_list = directory / "b.json"
    as_list.write_text(json.dumps([make_test()]), encoding="utf-8")
    assert ev.load_dataset_metadata(as_list) == {}


def test_the_summary_shows_a_confidence_interval():
    _, summary = ev.run_evaluation(
        [make_test()], Scripted(GOOD_SQL), executor=executor_for(make_db()), verbose=False)
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        ev.print_summary(summary, "test")

    assert "confidence interval" in buffer.getvalue()

def test_candidate_score_ignores_reference_metrics():
    quality_result = {
        "valid": True,
        "issues": [],
    }

    correct_reference_match = {
        "executed": True,
        "strict": True,
        "execution_match": True,
        "lenient": True,
    }

    incorrect_reference_match = {
        "executed": True,
        "strict": False,
        "execution_match": False,
        "lenient": False,
    }

    score_correct = ev.candidate_score(
        correct_reference_match,
        quality_result,
    )

    score_incorrect = ev.candidate_score(
        incorrect_reference_match,
        quality_result,
    )

    assert score_correct == score_incorrect

@pytest.mark.parametrize(
    "deterministic_repairs",
    [True, False],
)
def test_deterministic_repairs_can_be_disabled(
        monkeypatch,
        deterministic_repairs,
):
    calls = []

    def fake_repair(name):
        def repair(question, sql):
            calls.append(name)
            return sql
        return repair

    repair_names = (
        "repair_supplier_rating_alias",
        "repair_order_line_items_total_alias",
        "repair_cheapest_products_id_alias",
    )

    for name in repair_names:
        monkeypatch.setattr(
            ev,
            name,
            fake_repair(name),
        )

    result = ev.evaluate_question(
        make_test(),
        Scripted(GOOD_SQL),
        retries=0,
        oracle=False,
        executor=executor_for(make_db()),
        quality_repair=True,
        deterministic_repairs=deterministic_repairs,
    )

    assert calls == []
    assert result["deterministic_repair"]["attempted"] is False

def test_save_report_separates_deterministic_repair_modes():
    original = ev.REPORT_DIR
    ev.REPORT_DIR = Path(tempfile.mkdtemp(prefix="qp_reports_"))

    try:
        enabled = ev.save_report(
            "qwen2.5:7b",
            False,
            2,
            [],
            {},
            quality_repair=True,
            deterministic_repairs=True,
        )

        disabled = ev.save_report(
            "qwen2.5:7b",
            False,
            2,
            [],
            {},
            quality_repair=True,
            deterministic_repairs=False,
        )

        enabled_data = json.loads(
            enabled.read_text(encoding="utf-8")
        )
        disabled_data = json.loads(
            disabled.read_text(encoding="utf-8")
        )

    finally:
        ev.REPORT_DIR = original

    assert enabled != disabled
    assert "_no_deterministic_" in disabled.name

    assert enabled_data["deterministic_repairs_enabled"] is True
    assert disabled_data["deterministic_repairs_enabled"] is False