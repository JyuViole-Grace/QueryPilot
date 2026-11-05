from pathlib import Path

from context_builder import build_context, relevant_tables
from helpers import make_db


def test_relevant_tables_use_english_domain_terms():
    assert "products" in relevant_tables("Which products have the largest stock?")
    assert "orders" in relevant_tables("How many delivered orders are there?")


def test_context_includes_safe_database_value_hints():
    path = make_db()
    context = build_context("Show customers by city and order status", path)

    assert "customers" in context
    assert "Known customer cities" in context


def test_context_works_when_database_is_missing(tmp_path: Path):
    context = build_context("Which products are available?", tmp_path / "missing.db")
    assert "products" in context


def test_context_lists_valid_join_conditions():
    from context_builder import CONTEXT_VERSION

    context = build_context("Which customers placed orders?", Path("missing.db"))

    assert "orders.customer_id = customers.customer_id" in context
    assert isinstance(CONTEXT_VERSION, int) and CONTEXT_VERSION >= 2


def test_join_hints_can_be_switched_off_for_ablation(monkeypatch):
    from context_builder import context_version, join_hints_enabled

    monkeypatch.setenv("QUERYPILOT_JOIN_HINTS", "0")

    assert not join_hints_enabled()
    assert context_version() == 1
    assert "Valid join conditions" not in build_context("Which customers placed orders?", Path("missing.db"))

    monkeypatch.setenv("QUERYPILOT_JOIN_HINTS", "1")

    assert join_hints_enabled()
    assert context_version() == 2
    assert "Valid join conditions" in build_context("Which customers placed orders?", Path("missing.db"))

    monkeypatch.delenv("QUERYPILOT_JOIN_HINTS")

    assert join_hints_enabled()
