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

    FEED_JITTER = float(os.environ.get("FEED_JITTER", "0.10"))
    # BUG-021: cap how many articles a single source can occupy in one
    # page of `/`. 0 disables the cap.
    FEED_MAX_PER_SOURCE = int(os.environ.get("FEED_MAX_PER_SOURCE", "3"))

    # /trending page. WINDOW_DAYS mirrors trending_poll's default (the
    # cron only persists matches for in-window articles). MIN_SOURCES is
    # the "topics that hit N outlets" floor that filters out
    # one-headline noise.
    TRENDING_WINDOW_DAYS = int(os.environ.get("TRENDING_WINDOW_DAYS", "2"))
    TRENDING_MIN_SOURCES = int(os.environ.get("TRENDING_MIN_SOURCES", "2"))
    TRENDING_PAGE_LIMIT = int(os.environ.get("TRENDING_PAGE_LIMIT", "40"))
    TRENDING_STORIES_PER_TOPIC = int(os.environ.get("TRENDING_STORIES_PER_TOPIC", "3"))

    CSRF_ENABLED = os.environ.get("CSRF_ENABLED", "1") not in ("0", "false", "False")
    AUTH_RATELIMIT_MAX = int(os.environ.get("AUTH_RATELIMIT_MAX", "10"))
    AUTH_RATELIMIT_WINDOW_SECONDS = int(os.environ.get("AUTH_RATELIMIT_WINDOW_SECONDS", "300"))

    ARTICLE_RETENTION_DAYS = int(os.environ.get("ARTICLE_RETENTION_DAYS", "30"))
    BODY_RETENTION_DAYS = int(os.environ.get("BODY_RETENTION_DAYS", "30"))
    FEED_FETCH_BATCH = int(os.environ.get("FEED_FETCH_BATCH", "20"))
    CLASSIFY_BUDGET_SECONDS = int(os.environ.get("CLASSIFY_BUDGET_SECONDS", "240"))
    CLASSIFY_BATCH_LIMIT = int(os.environ.get("CLASSIFY_BATCH_LIMIT", "200"))

    SITE_URL = os.environ.get("SITE_URL", "https://sauce.ai/news").rstrip("/")
    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "0") in ("1", "true", "True")
    SMTP_FROM = os.environ.get("SMTP_FROM", "news@sauce.ai")
    DIGEST_MAX_ARTICLES = int(os.environ.get("DIGEST_MAX_ARTICLES", "8"))
    DIGEST_LOOKBACK_HOURS = int(os.environ.get("DIGEST_LOOKBACK_HOURS", "24"))
    DIGEST_RESEND_GUARD_HOURS = int(os.environ.get("DIGEST_RESEND_GUARD_HOURS", "20"))

    DISCOVER_PROMOTION_SCORE_MIN = int(os.environ.get("DISCOVER_PROMOTION_SCORE_MIN", "3"))
    DISCOVER_PROMOTE_BUDGET_SECONDS = int(os.environ.get("DISCOVER_PROMOTE_BUDGET_SECONDS", "1500"))
    DISCOVER_PROMOTE_WORKERS = int(os.environ.get("DISCOVER_PROMOTE_WORKERS", "8"))
    DISCOVER_PROMOTE_BATCH_LIMIT = int(os.environ.get("DISCOVER_PROMOTE_BATCH_LIMIT", "100"))
    DISCOVER_PROMOTE_REVALIDATE_DAYS = int(os.environ.get("DISCOVER_PROMOTE_REVALIDATE_DAYS", "14"))
    DISCOVER_LLM_CATEGORIES = os.environ.get(
        "DISCOVER_LLM_CATEGORIES", "world,politics,tech,science,business,sports"
    )
    DISCOVER_LLM_PER_CATEGORY = int(os.environ.get("DISCOVER_LLM_PER_CATEGORY", "10"))
