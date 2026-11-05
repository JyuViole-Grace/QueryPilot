"""The sample database is English, reproducible from the seed, and tied to every dataset."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import init_db
import seed_data
from sql_safety import DATABASE_PATH

TESTS_DIR = Path(__file__).resolve().parent
CYRILLIC = re.compile("[\u0400-\u04FF]")
DATASETS = ("golden_questions.json", "heldout_questions.json", "heldout_v3_questions.json", "heldout_v4_questions.json")


def table_hashes(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {
            table: hashlib.sha256(repr(connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()).encode()).hexdigest()
            for table in tables
        }
    finally:
        connection.close()


def test_the_shipped_database_contains_no_cyrillic_text():
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        found = [
            (table, value) for table in tables
            for row in connection.execute(f"SELECT * FROM {table}")
            for value in row if isinstance(value, str) and CYRILLIC.search(value)
        ]
    finally:
        connection.close()

    assert found[:3] == []


def test_the_seed_script_reproduces_the_shipped_database(tmp_path, monkeypatch):
    """Dataset fingerprints rely on this: the shipped file must equal a fresh seed."""
    target = tmp_path / "fresh.db"
    monkeypatch.setattr(init_db, "DATABASE_PATH", target)
    monkeypatch.setattr(seed_data, "DATABASE_PATH", target)

    init_db.initialize_database()
    seed_data.seed_database()

    assert table_hashes(target) == table_hashes(DATABASE_PATH)


def test_every_dataset_records_the_current_database_and_edition():
    expected = hashlib.sha256(DATABASE_PATH.read_bytes()).hexdigest()

    for name in DATASETS:
        data = json.loads((TESTS_DIR / name).read_text(encoding="utf-8"))

        assert data["data_edition"] == "english", name
        assert data["database_sha256"] == expected, f"{name} was built for a different database"


def test_no_dataset_text_contains_cyrillic():
    for name in DATASETS:
        text = (TESTS_DIR / name).read_text(encoding="utf-8")

        assert not CYRILLIC.search(text), name
