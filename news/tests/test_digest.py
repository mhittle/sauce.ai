import os
import sys
import types
from datetime import datetime

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(HERE, "jobs")
if JOBS not in sys.path:
    sys.path.insert(0, JOBS)


class _FakeCursor:
    """Records (sql, params) of the last execute(); returns the staged result."""
    def __init__(self, result=None):
        self._result = result if result is not None else []
        self.last_sql = None
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, cursors):
        self._cursors = list(cursors)

    def cursor(self):
        return self._cursors.pop(0)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _sample_articles(n=3):
    return [
        {
            "id": i + 1,
            "title": f"Article {i+1}",
            "summary": f"Summary <em>body</em> for article {i+1} with enough text to be useful.",
            "url": f"https://example.com/a{i+1}",
            "byline": "By Reporter",
            "published_at": datetime(2026, 5, 13, 9, 0, 0),
            "source_name": f"Source {i+1}",
            "category": "world",
            "score": 1.5 - 0.1 * i,
        }
        for i in range(n)
    ]


def test_select_articles_uses_lookback_and_limit():
    from send_digest import select_articles

    cur = _FakeCursor(result=_sample_articles(2))
    conn = _FakeConn([cur])

    weights = {"objectivity": 1.0, "objectivity_direction": 1.0}
    rows = select_articles(conn, weights, lookback_hours=24, limit=5)

    assert len(rows) == 2
    assert "INTERVAL %(lookback_hours)s HOUR" in cur.last_sql
    assert "f.objectivity" in cur.last_sql
    assert cur.last_params["lookback_hours"] == 24
    assert cur.last_params["limit"] == 5
    assert cur.last_params["objectivity_w"] == 1.0
    assert cur.last_params["objectivity_d"] == 1.0


def test_select_articles_empty_weights_still_runs():
    from send_digest import select_articles

    cur = _FakeCursor(result=[])
    conn = _FakeConn([cur])

    rows = select_articles(conn, {}, lookback_hours=24, limit=8)
    assert rows == []
    assert "ORDER BY score DESC" in cur.last_sql


def test_render_digest_html_and_text_have_articles_and_unsubscribe():
    from app.config import Config

    from send_digest import render_digest, _build_jinja_env

    env = _build_jinja_env()
    articles = _sample_articles(3)

    msg = render_digest(env, "reader@example.com", articles, "abc123token", Config)

    assert msg["To"] == "reader@example.com"
    assert msg["Subject"].startswith("sauce.ai/news")
    assert "abc123token" in msg["List-Unsubscribe"]

    parts = msg.get_payload()
    assert len(parts) == 2
    plain = parts[0].get_payload(decode=True).decode("utf-8")
    html = parts[1].get_payload(decode=True).decode("utf-8")

    for a in articles:
        assert a["title"] in plain
        assert a["title"] in html
        assert a["url"] in plain
        assert a["url"] in html
        assert a["source_name"] in html

    # Unsubscribe link present in both parts.
    assert "abc123token" in plain
    assert "abc123token" in html
    # striptags drops the <em>.
    assert "<em>" not in plain


def test_render_digest_subject_includes_article_count():
    from app.config import Config
    from send_digest import render_digest, _build_jinja_env

    env = _build_jinja_env()
    msg = render_digest(env, "r@example.com", _sample_articles(5), "tok", Config)
    assert "5 stories" in msg["Subject"]


def test_smtp_send_uses_starttls_when_configured(monkeypatch):
    from send_digest import smtp_send

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def ehlo(self):
            sent.setdefault("ehlo_count", 0)
            sent["ehlo_count"] += 1

        def starttls(self):
            sent["starttls"] = True

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def sendmail(self, from_addr, to_addrs, body):
            sent["sendmail"] = (from_addr, to_addrs, body[:100])

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr("app.mailer.smtplib.SMTP", FakeSMTP)

    cfg = types.SimpleNamespace(
        SMTP_HOST="smtp.example.com", SMTP_PORT=587,
        SMTP_USE_TLS=True, SMTP_USER="u", SMTP_PASSWORD="p",
    )

    class FakeMsg:
        def as_string(self):
            return "BODY"

    smtp_send(cfg, "from@example.com", "to@example.com", FakeMsg())

    assert sent["host"] == "smtp.example.com"
    assert sent["port"] == 587
    assert sent.get("starttls") is True
    assert sent.get("login") == ("u", "p")
    assert sent["sendmail"][0] == "from@example.com"
    assert sent["sendmail"][1] == ["to@example.com"]
    assert sent.get("quit") is True


def test_smtp_send_plain_local_mta(monkeypatch):
    from send_digest import smtp_send

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port

        def ehlo(self):
            pass

        def starttls(self):
            sent["starttls"] = True  # should not be called

        def login(self, *a):
            sent["login"] = a  # should not be called

        def sendmail(self, *a):
            sent["sendmail"] = True

        def quit(self):
            pass

    monkeypatch.setattr("app.mailer.smtplib.SMTP", FakeSMTP)

    cfg = types.SimpleNamespace(
        SMTP_HOST="localhost", SMTP_PORT=25,
        SMTP_USE_TLS=False, SMTP_USER="", SMTP_PASSWORD="",
    )

    class FakeMsg:
        def as_string(self):
            return "BODY"

    smtp_send(cfg, "from@example.com", "to@example.com", FakeMsg())

    assert "starttls" not in sent
    assert "login" not in sent
    assert sent.get("sendmail") is True
