import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


MAX_ROWS = 100
ALLOWED_TABLES = frozenset({
    "federated.sales.metis_won_opps_fact",
    "federated.sales.metis_opened_opps_fact",
    "federated.sales.metis_targets_summary",
})
ALLOWED_NODES = frozenset({
    "Select", "Union", "With", "CTE", "Subquery", "Table", "TableAlias", "Identifier",
    "Column", "Star", "Literal", "Null", "Boolean", "Alias", "From", "Join", "Where",
    "Group", "Having", "Order", "Ordered", "Limit", "Offset", "Distinct", "Paren",
    "And", "Or", "Not", "EQ", "NEQ", "GT", "GTE", "LT", "LTE", "Is", "In",
    "Between", "Like", "ILike", "Add", "Sub", "Mul", "Div", "Mod", "Neg",
    "Case", "If", "Cast", "TryCast", "DataType", "DataTypeParam", "Interval", "Var",
    "Window", "WindowSpec", "Filter", "Tuple",
})
ALLOWED_FUNCTIONS = frozenset({
    "SUM", "COUNT", "AVG", "MIN", "MAX", "ABS", "ROUND", "COALESCE", "NULLIF",
    "CAST", "TRY_CAST", "IF", "CASE", "LOWER", "UPPER", "TRIM", "LENGTH",
    "CURRENT_DATE", "CURRENT_TIMESTAMP", "DATE", "DATE_TRUNC", "TIMESTAMP_TRUNC",
    "DATE_ADD", "DATE_SUB", "DATE_DIFF", "DATEDIFF", "ADD_MONTHS", "YEAR", "MONTH",
    "QUARTER", "DAY", "DAY_OF_MONTH", "DAY_OF_WEEK", "WEEK_OF_YEAR", "LAST_DAY",
    "TIME_TO_STR", "TS_OR_DS_TO_DATE", "TS_OR_DS_ADD", "ROW_NUMBER", "RANK",
    "DENSE_RANK", "LAG", "LEAD", "GREATEST", "LEAST", "EXTRACT", "FLOOR", "CEIL",
})


def prepare_read_only_sql(statement: str) -> str:
    if not isinstance(statement, str) or not statement.strip() or len(statement) > 20000:
        raise ValueError("Invalid SQL query")
    try:
        statements = sqlglot.parse(statement, read="databricks")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise ValueError("Only one reporting SELECT query is allowed")
        query = statements[0]
        nodes = list(query.walk())
        if len(nodes) > 500:
            raise ValueError("Query is too complex")
        for node in nodes:
            if isinstance(node, exp.Func):
                if isinstance(node, exp.Anonymous) or node.sql_name() not in ALLOWED_FUNCTIONS:
                    raise ValueError("Function is not approved for reporting")
            elif type(node).__name__ not in ALLOWED_NODES:
                raise ValueError("SQL construct is not approved for reporting")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise ValueError("Recursive queries are not allowed")
        for scope in traverse_scope(query):
            for _, source in scope.selected_sources.values():
                if isinstance(source, Scope):
                    continue
                if not isinstance(source, exp.Table) or any(not isinstance(part, exp.Identifier) for part in source.parts):
                    raise ValueError("Only approved reporting tables are allowed")
                name = ".".join(part.name.lower() for part in source.parts)
                if name not in ALLOWED_TABLES:
                    raise ValueError("Table is not approved for reporting")
        limit = query.args.get("limit")
        row_limit = MAX_ROWS
        if limit is not None:
            expression = limit.expression
            if not isinstance(expression, exp.Literal) or not expression.is_int:
                raise ValueError("LIMIT must be a nonnegative integer")
            row_limit = min(MAX_ROWS, max(0, int(expression.this)))
        return query.limit(row_limit).sql(dialect="databricks", comments=False)
    except (sqlglot.errors.SqlglotError, AttributeError, TypeError) as exc:
        raise ValueError("SQL could not be validated") from exc
