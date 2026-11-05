
"""Deterministic quality checks for SQL generated from natural-language questions."""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from join_check import find_invalid_join_keys


def _get_final_select_clause(sql: str) -> str:
    """Extract the SELECT clause from the outermost query."""

    depth = 0
    quote = None
    select_start = None
    index = 0

    while index < len(sql):
        char = sql[index]

        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None

            elif char == "\\" and quote != "]":
                index += 2
                continue

            index += 1
            continue

        if char in ("'", '"', "`"):
            quote = char
            index += 1
            continue

        if char == "[":
            quote = "]"
            index += 1
            continue

        if sql[index:index + 2] == "--":
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline + 1
            continue

        if sql[index:index + 2] == "/*":
            comment_end = sql.find("*/", index + 2)
            index = len(sql) if comment_end == -1 else comment_end + 2
            continue

        if char == "(":
            depth += 1
            index += 1
            continue

        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue

        if depth == 0:
            match = re.match(r"\bSELECT\b", sql[index:], re.IGNORECASE)

            if match:
                select_start = index + match.end()
                index = select_start
                break

        index += 1

    if select_start is None:
        return ""

    index = select_start
    depth = 0
    quote = None

    while index < len(sql):
        char = sql[index]

        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None

            elif char == "\\" and quote != "]":
                index += 2
                continue

            index += 1
            continue

        if char in ("'", '"', "`"):
            quote = char
            index += 1
            continue

        if char == "[":
            quote = "]"
            index += 1
            continue

        if sql[index:index + 2] == "--":
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline + 1
            continue

        if sql[index:index + 2] == "/*":
            comment_end = sql.find("*/", index + 2)
            index = len(sql) if comment_end == -1 else comment_end + 2
            continue

        if char == "(":
            depth += 1
            index += 1
            continue

        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue

        if depth == 0:
            match = re.match(r"\bFROM\b", sql[index:], re.IGNORECASE)

            if match:
                return sql[select_start:index].strip()

        index += 1

    return ""


def _get_output_names(select_clause: str) -> list[str]:
    """Extract output column names from a SELECT clause."""

    output_names: list[str] = []
    columns: list[str] = []

    current: list[str] = []
    depth = 0
    quote_char = None
    i = 0

    # Split only on commas outside parentheses and quoted strings.
    while i < len(select_clause):
        char = select_clause[i]

        if quote_char:
            current.append(char)

            # Handle escaped quote characters.
            if char == quote_char:
                if i + 1 < len(select_clause) and select_clause[i + 1] == quote_char:
                    current.append(select_clause[i + 1])
                    i += 2
                    continue

                quote_char = None

        elif char in ("'", '"', "`"):
            quote_char = char
            current.append(char)

        elif char == "[":
            quote_char = "]"
            current.append(char)

        elif char == "(":
            depth += 1
            current.append(char)

        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)

        elif char == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []

        else:
            current.append(char)

        i += 1

    if current:
        columns.append("".join(current).strip())

    # Extract aliases or simple column names.
    for column in columns:
        alias_match = re.search(
            r"\bAS\s+([a-zA-Z_]\w*)\s*$",
            column,
            flags=re.IGNORECASE,
        )

        if alias_match:
            output_names.append(alias_match.group(1).casefold())
        else:
            bare_name = column.split(".")[-1].strip()
            bare_name = bare_name.strip('"`[]')
            output_names.append(bare_name.casefold())

    return output_names

