"""Methods & workflows guide page: content + route-coverage (no drift)."""
import re

from fastapi.testclient import TestClient

from app import guide
from app.config import Settings
from app.main import create_app
from app.runner import Runner
from app.store import Store


def _client():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    return TestClient(create_app(settings, store, Runner(settings, store, mocks={})))


def test_guide_renders_key_workflows():
    html = guide.render_html()
    for needle in ("Methods &amp; workflows", "Submit a red-team run", "Grader bias",
                   "Critical Harm Event", "Reproducibility capsule", "DALY burden",
                   "Confirmatory analysis", "Inspect", "inspect eval clinical_redteam.py"):
        assert needle in html, needle


def test_guide_endpoint():
    html = _client().get("/guide").text
    assert "Methods &amp; workflows" in html and "/grader-audit" in html


def test_every_http_path_in_guide_is_a_real_route():
    """The guide can't drift: every HTTP path it lists must be a registered route."""
    app = create_app(Settings(db_path=":memory:"), Store(":memory:"), None)
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    for p in guide.http_paths():
        assert p in routes, f"guide references unregistered route: {p}"


def test_guide_paths_are_well_formed():
    for p in guide.http_paths():
        assert p.startswith("/")
        # balanced path params
        assert p.count("{") == p.count("}")
        for name in re.findall(r"{([^}]+)}", p):
            assert name.isidentifier()
