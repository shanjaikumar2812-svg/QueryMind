"""QueryMind application factory."""

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template
from app.config import config_map
from app.extensions import db, cors


def create_app(config_name: str = "default") -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    app.config.from_object(config_map.get(config_name, config_map["default"]))

    # Ensure directories exist
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["EXPORT_DIR"], exist_ok=True)
    os.makedirs(app.config["LOG_DIR"], exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    cors.init_app(app)

    # Setup logging
    _setup_logging(app)

    # Register blueprints
    _register_blueprints(app)

    # Error handlers
    _register_error_handlers(app)

    # Create tables
    with app.app_context():
        db.create_all()

    return app


def _setup_logging(app: Flask) -> None:
    """Configure application logging."""
    log_level = getattr(logging, app.config["LOG_LEVEL"], logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        app.config["LOG_FILE"],
        maxBytes=10485760,  # 10MB
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    app.logger.addHandler(file_handler)
    app.logger.setLevel(log_level)


def _register_blueprints(app: Flask) -> None:
    """Register all Flask blueprints."""
    from app.routes.main import main_bp
    from app.routes.query import query_bp
    from app.routes.analytics import analytics_bp
    from app.routes.export import export_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(query_bp, url_prefix="/query")
    app.register_blueprint(analytics_bp, url_prefix="/analytics")
    app.register_blueprint(export_bp, url_prefix="/export")


def _register_error_handlers(app: Flask) -> None:
    """Register error handlers."""

    @app.errorhandler(400)
    def bad_request(e):
        return {"error": "Bad Request", "message": str(e)}, 400

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Not Found", "message": str(e)}, 404

    @app.errorhandler(413)
    def file_too_large(e):
        return {"error": "File Too Large", "message": "Maximum file size is 50MB"}, 413

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.error(f"Internal error: {e}")
        return {"error": "Internal Server Error", "message": "Something went wrong"}, 500