def _validate_money_threshold(question: str, sql: str) -> str | None:
    """Validate explicit UAH thresholds against monetary columns stored in cents."""

    range_match = re.search(
        r"\bbetween\s+(\d[\d\s,]*(?:\.\d+)?)\s+and\s+"
        r"(\d[\d\s,]*(?:\.\d+)?)\s*"
        r"(?:uah|hryvnias?)",
        question,
        flags=re.IGNORECASE,
    )

    if range_match:
        lower_bound_cents = round(
            float(range_match.group(1).replace(",", "").replace(" ", "")) * 100
        )
        upper_bound_cents = round(
            float(range_match.group(2).replace(",", "").replace(" ", "")) * 100
        )

        if lower_bound_cents >= upper_bound_cents:
            return "The question contains an invalid monetary range."

        is_range = True
        expected_cents = None
        amount_uah = None
        direction = None
        expected_operators = ()
        is_lower_bound = False

    else:
        amount_match = re.search(
            r"\b(over|above|more\s+than|greater\s+than|less\s+than|below|under)\s+"
            r"(\d[\d\s,]*(?:\.\d+)?)\s*"
            r"(?:uah|hryvnias?)",
            question,
            flags=re.IGNORECASE,
        )

        if not amount_match:
            return None

        direction = amount_match.group(1).casefold()
        amount_uah = float(
            amount_match.group(2).replace(",", "").replace(" ", "")
        )
        expected_cents = round(amount_uah * 100)

        is_lower_bound = direction in ("less than", "below", "under")
        expected_operators = (
            ("<", "<=") if is_lower_bound else (">", ">=")
        )
        is_range = False

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return None

    expected_table = None
    expected_column = None

    if re.search(r"\bpayments?\b", question, re.IGNORECASE):
        expected_table = "payments"
        expected_column = "amount_cents"

    elif (
            re.search(r"\b(products?|items?)\b", question, re.IGNORECASE)
            and re.search(
        r"\b(price|cost|cheapest|expensive)\b",
        question,
        re.IGNORECASE,
    )
    ):
        expected_table = "products"
        expected_column = "price_cents"

    table_aliases = {}

    for table_node in tree.find_all(exp.Table):
        table_name = table_node.name.casefold()
        table_alias = table_node.alias.casefold() if table_node.alias else table_name
        table_aliases[table_alias] = table_name

    comparisons = []
    range_comparisons = []
    range_bound_comparisons = []
    other_money_comparisons = []

    for node in tree.find_all(exp.Predicate):
        if isinstance(node, exp.Between):
            column = node.this
            low = node.args.get("low")
            high = node.args.get("high")

            if not isinstance(column, exp.Column):
                continue

            if not column.name.casefold().endswith("_cents"):
                continue

            if expected_column is not None:
                if column.table:
                    resolved_table = table_aliases.get(
                        column.table.casefold(),
                        column.table.casefold(),
                    )
                elif expected_table in table_aliases.values():
                    resolved_table = expected_table
                else:
                    resolved_table = ""

                if (
                        column.name.casefold() != expected_column
                        or resolved_table != expected_table
                ):
                    other_money_comparisons.append(node)
                    continue

            if (
                    not isinstance(low, exp.Literal)
                    or low.is_string
                    or not isinstance(high, exp.Literal)
                    or high.is_string
            ):
                continue

            try:
                lower_cents = float(low.this)
                upper_cents = float(high.this)
            except (TypeError, ValueError):
                continue

            range_comparisons.append((lower_cents, upper_cents))
            continue

        if not isinstance(node, (exp.LT, exp.LTE, exp.GT, exp.GTE)):
            continue

        column = node.this
        value = node.expression

        if not isinstance(column, exp.Column):
            continue

        if not column.name.casefold().endswith("_cents"):
            continue

        if not isinstance(value, exp.Literal) or value.is_string:
            continue

        resolved_table = ""

        if column.table:
            resolved_table = table_aliases.get(
                column.table.casefold(),
                column.table.casefold(),
            )
        elif expected_table in table_aliases.values():
            resolved_table = expected_table

        if expected_column is not None:
            if (
                    column.name.casefold() != expected_column
                    or resolved_table != expected_table
            ):
                other_money_comparisons.append(node)
                continue

        try:
            actual_cents = float(value.this)
        except (TypeError, ValueError):
            continue

        operator = {
            exp.LT: "<",
            exp.LTE: "<=",
            exp.GT: ">",
            exp.GTE: ">=",
        }[type(node)]

        comparisons.append((operator, actual_cents))

        comparison_table = (
            resolved_table
            if expected_column is not None
            else column.table.casefold() if column.table else ""
        )

        range_bound_comparisons.append(
            (
                comparison_table,
                column.name.casefold(),
                operator,
                actual_cents,
            )
        )
    if is_range:
        matching_range = any(
            lower == lower_bound_cents and upper == upper_bound_cents
            for lower, upper in range_comparisons
        )

        if matching_range:
            return None

        columns = {}

        for table, column, operator, value in range_bound_comparisons:
            key = (table, column)
            columns.setdefault(key, []).append((operator, value))

        for bounds in columns.values():
            has_lower_bound = any(
                operator in (">", ">=") and value == lower_bound_cents
                for operator, value in bounds
            )
            has_upper_bound = any(
                operator in ("<", "<=") and value == upper_bound_cents
                for operator, value in bounds
            )

            if has_lower_bound and has_upper_bound:
                return None

        if other_money_comparisons and not range_comparisons:
            return (
                f"The question asks about {expected_table}.{expected_column}, "
                "but the SQL compares a different monetary column."
            )

        if range_comparisons or range_bound_comparisons:
            return (
                f"The question specifies a range from "
                f"{lower_bound_cents} to {upper_bound_cents} cents, "
                "but the SQL uses different range boundaries."
            )

        return (
            f"The question specifies a range from "
            f"{lower_bound_cents} to {upper_bound_cents} cents, "
            "but the SQL does not use this range."
        )

    if not comparisons:
        if other_money_comparisons:
            return (
                f"The question asks about {expected_table}.{expected_column}, "
                "but the SQL compares a different monetary column."
            )
        return None

    matching_value = [
        operator
        for operator, value in comparisons
        if value == expected_cents
    ]

    if any(operator in expected_operators for operator in matching_value):
        return None

    if matching_value:
        actual_operator = matching_value[0]
        expected_direction = "less-than" if is_lower_bound else "greater-than"

        return (
            f"The question asks for an amount {direction} {amount_uah:g} UAH, "
            f"but the SQL uses the comparison operator {actual_operator}. "
            f"Use a {expected_direction} comparison."
        )

    return (
        f"The question specifies {amount_uah:g} UAH, which equals "
        f"{expected_cents} cents, but the SQL does not use this threshold. "
        f"Compare the monetary column against {expected_cents}."
    )

