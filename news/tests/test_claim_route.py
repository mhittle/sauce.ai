"""Flask-layer tests for /claim. The DB and the model pipeline are stubbed;
no network, no API key."""
import pymysql
import pytest

from app import create_app
from app import claim
from app.classifier import LLMUnavailable


ABSTRACT = ("We randomized 1,204 adults. Relative risk 0.62 (95% CI 0.48 to 0.81). "
            "The event rate in the placebo group was 8.0%.")


def _result(status="ok"):
    fields = claim.validate_spans({
        "design": {"value": "rct", "span": "We randomized"},
        "n": {"value": 1204, "span": "1,204 adults"},
        "effect": {"type": "RR", "point": 0.62, "ci_low": 0.48, "ci_high": 0.81,
                   "span": "Relative risk 0.62 (95% CI 0.48 to 0.81)"},
        "baseline_risk": {"value": 0.08, "span": "placebo group was 8.0%"},
    }, ABSTRACT)
    if status == "no-study":
        flags = claim.merge_flags(["no-study-located"], [])
        return {"status": "no-study", "headline": "Chocolate cures cancer",
                "claim": {"claim": "Chocolate cures cancer", "claim_sentences": [],
                          "identifiers": {}, "source_kind": "blog", "mentions_study": False},
                "study": None, "fields": {}, "numbers": claim.absolute_effect(None, None),
                "flags": flags, "concordance": None, "concordance_why": "",
                "grade": 5, "usages": []}
    return {"status": "ok", "headline": "Aspirin cuts heart attack risk by 40%",
            "claim": {"claim": "Aspirin cuts heart attack risk", "claim_sentences": [],
                      "identifiers": {"doi": "10.1000/x"}, "source_kind": "news",
                      "mentions_study": True},
            "study": {"doi": "10.1000/x", "title": "Aspirin and MI", "journal": "BMJ",
                      "year": 2024, "first_author": "Smith", "abstract": ABSTRACT,
                      "is_preprint": False, "resolver": "crossref"},
            "fields": fields, "numbers": claim.absolute_effect(fields["effect"], 0.08),
            "flags": [], "concordance": 2, "concordance_why": "Matches.", "grade": 1,
            "usages": [{"model": "m", "input_tokens": 10, "output_tokens": 5,
                        "cache_read_tokens": 0, "est_cost_usd": 0.0001}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = create_app()
    app.config["ANTHROPIC_API_KEY"] = "test-key"
    return app.test_client()


class FakeDB:
    """Stands in for app.db.query / execute / get_conn inside the route.
    `missing_table=True` raises the 1146 ProgrammingError on every
    claim_checks statement, mimicking the pre-migration host."""

    def __init__(self, missing_table=False, rows=None):
        self.missing_table = missing_table
        self.rows = dict(rows or {})
        self.inserts = []
        self.usage_rows = []
        self.next_id = 100

    def _missing(self, sql):
        if self.missing_table and "claim_checks" in sql:
            raise pymysql.err.ProgrammingError(1146, "Table 'news.claim_checks' doesn't exist")

    def query(self, sql, params=None, one=False):
        self._missing(sql)
        s = " ".join(sql.split()).lower()
        if "count(*)" in s and "claim_checks" in s:
            return {"n": len(self.inserts)}
        if "from claim_checks where id" in s:
            return self.rows.get(int(params[0]))
        if "from claim_checks where url_hash" in s:
            for r in self.rows.values():
                if r.get("url_hash") == params[0]:
                    return r
            return None
        return None if one else []

    def execute(self, sql, params=None):
        self._missing(sql)
        if "insert into llm_usage" in sql.lower():
            self.usage_rows.append(params)
            return 1
        if "insert into claim_checks" in sql.lower():
            self.next_id += 1
            self.inserts.append(params)
            cols = ("url_hash", "input_kind", "headline", "source_url", "claim_json",
                    "study_json", "numbers_json", "flags_json", "grade", "status")
            row = dict(zip(cols, params))
            row["id"] = self.next_id
            row["created_at"] = None
            self.rows[self.next_id] = row
            return self.next_id
        return 0

    class _Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    def get_conn(self):
        return self._Conn()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr("app.routes.claim.query", fake.query)
    monkeypatch.setattr("app.routes.claim.execute", fake.execute)
    monkeypatch.setattr("app.routes.claim.get_conn", fake.get_conn)
    return fake


@pytest.fixture
def pipeline(monkeypatch):
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        outcome = calls_cfg.get("outcome", "ok")
        if outcome == "llm-down":
            raise LLMUnavailable("down")
        return _result(outcome)

    calls_cfg = {"outcome": "ok"}
    monkeypatch.setattr("app.routes.claim.run_check", fake_run)
    return {"calls": calls, "cfg": calls_cfg}


@pytest.fixture
def extractor(monkeypatch):
    state = {"status": "ok", "title": "Aspirin cuts heart attack risk by 40%",
             "body_text": "A study in the BMJ found " * 20}

    def fake_extract(url, **kwargs):
        return dict(state)

    monkeypatch.setattr("app.routes.claim.extract_body", fake_extract)
    return state


TEXT = ("Aspirin cuts heart attack risk by 40%\n"
        "A randomized trial published in the BMJ followed 1,204 adults for five years.")


def test_get_renders_form(client, db):
    r = client.get("/claim/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Check this claim" in body
    assert "not medical advice" in body


def test_post_bad_url_returns_inline_error_without_running(client, db, pipeline):
    r = client.post("/claim/", data={"url": "not a url"}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "look like a web address" in r.get_data(as_text=True)
    assert pipeline["calls"] == []


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1:8080/x", "https://10.0.0.5/secret",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data", "ftp://example.com/x",
    "https://[::1]/", "https://intranet.local/x", "example.com/no-scheme",
])
def test_post_refuses_non_public_urls(client, db, pipeline, url):
    r = client.post("/claim/", data={"url": url}, headers={"HX-Request": "true"})
    assert "look like a web address" in r.get_data(as_text=True)
    assert pipeline["calls"] == []


def test_post_empty_and_short_text(client, db, pipeline):
    r = client.post("/claim/", data={})
    assert "Paste a link or a headline" in r.get_data(as_text=True)
    r = client.post("/claim/", data={"text": "too short"})
    assert "at least a paragraph" in r.get_data(as_text=True)
    assert pipeline["calls"] == []


def test_post_text_runs_pipeline_saves_and_renders_card(client, db, pipeline):
    r = client.post("/claim/", data={"text": TEXT}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "1/5 grains of salt" in body
    assert "NNT = 33" in body
    assert "/claim/101" in body
    call = pipeline["calls"][0]
    assert call["headline"] == "Aspirin cuts heart attack risk by 40%"
    assert call["body"].startswith("A randomized trial")
    assert call["api_key"] == "test-key"
    assert call["model_extract"] == "claude-sonnet-5"
    assert len(db.inserts) == 1
    assert db.inserts[0][1] == "text" and db.inserts[0][0] is None
    assert len(db.usage_rows) == 1
    # Non-HTMX POST renders the full page with the card embedded.
    r = client.post("/claim/", data={"text": TEXT})
    assert "<form" in r.get_data(as_text=True) and "grains of salt" in r.get_data(as_text=True)


def test_post_url_extracts_then_caches_by_hash(client, db, pipeline, extractor):
    url = "https://example.com/news/aspirin?utm_source=x"
    r = client.post("/claim/", data={"url": url}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "grains of salt" in r.get_data(as_text=True)
    assert len(pipeline["calls"]) == 1
    assert pipeline["calls"][0]["headline"] == extractor["title"]
    assert db.inserts[0][0] == claim.url_hash(url)
    assert db.inserts[0][1] == "url"
    # Same link (different tracking params) -> cache hit, no second run.
    r = client.post("/claim/", data={"url": "https://example.com/news/aspirin?utm_source=y"},
                    headers={"HX-Request": "true"})
    assert "grains of salt" in r.get_data(as_text=True)
    assert len(pipeline["calls"]) == 1


def test_post_url_unreadable_page(client, db, pipeline, extractor):
    extractor["status"] = "blocked"
    extractor["body_text"] = None
    r = client.post("/claim/", data={"url": "https://example.com/paywalled"})
    assert "read that page" in r.get_data(as_text=True)
    assert pipeline["calls"] == []


def test_no_study_is_a_first_class_outcome(client, db, pipeline):
    pipeline["cfg"]["outcome"] = "no-study"
    r = client.post("/claim/", data={"text": TEXT}, headers={"HX-Request": "true"})
    body = r.get_data(as_text=True)
    assert "5/5 grains of salt" in body
    assert "No study could be located" in body
    assert db.inserts[0][-1] == "no-study"


def test_llm_unavailable_renders_inline_and_does_not_persist(client, db, pipeline):
    pipeline["cfg"]["outcome"] = "llm-down"
    r = client.post("/claim/", data={"text": TEXT}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "check this one right now" in r.get_data(as_text=True)
    assert db.inserts == []


def test_ip_rate_limit_trips(client, db, pipeline, monkeypatch):
    client.application.config["CLAIM_RATE_PER_IP_HOUR"] = 2
    for _ in range(2):
        r = client.post("/claim/", data={"text": TEXT})
        assert "grains of salt" in r.get_data(as_text=True)
    r = client.post("/claim/", data={"text": TEXT})
    body = r.get_data(as_text=True)
    assert "checked 2 headlines this hour" in body
    assert "alert-warn" in body
    assert len(pipeline["calls"]) == 2


def test_daily_cap_trips(client, db, pipeline):
    client.application.config["CLAIM_DAILY_CAP"] = 1
    client.post("/claim/", data={"text": TEXT})
    r = client.post("/claim/", data={"text": TEXT})
    assert "checking budget" in r.get_data(as_text=True)
    assert len(pipeline["calls"]) == 1


def test_missing_table_degrades_to_unsaved_card(client, db, pipeline):
    db.missing_table = True
    r = client.post("/claim/", data={"text": TEXT}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "grains of salt" in body
    assert "Permalink" not in body
    assert db.inserts == []
    # and the permalink route 404s cleanly rather than 500ing
    assert client.get("/claim/1").status_code == 404


def test_permalink_renders_saved_row_and_404s_unknown(client, db, pipeline):
    client.post("/claim/", data={"text": TEXT})
    r = client.get("/claim/101")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Aspirin cuts heart attack risk" in body
    assert "1/5 grains of salt" in body
    assert "NNT = 33" in body
    assert "Show abstract sources" in body
    assert client.get("/claim/999").status_code == 404
    assert client.get("/claim/abc").status_code == 404


def test_disabled_flag(client, db, pipeline):
    client.application.config["CLAIM_ENABLED"] = False
    r = client.post("/claim/", data={"text": TEXT})
    assert "currently disabled" in r.get_data(as_text=True)
    assert pipeline["calls"] == []


def test_nav_link_present_for_anonymous(client, db):
    body = client.get("/claim/").get_data(as_text=True)
    assert 'href="/claim/"' in body
