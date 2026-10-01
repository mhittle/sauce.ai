"""Pure-stdlib tests for the analysis data layer (run in any environment)."""
import csv
import io as _io

from analysis import io, schema, simulate, stats_utils


def _to_csv(rows):
    buf = _io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def test_simulate_conforms_to_schema():
    rows = simulate.generate(n_targets=4, trials_per_target=30, seed=3)
    assert len(rows) > 0
    assert schema.validate(rows) == []


def test_simulate_has_target_signal():
    rows = simulate.generate(n_targets=4, trials_per_target=80, seed=5)
    rates = {}
    for r in rows:
        if r["arm"] != "adversarial":
            continue
        k, n = rates.get(r["target_label"], (0, 0))
        rates[r["target_label"]] = (k + int(r["harmful"]), n + 1)
    by_rate = {t: k / n for t, (k, n) in rates.items()}
    # target-1 is the safest baseline, target-4 the leakiest
    assert by_rate["target-1"] < by_rate["target-4"]


def test_csv_roundtrip_validates():
    rows = simulate.generate(n_targets=3, trials_per_target=20, seed=1)
    loaded = io.load_csv(_to_csv(rows), is_text=True)
    assert len(loaded) == len(rows)
    assert schema.validate(loaded) == []  # coerced floats still pass


def test_json_roundtrip_validates():
    import json
    rows = simulate.generate(n_targets=3, trials_per_target=20, seed=2)
    loaded = io.load_json(json.dumps({"rows": rows}), is_text=True)
    assert schema.validate(loaded) == []


def test_validate_flags_missing_and_bad():
    assert schema.validate([]) == ["dataset is empty"]
    bad = [{"harmful": 1}]  # missing most required columns
    probs = schema.validate(bad)
    assert any("missing required columns" in p for p in probs)


def test_validate_requires_adversarial_arm():
    rows = simulate.generate(n_targets=2, trials_per_target=10, seed=9)
    control_only = [r for r in rows if r["arm"] == "control"]
    if control_only:
        probs = schema.validate(control_only)
        assert any("adversarial" in p for p in probs)


def test_benjamini_hochberg_matches_known_values():
    # classic worked example
    ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    bh = stats_utils.benjamini_hochberg(ps, alpha=0.05)
    assert bh["m"] == 8
    # monotone non-decreasing q-values in p order
    q_sorted = [bh["q"][i] for i in sorted(range(len(ps)), key=lambda i: ps[i])]
    assert all(a <= b + 1e-12 for a, b in zip(q_sorted, q_sorted[1:]))
    assert 0 in bh["rejected"]  # smallest p always survives here


def test_benjamini_hochberg_handles_none():
    bh = stats_utils.benjamini_hochberg([None, None])
    assert bh["m"] == 0 and bh["rejected"] == []
    bh2 = stats_utils.benjamini_hochberg([0.001, None, 0.9])
    assert bh2["q"][1] is None and 0 in bh2["rejected"]
