"""SQL execution service: validates and runs generated SQL against a dataset's
per-file SQLite database, with a self-healing retry loop against the AI service.
"""

import sqlite3

from flask import current_app

from app.services import ai_service
from app.utils.helpers import rows_to_dicts
from app.utils.logger import get_logger
from app.utils.security import validate_sql

logger = get_logger(__name__)


class SQLExecutionError(Exception):
    """Raised when SQL fails validation or execution after all retries."""


def execute_sql(db_path: str, sql: str, table_name: str, limit: int = None):
    """Validate then run `sql` read-only against the dataset's SQLite file.

    Returns (columns, rows) on success. Raises SQLExecutionError otherwise.
    """
    is_valid, error = validate_sql(sql, table_name)
    if not is_valid:
        raise SQLExecutionError(error)

    limit = limit or current_app.config.get("SQL_STATEMENT_TIMEOUT_ROWS", 100000)

    # Open read-only via URI to guarantee no writes happen even if a check
    # above were somehow bypassed.
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    except sqlite3.OperationalError as exc:
        raise SQLExecutionError(f"Could not open dataset database: {exc}") from exc

    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(limit)
        return columns, rows
    except sqlite3.Error as exc:
        raise SQLExecutionError(str(exc)) from exc
    finally:
        conn.close()


def ask_and_run(question: str, dataset, nlp_hints: dict, sample_rows: list) -> dict:
    """Full NL -> SQL -> execution pipeline with self-healing retries.

    `dataset` is an app.models.dataset.Dataset instance.
    Returns a dict: {sql, columns, rows, retries, success, error}.
    """
    max_retries = current_app.config.get("AI_MAX_RETRIES", 3)
    previous_error = None
    previous_sql = None
    last_sql = None

    for attempt in range(1, max_retries + 1):
        try:
            sql = ai_service.generate_sql(
                question=question,
                table_name=dataset.table_name,
                columns=dataset.columns,
                sample_rows=sample_rows,
                nlp_hints=nlp_hints,
                previous_error=previous_error,
                previous_sql=previous_sql,
            )
            last_sql = sql
            columns, rows = execute_sql(dataset.db_path, sql, dataset.table_name)
            return {
                "sql": sql,
                "columns": columns,
                "rows": rows,
                "results": rows_to_dicts(columns, rows),
                "retries": attempt - 1,
                "success": True,
                "error": None,
            }
        except (SQLExecutionError, ai_service.AIServiceError) as exc:
            logger.warning("Attempt %s/%s failed: %s", attempt, max_retries, exc)
            previous_error = str(exc)
            previous_sql = last_sql
            continue

    return {
        "sql": last_sql,
        "columns": [],
        "rows": [],
        "results": [],
        "retries": max_retries,
        "success": False,
        "error": previous_error or "Failed to generate a valid query.",
    }
