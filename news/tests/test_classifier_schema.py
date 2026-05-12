from app.classifier.schema import SYSTEM_PROMPT, USER_TEMPLATE, render_articles_block


def test_render_articles_block():
    items = [
        (1, "Reuters", 0.0, "Markets up", "Stocks rose"),
        (2, "Fox News", 0.6, "Op-ed: dems wrong", "An opinion piece."),
    ]
    out = render_articles_block(items)
    assert "id: 1" in out
    assert "id: 2" in out
    assert "Reuters" in out
    assert "lean=+0.60" in out


def test_user_template_has_placeholders():
    rendered = USER_TEMPLATE.format(n=3, articles="X")
    assert "3" in rendered
    assert "X" in rendered


def test_system_prompt_demands_json():
    assert "JSON" in SYSTEM_PROMPT
    assert "results" in SYSTEM_PROMPT
