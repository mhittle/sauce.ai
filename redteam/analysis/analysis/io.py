"""Load the tidy export (pure stdlib) and, lazily, hand it to pandas.

The service serves `/export/tidy.csv?runs=…&level=turn` and `/export/tidy.json`.
`load_csv` / `load_json` read those into a list of dict rows with no third-party
dependency, so the data contract can be validated anywhere. `to_frame` builds a
pandas DataFrame only when the model layer needs it.
"""
from __future__ import annotations

import csv
import io as _io
import json

from . import schema


def load_csv(path_or_text: str, *, is_text: bool = False) -> list[dict]:
    text = path_or_text if is_text else open(path_or_text, encoding="utf-8").read()
    rows = list(csv.DictReader(_io.StringIO(text)))
    return schema.coerce(rows)


def load_json(path_or_text: str, *, is_text: bool = False) -> list[dict]:
    text = path_or_text if is_text else open(path_or_text, encoding="utf-8").read()
    data = json.loads(text)
    rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
    return schema.coerce(rows)


def to_frame(rows: list[dict]):
    """Build a pandas DataFrame (lazy import). Adds analysis-ready columns:
    ``harmful`` as int, ``adversarial`` indicator, and trial-level ``any_harm``
    when absent."""
    import pandas as pd  # lazy: only needed for modelling

    df = pd.DataFrame(rows)
    if "harmful" in df:
        df["harmful"] = pd.to_numeric(df["harmful"], errors="coerce").fillna(0).astype(int)
    df["adversarial"] = (df.get("arm") == "adversarial").astype(int)
    for c in ("turn_idx", "n_turns_in_trial", "first_harm_turn", "p_harm", "seed"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
