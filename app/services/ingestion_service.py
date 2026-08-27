"""CSV ingestion: encoding detection, cleaning, and dynamic SQLite table creation.

Each uploaded CSV gets its own SQLite database file under DATA_DIR/databases/
so datasets never collide and can be dropped independently.
"""

import os
import sqlite3

import chardet
import pandas as pd
from flask import current_app
from werkzeug.datastructures import FileStorage

from app.utils.helpers import new_id
from app.utils.logger import get_logger
from app.utils.security import sanitize_filename, sanitize_identifier

logger = get_logger(__name__)


class IngestionError(Exception):
    """Raised when a CSV fails validation or cannot be ingested."""


def allowed_file(filename: str) -> bool:
    try:
        allowed_extensions = current_app.config["ALLOWED_EXTENSIONS"]
    except RuntimeError:
        allowed_extensions = {"csv"}
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in allowed_extensions


def _detect_encoding(raw_bytes: bytes) -> str:
    result = chardet.detect(raw_bytes[:200000])
    return result.get("encoding") or "utf-8"


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names, drop fully-empty rows/columns, coerce dtypes."""
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")

    seen = {}
    clean_cols = []
    for col in df.columns:
        base = sanitize_identifier(str(col))
        count = seen.get(base, 0)
        seen[base] = count + 1
        clean_cols.append(base if count == 0 else f"{base}_{count}")
    df.columns = clean_cols

    # Best-effort numeric/datetime coercion for object columns.
    for col in df.columns:
        if df[col].dtype == object:
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().mean() > 0.9:
                df[col] = coerced
                continue
            try:
                dt = pd.to_datetime(df[col], errors="coerce", format="mixed")
                if dt.notna().mean() > 0.9:
                    df[col] = dt
            except (ValueError, TypeError):
                pass

    return df


def ingest_csv(file: FileStorage, session_id: str) -> dict:
    """Read, clean, and persist an uploaded CSV into its own SQLite DB.

    Returns a dict of metadata ready to populate a Dataset row.
    """
    filename = sanitize_filename(file.filename or "upload.csv")
    if not allowed_file(filename):
        raise IngestionError("Only .csv files are supported.")

    raw = file.read()
    if not raw:
        raise IngestionError("Uploaded file is empty.")
    encoding = _detect_encoding(raw)

    from io import BytesIO
    try:
        df = pd.read_csv(BytesIO(raw), encoding=encoding, low_memory=False)
    except Exception as exc:  # pandas raises many exception subtypes for bad CSVs
        raise IngestionError(f"Could not parse CSV ({encoding}): {exc}") from exc

    max_rows = current_app.config["MAX_ROWS"]
    max_cols = current_app.config["MAX_COLUMNS"]
    if len(df) > max_rows:
        raise IngestionError(f"Dataset exceeds max row limit ({max_rows}).")
    if len(df.columns) > max_cols:
        raise IngestionError(f"Dataset exceeds max column limit ({max_cols}).")
    if len(df.columns) == 0:
        raise IngestionError("No columns detected in the uploaded file.")

    df = _clean_dataframe(df)

    dataset_id = new_id("ds_")
    table_name = f"tbl_{dataset_id}"
    db_filename = f"{dataset_id}.db"
    db_path = os.path.join(current_app.config["DATABASES_DIR"], db_filename)

    os.makedirs(current_app.config["DATABASES_DIR"], exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        df.to_sql(table_name, conn, if_exists="replace", index=False)
    finally:
        conn.close()

    columns_meta = [
        {"name": col, "dtype": str(df[col].dtype)} for col in df.columns
    ]

    logger.info("Ingested dataset %s (%s rows, %s cols) -> %s", dataset_id, len(df), len(df.columns), db_path)

    return {
        "id": dataset_id,
        "session_id": session_id,
        "original_filename": filename,
        "table_name": table_name,
        "db_path": db_path,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": columns_meta,
        "file_size_bytes": len(raw),
    }


def load_sample(df: pd.DataFrame, limit: int = 5) -> list:
    """Return a small JSON-serializable sample of rows for prompt context."""
    sample = df.head(limit).copy()
    for col in sample.columns:
        if pd.api.types.is_datetime64_any_dtype(sample[col]):
            sample[col] = sample[col].astype(str)
    return sample.where(pd.notnull(sample), None).to_dict(orient="records")
