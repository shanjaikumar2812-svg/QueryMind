"""Home, upload, dashboard, and workspace routes."""

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.dataset import Dataset
from app.models.session import Session as WorkspaceSession
from app.services.ingestion_service import IngestionError, ingest_csv
from app.utils.helpers import new_id
from app.utils.logger import get_logger

main_bp = Blueprint("main", __name__)
logger = get_logger(__name__)


def _get_or_create_session_id() -> str:
    """QueryMind uses a lightweight, login-free session tracked via cookie."""
    session_id = session.get("qm_session_id")
    if not session_id or not WorkspaceSession.query.get(session_id):
        session_id = new_id("sess_")
        db.session.add(WorkspaceSession(id=session_id))
        db.session.commit()
        session["qm_session_id"] = session_id
    return session_id


@main_bp.route("/")
def home():
    session_id = _get_or_create_session_id()
    datasets = Dataset.query.filter_by(session_id=session_id).order_by(Dataset.uploaded_at.desc()).all()
    if datasets:
        return redirect(url_for("main.dashboard"))
    return render_template("pages/upload.html")


@main_bp.route("/upload", methods=["POST"])
def upload():
    session_id = _get_or_create_session_id()

    if "file" not in request.files:
        return jsonify({"error": "No file part in the request."}), 400
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    try:
        meta = ingest_csv(file, session_id)
    except IngestionError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Unexpected ingestion failure")
        return jsonify({"error": f"Unexpected error during upload: {exc}"}), 500

    dataset = Dataset(
        id=meta["id"],
        session_id=meta["session_id"],
        original_filename=meta["original_filename"],
        table_name=meta["table_name"],
        db_path=meta["db_path"],
        row_count=meta["row_count"],
        column_count=meta["column_count"],
        file_size_bytes=meta["file_size_bytes"],
    )
    dataset.columns = meta["columns"]
    db.session.add(dataset)
    db.session.commit()

    return jsonify({"dataset": dataset.to_dict(), "redirect": url_for("main.workspace", dataset_id=dataset.id)}), 201


@main_bp.route("/dashboard")
def dashboard():
    session_id = _get_or_create_session_id()
    datasets = Dataset.query.filter_by(session_id=session_id).order_by(Dataset.uploaded_at.desc()).all()
    return render_template("pages/dashboard.html", datasets=[d.to_dict() for d in datasets], session_id=session_id)


@main_bp.route("/workspace/<dataset_id>")
def workspace(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    return render_template("pages/workspace.html", dataset=dataset.to_dict())


@main_bp.route("/api/datasets/<dataset_id>", methods=["DELETE"])
def delete_dataset(dataset_id):
    import os
    dataset = Dataset.query.get_or_404(dataset_id)
    db_path = dataset.db_path
    db.session.delete(dataset)
    db.session.commit()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except OSError as exc:
        logger.warning("Could not remove dataset file %s: %s", db_path, exc)
    return jsonify({"deleted": dataset_id})
