"""Quality self-correction loop without any LLM critic (removed after evaluation).

The SQL quality validator is replaced by a small fake so these tests do not
depend on sqlglot and exercise only the loop logic.
"""

import io
from contextlib import redirect_stdout

import evaluate_sql as ev

TEST = {
    "id": "t1", "category": "x", "question": "How many customers are there?",
    "reference_sql": "SELECT COUNT(*) AS n FROM customers",
    "expected_columns": ["n"], "expected_result": [{"n": 100}],
}

GOOD = "SELECT COUNT(*) AS n FROM customers"
WRONG_BUT_RUNS = "SELECT COUNT(*) AS n FROM orders"      # executes, wrong answer
BROKEN = "SELECT COUNT(*) AS n FROM missing_table"       # execution error


def fake_quality(monkeypatch, invalid_marker="orders"):
    """Flag SQL that mentions ``invalid_marker`` as a quality problem."""
    def validate(question, sql):
        bad = invalid_marker in sql
        return {"valid": not bad, "issues": ["uses the wrong table"] if bad else []}

    monkeypatch.setattr(ev, "validate_sql_quality", validate)


def scripted(answers):
    calls = []

    def generate(question, previous_sql=None, error_feedback=None, attempt=0):
        calls.append({"previous_sql": previous_sql, "feedback": error_feedback})
        return answers[len(calls) - 1]

    generate.calls = calls
    return generate


def run(generate):
    return ev.evaluate_question(TEST, generate, 2, False, quality_repair=True, deterministic_repairs=False)


def test_valid_first_answer_needs_no_repair_and_has_no_critic_fields(monkeypatch):
    fake_quality(monkeypatch)
    generate = scripted([GOOD])

    result = run(generate)

    assert result["attempts"] == 1 and len(generate.calls) == 1
    assert result["final"]["execution_match"]
    assert "semantic_reviews" not in result and "final_semantic_review" not in result


def test_execution_error_triggers_a_repair(monkeypatch):
    fake_quality(monkeypatch)

    result = run(scripted([BROKEN, GOOD]))

    assert result["attempts"] == 2 and result["final"]["execution_match"]
    assert not result["first_attempt"]["executed"]


def test_a_quality_failure_triggers_a_repair_with_the_issues_as_feedback(monkeypatch):
    fake_quality(monkeypatch)
    generate = scripted([WRONG_BUT_RUNS, GOOD])

    result = run(generate)

    assert result["attempts"] == 2 and result["final"]["execution_match"]
    assert "uses the wrong table" in generate.calls[1]["feedback"]
    assert "critic" not in generate.calls[1]["feedback"].lower()


def test_a_worse_candidate_does_not_replace_a_better_one(monkeypatch):
    fake_quality(monkeypatch)

    # 1st: runs but flagged; 2nd: execution error (worse); 3rd: same as 2nd -> stuck
    result = run(scripted([WRONG_BUT_RUNS, BROKEN, BROKEN]))

    assert result["final"]["executed"]            # the executable candidate is kept
    assert result["final_sql"] == WRONG_BUT_RUNS


def test_a_repeated_answer_stops_the_loop(monkeypatch):
    fake_quality(monkeypatch)

    result = run(scripted([BROKEN, BROKEN]))

    assert result["stuck_on_same_sql"] and result["attempts"] == 1


def test_baseline_mode_still_retries_only_after_execution_errors(monkeypatch):
    fake_quality(monkeypatch)

    result = ev.evaluate_question(TEST, scripted([WRONG_BUT_RUNS]), 2, False)

    assert result["attempts"] == 1 and result["mode"] == "baseline"


def test_conflicting_modes_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        ev.evaluate_question(TEST, scripted([GOOD]), 1, True, quality_repair=True)


def test_summary_and_printout_contain_no_critic_statistics(monkeypatch):
    fake_quality(monkeypatch)
    generate = scripted([GOOD])

    results, summary = ev.run_evaluation([TEST], generate, retries=1, quality_repair=True,
                                         deterministic_repairs=False, verbose=False)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ev.print_summary(summary, "m: quality self-correction")

    assert "critic" not in summary
    assert "critic" not in buffer.getvalue().lower()
