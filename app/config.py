"""QueryMind application configuration."""

import os
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    """Like os.getenv, but treats an empty string in the .env file the
    same as an unset variable, so a blank `KEY=` line falls back to
    `default` instead of resolving to ''."""
    value = os.getenv(key)
    return value if value else default


class Config:
    """Base configuration."""

    SECRET_KEY = _env("SECRET_KEY", "dev-secret-key-change-in-production")
    GEMINI_API_KEY = _env("GEMINI_API_KEY", "")

    # Upload
    MAX_CONTENT_LENGTH = int(_env("MAX_CONTENT_LENGTH", "52428800"))  # 50MB
    MAX_ROWS = 500000
    MAX_COLUMNS = 200
    ALLOWED_EXTENSIONS = {"csv"}

    # Dataset storage
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    DATABASES_DIR = os.path.join(DATA_DIR, "databases")
    EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")
    LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

    # Database (master metadata DB — sessions, dataset registry, query history)
    SQLALCHEMY_DATABASE_URI = _env(
        "SQLALCHEMY_DATABASE_URI", f"sqlite:///{os.path.join(DATA_DIR, 'master.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Sample datasets
    SAMPLE_DATASETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_data")

    # Pagination
    RESULTS_PER_PAGE = 50

    # Gemini / AI
    GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")
    AI_MAX_RETRIES = 3  # self-healing SQL retry loop

    # Forecasting
    FORECAST_MIN_POINTS = 8
    FORECAST_DEFAULT_HORIZON = 12

    # Query safety
    SQL_STATEMENT_TIMEOUT_ROWS = 100000

    # Logging
    LOG_LEVEL = _env("LOG_LEVEL", "INFO")
    LOG_FILE = os.path.join(LOG_DIR, _env("LOG_FILE", "app.log"))

    # Pagination
    PAGE_SIZE = 50


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SECRET_KEY = os.getenv("SECRET_KEY")


class TestingConfig(Config):
    """Testing configuration — in-memory master DB, isolated tmp dirs."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
