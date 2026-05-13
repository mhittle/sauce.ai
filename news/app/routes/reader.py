"""In-app reader view at /read/<article_id>.

Renders the trafilatura-extracted body inside our own typography. When
extraction failed/empty/blocked, falls back to a stub with a "Read at
<source>" link to the original.
"""
from flask import Blueprint, abort, render_template

from ..db import query

bp = Blueprint("reader", __name__)


@bp.route("/read/<int:article_id>")
def read(article_id):
    row = query(
        """SELECT a.id, a.title, a.url, a.byline, a.published_at, a.thumbnail_url,
                  s.id AS source_id, s.name AS source_name, s.homepage,
                  f.political_lean, f.category,
                  b.body_text, b.lead_image, b.author, b.word_count,
                  b.status AS body_status, b.extracted_at
           FROM articles a
           JOIN sources s ON s.id = a.source_id
           LEFT JOIN article_features f ON f.article_id = a.id
           LEFT JOIN article_bodies b ON b.article_id = a.id
           WHERE a.id = %s""",
        (article_id,),
        one=True,
    )
    if not row:
        abort(404)

    paragraphs = []
    if row.get("body_text"):
        paragraphs = [p.strip() for p in row["body_text"].split("\n") if p.strip()]

    return render_template(
        "reader.html",
        article=row,
        paragraphs=paragraphs,
        has_body=bool(paragraphs),
    )