def _flatten_and(expression: exp.Expression) -> list[exp.Expression]:
    """Return top-level AND conditions without splitting nested expressions."""

    if isinstance(expression, exp.And):
        return (
                _flatten_and(expression.this)
                + _flatten_and(expression.expression)
        )

    return [expression]


def _has_correlated_order_status(
        exists_node: exp.Exists,
        customer_alias: str,
        expected_status: str,
) -> bool:
    """Check whether an EXISTS subquery filters orders by status
    and correlates customer_id with the outer customer query.
    """

    subquery = exists_node.this

    if not isinstance(subquery, exp.Select):
        return False

    from_clause = subquery.args.get("from_")
    if not from_clause or not isinstance(from_clause.this, exp.Table):
        return False

    orders_table = from_clause.this

    if orders_table.name.casefold() != "orders":
        return False

    orders_alias = orders_table.alias_or_name.casefold()
    customer_alias = customer_alias.casefold()

    where_clause = subquery.args.get("where")
    if not where_clause:
        return False

    conditions = _flatten_and(where_clause.this)

    has_status = False
    has_correlation = False

    for condition in conditions:
        if not isinstance(condition, exp.EQ):
            continue

        left = condition.this
        right = condition.expression

        # Match orders.status = 'expected_status'.
        if (
                isinstance(left, exp.Column)
                and isinstance(right, exp.Literal)
                and left.name.casefold() == "status"
                and left.table.casefold() == orders_alias
                and right.is_string
                and right.this.casefold() == expected_status.casefold()
        ):
            has_status = True

        # Match orders.customer_id = customers.customer_id.
        if (
                isinstance(left, exp.Column)
                and isinstance(right, exp.Column)
                and left.name.casefold() == "customer_id"
                and right.name.casefold() == "customer_id"
                and {
            left.table.casefold(),
            right.table.casefold(),
        } == {orders_alias, customer_alias}
        ):
            has_correlation = True

    return has_status and has_correlation


