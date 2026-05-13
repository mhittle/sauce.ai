import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    DB_USER = os.environ.get("DB_USER", "")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", "10"))
    CLASSIFIER_VERSION = os.environ.get("CLASSIFIER_VERSION", "v1")

    ARTICLE_RETENTION_DAYS = int(os.environ.get("ARTICLE_RETENTION_DAYS", "30"))
    BODY_RETENTION_DAYS = int(os.environ.get("BODY_RETENTION_DAYS", "30"))
    FEED_FETCH_BATCH = int(os.environ.get("FEED_FETCH_BATCH", "20"))
    CLASSIFY_BUDGET_SECONDS = int(os.environ.get("CLASSIFY_BUDGET_SECONDS", "90"))
    CLASSIFY_BATCH_LIMIT = int(os.environ.get("CLASSIFY_BATCH_LIMIT", "200"))
