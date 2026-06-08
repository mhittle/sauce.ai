import pytest

from app.adapters.paid import PaidApiAdapter
from app.adapters.registry import build_adapter


def test_paid_adapter_disabled_without_key():
    adapter = build_adapter({"source_type": "paid"})
    assert isinstance(adapter, PaidApiAdapter)
    assert adapter.enabled is False
    with pytest.raises(RuntimeError):
        list(adapter.fetch_raw())


def test_paid_adapter_enabled_with_key_not_implemented():
    adapter = build_adapter({"source_type": "paid"}, paid_api_key="k")
    assert adapter.enabled is True
    with pytest.raises(NotImplementedError):
        list(adapter.fetch_raw())