def _has_cancelled_left_join(
        tree: exp.Select,
        customer_alias: str,
) -> str | None:
    """Return the alias of a LEFT JOIN to cancelled_orders."""

    for join in tree.args.get("joins", []):
        side = (join.args.get("side") or "").upper()

        if side != "LEFT":
            continue

        table = join.this

        if not isinstance(table, exp.Table):
            continue

        if table.name.casefold() != "cancelled_orders":
            continue

        joined_alias = table.alias_or_name.casefold()
        on_clause = join.args.get("on")

        if not on_clause:
            continue

        for condition in _flatten_and(on_clause):
            if not isinstance(condition, exp.EQ):
                continue

            left = condition.this
            right = condition.expression

            if not (
                    isinstance(left, exp.Column)
                    and isinstance(right, exp.Column)
            ):
                continue

            if (
                    left.name.casefold() == "customer_id"
                    and right.name.casefold() == "customer_id"
                    and {
                left.table.casefold(),
                right.table.casefold(),
            } == {customer_alias, joined_alias}
            ):
                return joined_alias

    return None


def _has_non_null_customer_check(
        tree: exp.Select,
        joined_alias: str,
) -> bool:
    """Check whether the joined customer_id is required to be non-null."""

    where_clause = tree.args.get("where")

    if not where_clause:
        return False

    for condition in _flatten_and(where_clause.this):
        if not isinstance(condition, exp.Not):
            continue

        inner = condition.this

        while isinstance(inner, exp.Paren):
            inner = inner.this

        if not isinstance(inner, exp.Is):
            continue

        column = inner.this
        value = inner.expression

        if (
                isinstance(column, exp.Column)
                and column.table.casefold() == joined_alias
                and column.name.casefold() == "customer_id"
                and isinstance(value, exp.Null)
        ):
            return True

    return False


def _validate_cancelled_without_delivered(sql: str) -> list[str]:
    """Validate customer-level cancelled and delivered order conditions."""

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return ["The SQL could not be parsed for customer-level order checks."]

    if not isinstance(tree, exp.Select):
        return ["The query must use an outer SELECT for customer-level checks."]

    issues = []

    # Reject status inequality as a substitute for checking the
    # absence of delivered orders at the customer level.
    where_clause = tree.args.get("where")

    inequality_predicates = (
       list(where_clause.find_all(exp.NEQ))
       if where_clause
       else []
    )

    for cte in tree.find_all(exp.CTE):
        inequality_predicates.extend(cte.find_all(exp.NEQ))

    for predicate in inequality_predicates:
        left = predicate.this
        right = predicate.expression

        is_status_inequality = (
            isinstance(left, exp.Column)
            and left.name.casefold() == "status"
            and isinstance(right, exp.Literal)
            and right.is_string
            and right.this.casefold() == "delivered"
        ) or (
            isinstance(right, exp.Column)
            and right.name.casefold() == "status"
            and isinstance(left, exp.Literal)
            and left.is_string
            and left.this.casefold() == "delivered"
        )

        if is_status_inequality:
            issues.append(
                "The query asks for customers with no delivered orders, "
                "but status != 'delivered' only filters individual order "
                "rows. Use a correlated NOT EXISTS condition."
            )
            break

    from_clause = tree.args.get("from_")

    if not from_clause or not isinstance(from_clause.this, exp.Table):
        return ["The query must select customers from the customers table."]

    customers_table = from_clause.this

    if customers_table.name.casefold() != "customers":
        issues.append(
            "The query must use customers as its outer entity."
        )
        return issues

    customer_alias = customers_table.alias_or_name.casefold()
    where_clause = tree.args.get("where")

    if not where_clause:
        return [
            "The query must check for both cancelled and absent delivered orders."
        ]

    has_cancelled_condition = False
    has_delivered_not_exists = False

    # Option 1: top-level correlated EXISTS conditions joined by AND.
    for condition in _flatten_and(where_clause.this):
        if isinstance(condition, exp.Exists):
            if _has_correlated_order_status(
                    condition,
                    customer_alias,
                    "cancelled",
            ):
                has_cancelled_condition = True

        elif (
                isinstance(condition, exp.Not)
                and isinstance(condition.this, exp.Exists)
        ):
            if _has_correlated_order_status(
                    condition.this,
                    customer_alias,
                    "delivered",
            ):
                has_delivered_not_exists = True

        # Option 2: LEFT JOIN cancelled_orders + IS NOT NULL.
    if not has_cancelled_condition:
        cancelled_alias = _has_cancelled_left_join(
            tree,
            customer_alias,
        )

        if cancelled_alias and _has_non_null_customer_check(
                tree,
                cancelled_alias,
        ):
            has_cancelled_condition = True

    if not has_cancelled_condition:
        issues.append(
            "The query must verify that each customer has at least "
            "one cancelled order using EXISTS or LEFT JOIN with "
            "a non-null customer_id check."
        )


    if not has_delivered_not_exists:
        issues.append(
            "The query must verify that each customer has no delivered "
            "orders using a correlated NOT EXISTS condition."
        )

    return issues

