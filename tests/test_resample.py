"""Resampling after a repeated repair answer, and the sampling options sent to Ollama."""

import json

import evaluate_sql as ev
import sql_generator as generator
from test_generator import FakeResponse, reply, with_urlopen


def install_fake_model(monkeypatch, answers):
    """Replace generate_sql by a scripted model; record the sampling arguments."""
    calls = []

    def fake(question, **kwargs):
        calls.append(kwargs)
        return answers[len(calls) - 1]

    monkeypatch.setattr(ev, "generate_sql", fake)
    monkeypatch.setattr(ev, "build_context", lambda question: None)
    return calls


def test_resample_is_off_by_default(monkeypatch):
    calls = install_fake_model(monkeypatch, ["SELECT 1", "SELECT 2"])
    generate = ev.make_generator("m")

    assert generate("q", previous_sql="SELECT 1", error_feedback="e", attempt=1) == "SELECT 1"
    assert len(calls) == 1 and "temperature" not in calls[0]
    assert generate.resample_count == 0


def test_a_repeated_answer_is_resampled_with_temperature_and_a_fixed_seed(monkeypatch):
    calls = install_fake_model(monkeypatch, ["SELECT 1", "SELECT 2"])
    generate = ev.make_generator("m", resample_on_repeat=True)

    result = generate("q", previous_sql="SELECT 1;", error_feedback="e", attempt=1)

    assert result == "SELECT 2"
    assert len(calls) == 2
    assert calls[1]["temperature"] == ev.RESAMPLE_TEMPERATURE > 0
    assert calls[1]["seed"] == ev.RESAMPLE_SEED_BASE + 10
    assert generate.resample_count == 1


def test_resampling_gives_up_after_the_try_limit(monkeypatch):
    calls = install_fake_model(monkeypatch, ["SELECT 1"] * 5)
    generate = ev.make_generator("m", resample_on_repeat=True)

    result = generate("q", previous_sql="SELECT 1", error_feedback="e", attempt=1)

    assert result == "SELECT 1"                       # still the same: the loop will report it as stuck
    assert len(calls) == 1 + ev.RESAMPLE_TRIES
    assert generate.resample_count == ev.RESAMPLE_TRIES


def test_a_first_generation_or_a_changed_answer_is_never_resampled(monkeypatch):
    calls = install_fake_model(monkeypatch, ["SELECT 1", "SELECT 3"])
    generate = ev.make_generator("m", resample_on_repeat=True)

    generate("q")                                                     # no previous SQL
    generate("q", previous_sql="SELECT 2", error_feedback="e", attempt=1)  # answer differs

    assert len(calls) == 2 and generate.resample_count == 0


def test_the_repair_loop_recovers_from_a_stuck_model_when_resampling(monkeypatch):
    test = {
        "id": "t1", "category": "x", "question": "How many customers are there?",
        "reference_sql": "SELECT COUNT(*) AS n FROM customers",
        "expected_columns": ["n"], "expected_result": [{"n": 100}],
    }
    # First answer fails to execute; the repair repeats it; the resample fixes it.
    answers = ["SELECT COUNT(*) AS n FROM missing_table", "SELECT COUNT(*) AS n FROM missing_table",
               "SELECT COUNT(*) AS n FROM customers"]
    install_fake_model(monkeypatch, answers)

    stuck = ev.evaluate_question(test, ev.make_generator("m"), 2, False)
    assert stuck["stuck_on_same_sql"] and not stuck["final"]["executed"]

    install_fake_model(monkeypatch, answers)
    fixed = ev.evaluate_question(test, ev.make_generator("m", resample_on_repeat=True), 2, False)
    assert not fixed["stuck_on_same_sql"] and fixed["final"]["execution_match"]


def _capture_options(**kwargs):
    seen = {}

    def fake(request, timeout):
        seen.update(json.loads(request.data.decode("utf-8"))["options"])
        return reply("SELECT 1")

    original = with_urlopen(fake)
    try:
        generator.generate_sql("Question", **kwargs)
    finally:
        generator.urlopen = original
    return seen


def test_default_requests_are_deterministic_and_unseeded():
    options = _capture_options()

    assert options["temperature"] == 0 and "seed" not in options


def test_sampling_options_are_sent_to_ollama_when_requested():
    options = _capture_options(temperature=0.7, seed=1010)

    assert options["temperature"] == 0.7 and options["seed"] == 1010
