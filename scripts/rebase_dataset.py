"""One-time migration of question sets to the English edition of the sample data.

The seed data originally used Russian-language values (city names, customer
names, category names, supplier countries). ``seed_data.py`` now generates the
same database with English values: the random draws are unchanged, so every
number, key and date is identical and only those four text columns differ.

This script moves an existing dataset file to the new database:

1. translates the old literals in ``question`` and ``reference_sql`` (and in
   ``common_wrong_sql`` when present);
2. re-executes every reference query on the current database to regenerate
   ``expected_columns`` and ``expected_result`` (row order can change when a
   query sorts by a translated text column);
3. records ``data_edition`` and ``database_sha256`` in the file header;
4. keeps every other field (ids, categories, notes, prompt fingerprint) as is.

Usage: python scripts/rebase_dataset.py tests/heldout_v3_questions.json [...]
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from build_heldout_dataset import check_order_is_unambiguous, execute_reference_query

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"

RU_TO_EN = {
    # cities
    "Львов": "Lviv", "Киев": "Kyiv", "Одесса": "Odesa", "Харьков": "Kharkiv",
    "Днепр": "Dnipro", "Винница": "Vinnytsia", "Полтава": "Poltava", "Черкассы": "Cherkasy",
    # categories
    "Ноутбуки": "Laptops", "Смартфоны": "Smartphones", "Мониторы": "Monitors",
    "Комплектующие": "Components", "Периферия": "Peripherals", "Аудио": "Audio",
    "Сетевое оборудование": "Networking Equipment", "Аксессуары": "Accessories",
    # supplier countries
    "Украина": "Ukraine", "Польша": "Poland", "Германия": "Germany",
    "Чехия": "Czechia", "Китай": "China", "Тайвань": "Taiwan",
    # first names
    "Александр": "Oleksandr", "Мария": "Maria", "Дмитрий": "Dmytro", "Анна": "Anna",
    "Максим": "Maksym", "София": "Sofia", "Артём": "Artem", "Елена": "Olena",
    "Иван": "Ivan", "Дарья": "Daria", "Никита": "Nikita", "Виктория": "Viktoria",
    # last names
    "Коваленко": "Kovalenko", "Бондаренко": "Bondarenko", "Ткаченко": "Tkachenko",
    "Мельник": "Melnyk", "Шевченко": "Shevchenko", "Кравченко": "Kravchenko",
    "Олейник": "Oliinyk", "Поліщук": "Polishchuk", "Бойко": "Boiko", "Мороз": "Moroz",
}


def translate(text: str) -> str:
    """Replace known Russian literals, longest first."""
    for old in sorted(RU_TO_EN, key=len, reverse=True):
        text = text.replace(old, RU_TO_EN[old])

    return text


def rebase(path: Path, connection: sqlite3.Connection) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    document: dict[str, Any] = data if isinstance(data, dict) else {"tests": data}
    problems: list[str] = []

    for test in document["tests"]:
        test["question"] = translate(test["question"])
        test["reference_sql"] = translate(test["reference_sql"])

        if "common_wrong_sql" in test:
            test["common_wrong_sql"] = [translate(sql) for sql in test["common_wrong_sql"]]

        columns, rows = execute_reference_query(connection, test["reference_sql"])

        if list(columns) != list(test["expected_columns"]):
            problems.append(f"{test['id']}: output columns changed {test['expected_columns']} -> {columns}")

        test["expected_columns"] = columns
        test["expected_result"] = rows

        for problem in check_order_is_unambiguous(connection, test):
            problems.append(f"{test['id']}: {problem}")

    if isinstance(data, dict):
        document["data_edition"] = "english"
        document["database_sha256"] = hashlib.sha256(DATABASE_PATH.read_bytes()).hexdigest()

    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    status = 0

    try:
        for name in argv:
            problems = rebase(Path(name), connection)
            print(f"{name}: rebased" + (f", {len(problems)} problem(s)" if problems else ""))
            for problem in problems:
                print("  -", problem)
            status |= bool(problems)
    finally:
        connection.close()

    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