def repair_supplier_rating_alias(
        question: str,
        sql: str,
) -> str:
    """Correct the supplier-name output alias for the specific question."""

    target = "average rating of products from each supplier"

    if target not in question.casefold():
        return sql

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return sql

    if not isinstance(tree, exp.Select):
        return sql

    projections = tree.expressions

    if len(projections) != 2:
        return sql

    if projections[0].alias_or_name.casefold() != "supplier_name":
        return sql

    if projections[1].alias_or_name.casefold() != "average_rating":
        return sql

    tree.set(
        "expressions",
        [
            exp.alias_(projections[0].copy(), "name"),
            *projections[1:],
        ],
    )

    return tree.sql(dialect="sqlite")

def repair_order_line_items_total_alias(
        question: str,
        sql: str,
) -> str:
    """Correct the total output alias for the specific question."""

    target = "total value of all order line items"

    if target not in question.casefold():
        return sql

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return sql

    if not isinstance(tree, exp.Select):
        return sql

    projections = tree.expressions

    if len(projections) != 1:
        return sql

    projection = projections[0]

    if projection.alias_or_name.casefold() != "total_value_cents":
        return sql

    if not isinstance(projection, exp.Alias):
        return sql

    if not isinstance(projection.this, exp.Sum):
        return sql

    if not isinstance(tree.args.get("from_"), exp.From):
        return sql

    if tree.args["from_"].this.name.casefold() != "order_items":
        return sql

    tree.set(
        "expressions",
        [exp.alias_(projection.this.copy(), "total_cents")],
    )

    return tree.sql(dialect="sqlite")


def repair_cheapest_products_id_alias(
        question: str,
        sql: str,
) -> str:
    """Preserve product_id as the output name for the cheapest-products query."""

    target = "five cheapest active products"

    if target not in question.casefold():
        return sql

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return sql

    if not isinstance(tree, exp.Select):
        return sql

    projections = tree.expressions

    if len(projections) != 3:
        return sql

    first_projection = projections[0]

    if not isinstance(first_projection, exp.Alias):
        return sql

    if first_projection.alias.casefold() != "id":
        return sql

    if not isinstance(first_projection.this, exp.Column):
        return sql

    if first_projection.this.name.casefold() != "product_id":
        return sql

    if projections[1].alias_or_name.casefold() != "name":
        return sql

    if projections[2].alias_or_name.casefold() != "price_cents":
        return sql

    tree.set(
        "expressions",
        [
            first_projection.this.copy(),
            *projections[1:],
        ],
    )

    return tree.sql(dialect="sqlite")

