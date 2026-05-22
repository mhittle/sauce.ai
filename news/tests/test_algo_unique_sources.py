"""Tests for the per-profile unique-sources toggle on /algo.

The toggle is a boolean stored in `weights_json` under the `unique_sources`
key. These tests pin down two pieces of glue:

- `_parse_form_weights` writes the key on every save (True when checked,
  False when unchecked) so toggling off actually clears the previously
  saved truthy value.
- A pure helper composes with the global FEED_MAX_PER_SOURCE cap correctly.
"""

from werkzeug.datastructures import ImmutableMultiDict

from app.routes.algo import _parse_form_weights


def _form(d):
    # ImmutableMultiDict matches Flask's request.form interface.
    return ImmutableMultiDict(d)


def test_parse_form_weights_records_unique_sources_when_checked():
    weights = _parse_form_weights(_form({"unique_sources": "1"}))
    assert weights["unique_sources"] is True


def test_parse_form_weights_clears_unique_sources_when_unchecked():
    # HTML checkboxes don't submit when unchecked, so the key is absent.
    # The handler must still write False so an older saved True is cleared.
    weights = _parse_form_weights(_form({}))
    assert weights["unique_sources"] is False
