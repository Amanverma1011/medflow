"""Validation and sandboxed execution for copilot SQL.

Three independent layers, any one of which blocks a bad query:
  1. validate()  - parsed with sqlglot: one SELECT, allow-listed tables, no risky functions.
  2. the DB role - SELECT-only with column-level grants (migration 0002).
  3. the session - READ ONLY transaction, statement timeout, hard row cap.
"""
import sqlglot
from sqlglot import exp
from sqlalchemy import text

from app.core.db import readonly_engine

MAX_ROWS = 200
ALLOWED_TABLES = {"departments", "doctors", "users", "patients", "appointments", "queues", "queue_entries", "wards",
                  "beds", "bed_assignments", "visits", "feedback", "complaints", "ai_insights"}
_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Copy,
                    exp.Set, exp.Transaction, exp.Commit, exp.Rollback, exp.Grant, exp.Into, exp.Lock)
_FORBIDDEN_FUNCTIONS = {"dblink", "dblink_exec", "lo_import", "lo_export", "set_config", "current_setting",
                        "query_to_xml", "copy", "txid_current", "nextval", "setval"}


class UnsafeSQL(ValueError):
    pass


def validate(sql: str) -> str:
    """Return a row-capped version of `sql`, or raise UnsafeSQL."""
    sql = sql.strip().rstrip(";").strip()
    if "--" in sql or "/*" in sql:
        raise UnsafeSQL("SQL comments are not allowed.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.SqlglotError:
        raise UnsafeSQL("The query could not be parsed.")
    if len(statements) != 1:
        raise UnsafeSQL("Exactly one statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise UnsafeSQL("Only SELECT queries are allowed.")
    if any(tree.find(node) for node in _FORBIDDEN_NODES):
        raise UnsafeSQL("The query contains a statement type that is not allowed.")
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.db or table.catalog:
            raise UnsafeSQL("Schema-qualified tables are not allowed.")
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeSQL(f"Table '{name}' is not available to the copilot.")
    for func in tree.find_all(exp.Func):
        name = (func.name or func.sql_name()).lower()
        if name.startswith("pg_") or name in _FORBIDDEN_FUNCTIONS:
            raise UnsafeSQL(f"Function '{name}' is not allowed.")
    # Execute the validated text itself rather than a re-rendering, so :name bind parameters survive.
    return f"SELECT * FROM (\n{sql}\n) AS copilot_result LIMIT {MAX_ROWS}"


def run_readonly(sql: str, params: dict | None = None) -> list[dict]:
    """Validate, then execute as the SELECT-only role inside a read-only transaction."""
    safe = validate(sql)
    with readonly_engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '5s'"))
        rows = conn.execute(text(safe), params or {}).mappings().all()
        conn.rollback()
    return [dict(r) for r in rows]
