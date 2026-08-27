"""Gemini integration: turns a natural-language question + schema into SQL.

Includes a self-healing retry loop — if the generated SQL fails validation
or execution, the error is fed back to Gemini for a corrected attempt.
"""

import re

import google.generativeai as genai
from flask import current_app

from app.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIGURED = False


class AIServiceError(Exception):
    """Raised when Gemini cannot produce a usable response."""


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    try:
        config = current_app.config
    except RuntimeError:
        config = {}

    api_key = config.get("GEMINI_API_KEY") if isinstance(config, dict) else None
    if not api_key:
        raise AIServiceError("GEMINI_API_KEY is not set. Add it to your .env file.")

    genai.configure(api_key=api_key)
    _CONFIGURED = True


def _build_schema_block(table_name: str, columns: list, sample_rows: list) -> str:
    col_lines = "\n".join(f"  - {c['name']} ({c['dtype']})" for c in columns)
    sample_block = "\n".join(str(row) for row in sample_rows[:3])
    return (
        f"Table name: {table_name}\n"
        f"Columns:\n{col_lines}\n\n"
        f"Sample rows:\n{sample_block}"
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(sql|SQL)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_sql(question: str, table_name: str, columns: list, sample_rows: list,
                  nlp_hints: dict = None, previous_error: str = None, previous_sql: str = None) -> str:
    """Ask Gemini for a single SQLite SELECT statement answering `question`."""
    _configure()
    model = genai.GenerativeModel(current_app.config["GEMINI_MODEL"])

    schema_block = _build_schema_block(table_name, columns, sample_rows)
    hint_line = ""
    if nlp_hints:
        hint_line = (
            f"\nDetected intent: {nlp_hints.get('intent')}. "
            f"Likely relevant columns: {nlp_hints.get('mentioned_columns')}.\n"
        )

    correction_block = ""
    if previous_error and previous_sql:
        correction_block = (
            f"\nYour previous SQL attempt failed.\n"
            f"Previous SQL:\n{previous_sql}\n"
            f"Error:\n{previous_error}\n"
            f"Fix the query and try again.\n"
        )

    prompt = f"""You are a SQLite expert. Convert the user's question into a single
read-only SELECT statement against the table described below. Respond with
ONLY the SQL statement — no explanation, no markdown fences, no semicolon-chained
statements. Never use INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.

{schema_block}
{hint_line}{correction_block}
Question: {question}

SQL:"""

    try:
        response = model.generate_content(prompt)
        sql = _strip_code_fences(response.text or "")
    except Exception as exc:
        logger.error("Gemini generation failed: %s", exc)
        raise AIServiceError(f"AI generation failed: {exc}") from exc

    if not sql:
        raise AIServiceError("Gemini returned an empty response.")
    return sql


def summarize_result(question: str, columns: list, rows: list, max_rows_for_prompt: int = 20) -> str:
    """Ask Gemini for a short plain-English summary of a query result."""
    _configure()
    model = genai.GenerativeModel(current_app.config["GEMINI_MODEL"])

    preview_rows = rows[:max_rows_for_prompt]
    prompt = f"""Question asked: {question}
Result columns: {columns}
Result rows (sample): {preview_rows}
Total rows returned: {len(rows)}

Write a 2-3 sentence plain-English summary of this result for a business
user. Do not restate the raw table. No markdown."""

    try:
        response = model.generate_content(prompt)
        return (response.text or "").strip()
    except Exception as exc:
        logger.warning("Summary generation failed, falling back to generic text: %s", exc)
        return f"Query returned {len(rows)} row(s) across {len(columns)} column(s)."
