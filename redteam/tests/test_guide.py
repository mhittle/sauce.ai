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


# -- launchers (interactive forms) ----------------------------------------------

def test_every_workflow_with_an_http_surface_has_a_launcher():
    ids = {w["id"] for g in guide.GROUPS for w in g["workflows"] if w.get("steps")}
    assert ids <= set(guide.FORMS), ids - set(guide.FORMS)


def test_launcher_paths_are_routes_and_path_params_have_fields():
    app = create_app(Settings(db_path=":memory:"), Store(":memory:"), None)
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    for forms in guide.FORMS.values():
        for f in forms:
            assert f["p"] in routes, f["p"]
            for name in re.findall(r"{([^}]+)}", f["p"]):
                assert any(x["n"] == name and x.get("path") for x in f["fields"]), (f["p"], name)
            if f["m"] == "POST":
                assert f.get("result"), f["p"]


def test_guide_renders_forms_and_marks_unavailable_panel_models():
    html = guide.render_html(available_models={"chatgpt-5"})
    assert html.count("<form") == sum(len(v) for v in guide.FORMS.values())
    assert 'name="target.api_key"' in html and 'type="password"' in html
    assert "(no key)" in html and 'value="chatgpt-5"' in html
    assert "fetch('/runs.json')" in html


def test_runs_json_lists_recent_runs_without_secrets():
    import sys
    sys.path.insert(0, "tests")
    from test_epi import _seed
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    c = TestClient(create_app(settings, store, Runner(settings, store, mocks={})))
    rid = _seed(store, "gpt-5", 0.3, seed=1)
    j = c.get("/runs.json").json()
    assert j["n"] == 1 and j["runs"][0]["run_id"] == rid
    r = j["runs"][0]
    assert r["label"] == "ChatGPT (GPT-5)" and r["specialty"] == "endocrinology" and r["status"] == "complete"
    assert r["email"].startswith("***") and "me@" not in r["email"]  # masked
    assert "api_key" not in str(j)
    assert "<form" in c.get("/guide").text