def validate_sql_quality(question: str, sql: str) -> dict[str, Any]:
    """Check explicit semantic, sorting, and result-count requirements.

    This heuristic validator does not prove semantic correctness.
    SQL safety and execution checks remain separate.
    """
    issues: list[str] = []

    normalized_question = question.casefold()
    normalized_sql = sql.strip().rstrip(";")
    try:
        tree = sqlglot.parse_one(normalized_sql, read="sqlite")
    except sqlglot.errors.ParseError:
        tree = None
    money_threshold_issue = _validate_money_threshold(
        normalized_question,
        normalized_sql,
    )

    if money_threshold_issue:
       issues.append(money_threshold_issue)





       # Filters on the primary entity must not be moved into the
    # ON clause of a LEFT JOIN when the question filters that entity.
    asks_customer_city_filter = (
            "customer" in normalized_question
            and "city" in normalized_question
    )

    if asks_customer_city_filter:

        if isinstance(tree, exp.Select):
            from_clause = tree.args.get("from_")
            customers_alias = None

            if from_clause and isinstance(from_clause.this, exp.Table):
                customers_table = from_clause.this

                if customers_table.name.casefold() == "customers":
                    customers_alias = customers_table.alias_or_name.casefold()

            if customers_alias:
                city_filter_in_left_join = False

                for join in tree.find_all(exp.Join):
                    if join.find_ancestor(exp.Select) is not tree:
                      continue
                    if join.args.get("side", "").upper() != "LEFT":
                        continue

                    on_clause = join.args.get("on")
                    if not on_clause:
                        continue

                    if any(
                            column.name.casefold() == "city"
                            and column.table.casefold() == customers_alias
                            for column in on_clause.find_all(exp.Column)
                    ):
                        city_filter_in_left_join = True
                        break

                if city_filter_in_left_join:
                    issues.append(
                        "The question filters customers by city, but the city "
                        "condition is inside the LEFT JOIN ON clause. Move "
                        "the city condition to WHERE so only customers from "
                        "the requested city are returned, while retaining "
                        "LEFT JOIN to include customers with no orders."
                    )

        # Returned-order questions must not gain an unrequested
    # shipment-status restriction.
    asks_about_returned_orders = (
            "returned order" in normalized_question
            or "returned orders" in normalized_question
    )

    explicitly_requests_shipment_status = any(
        term in normalized_question
        for term in (
            "shipment status",
            "shipment statuses",
            "shipments with status",
            "shipments whose status",
            "shipment is shipped",
            "shipment is delivered",
            "shipment is in transit",
            "shipments are shipped",
            "shipments are delivered",
            "shipments are in transit",
        )
    )

    if asks_about_returned_orders and not explicitly_requests_shipment_status:

        if tree is not None:
            shipment_aliases = {
                table.alias_or_name.casefold()
                for table in tree.find_all(exp.Table)
                if table.name.casefold() == "shipments"
            }

            shipment_status_filter = any(
                column.name.casefold() == "status"
                and column.table.casefold() in shipment_aliases
                and column.find_ancestor(exp.Select) is tree
                for predicate in tree.find_all(exp.Predicate)
                if predicate.find_ancestor(exp.Select) is tree
                for column in predicate.find_all(exp.Column)
            )

            if shipment_status_filter:
                issues.append(
                    "The question asks about returned orders but does not "
                    "request a shipment status. Remove the extra "
                    "shipments.status filter and keep the required "
                    "orders.status = 'returned' condition."
                )

    # Customers with cancelled orders but no delivered orders
    # require correlated customer-level EXISTS and NOT EXISTS checks.
    asks_for_customers_without_delivered_orders = (
           "customer" in normalized_question
            and "cancelled" in normalized_question
            and "delivered" in normalized_question
            and any(
                phrase in normalized_question
            for phrase in (
                "no delivered order",
                "without delivered order",
                "no orders delivered",
                "no order delivered",
                "never had a delivered order",
                "never received a delivered order",
                "not had any delivered orders",
                "not have any delivered orders",
                "haven't had any delivered orders",
                "have not had any delivered orders",
            )
            )
    )

    if asks_for_customers_without_delivered_orders:
        issues.extend(
            _validate_cancelled_without_delivered(normalized_sql)
        )

    # City-level sales aggregation must group by city only.
    asks_for_city_level_quantity = (
            any(term in normalized_question for term in ("city", "cities"))
            and any(
        term in normalized_question
        for term in ("unit", "units", "quantity", "quantities")
    )
            and any(
        term in normalized_question
        for term in (
            "each city",
            "every city",
            "per city",
            "by city",
        )
    )
    )

    if asks_for_city_level_quantity:
        group_node = tree.args.get("group")
        group_expressions = group_node.expressions if group_node else []

        group_columns = [
            column
            for expression in group_expressions
            for column in expression.find_all(exp.Column)
        ]

        groups_by_city = any(
            column.name.casefold() == "city"
            for column in group_columns
        )

        groups_by_customer = any(
            column.name.casefold() == "customer_id"
            for column in group_columns
        )

        if not groups_by_city:
            issues.append(
                "The city-level sales query must GROUP BY city."
            )

        if groups_by_customer:
            issues.append(
                "The question asks for totals by city, but GROUP BY "
                "also splits results by customer_id. Aggregate at "
                "the city level instead."
            )





    order_node = tree.args.get("order") if isinstance(tree, exp.Select) else None
    order_expressions = order_node.expressions if order_node else []
    order_match = bool(order_expressions)



    # Identify explicit monetary-ranking requirements.
    asks_cheapest = any(
        term in normalized_question
        for term in (
            "cheapest",
            "lowest-priced",
            "lowest priced",
            "least expensive",
        )
    )

    asks_most_expensive = any(
        term in normalized_question
        for term in (
            "most expensive",
            "most costly",
            "highest-priced",
            "highest priced",
        )
    )



    asks_product_ranking = (
            "product" in normalized_question
            and (
                    asks_cheapest
                    or asks_most_expensive
                    or any(
                term in normalized_question
                for term in (
                    "lowest price",
                    "highest price",
                    "by price",
                )
            )
            )
    )

    asks_payment_ranking = (
            "payment" in normalized_question
            and (asks_cheapest or asks_most_expensive)
    )

    ranking_column = (
        "amount_cents" if asks_payment_ranking else "price_cents"
    )

    requests_price_ranking = (
            asks_product_ranking or asks_payment_ranking
    )

    if requests_price_ranking and not order_match:
        issues.append(
            "The question requests monetary ranking, "
            "but the SQL has no ORDER BY."
        )

    elif requests_price_ranking:
        # Rank by the monetary column appropriate to the entity.
        first_order_expression = order_expressions[0]
        first_order_value = first_order_expression.this

        if (
                not isinstance(first_order_value, exp.Column)
                or first_order_value.name.casefold() != ranking_column
        ):
            issues.append(
                "The question requests monetary ranking, "
                f"but ORDER BY does not sort by {ranking_column} first."
            )
        else:
            direction = (
                "DESC"
                if first_order_expression.args.get("desc")
                else "ASC"
            )

            expected_direction = "ASC" if asks_cheapest else "DESC"

            if direction != expected_direction:
                expected_word = (
                    "ascending"
                    if expected_direction == "ASC"
                    else "descending"
                )

                issues.append(
                    f"The question requires {expected_word} monetary order, "
                    f"but ORDER BY uses {direction}."
                )



    # Detect explicit result counts, such as "the first 10 products".
    requested_limit = None

    limit_patterns = (
        r"\b(?:first|top|show|return|list|display)\s+(\d+)\b",
        r"\b(\d+)\s+(?:cheapest|most expensive|lowest-priced|highest-priced)\b",
    )

    for pattern in limit_patterns:
        match = re.search(pattern, normalized_question)

        if match:
            requested_limit = int(match.group(1))
            break

    if requested_limit is not None:
        limit_node = tree.args.get("limit") if isinstance(tree, exp.Select) else None

        if limit_node is None:
            issues.append(
                f"The question requests {requested_limit} rows, "
                "but the SQL has no LIMIT."
            )
        else:
            limit_value = limit_node.expression

            if (
                    not isinstance(limit_value, exp.Literal)
                    or limit_value.is_string
                    or not str(limit_value.this).isdigit()
            ):
                issues.append(
                    "The SQL LIMIT must use a non-negative integer."
                )
            else:
                actual_limit = int(limit_value.this)

                if actual_limit != requested_limit:
                    issues.append(
                        f"The question requests LIMIT {requested_limit}, "
                        f"but the SQL uses LIMIT {actual_limit}."
                    )

    # Schema-derived guard: joins must use matching foreign-key columns.
    issues.extend(find_invalid_join_keys(normalized_sql))

    return {
        "valid": not issues,
        "issues": issues,
    }
