from pathlib import Path

from app.config import on_mounted_volume, resolve_data_dir


def test_railway_volume_wins_over_ephemeral_dir(monkeypatch, tmp_path):
    vol = tmp_path / "vol"
    vol.mkdir()
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(vol))
    monkeypatch.setenv("DATASETS_DATA_DIR", "./data")          # pasted from .env.example
    assert resolve_data_dir() == vol
    monkeypatch.setenv("DATASETS_DATA_DIR", str(vol / "catalog"))  # inside the volume: kept
    assert resolve_data_dir() == vol / "catalog"
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH")
    monkeypatch.setenv("DATASETS_DATA_DIR", "/tmp/x")
    assert resolve_data_dir() == Path("/tmp/x")


def test_mount_detection():
    assert on_mounted_volume(Path("/proc/self")) is True       # /proc is its own mount
    assert isinstance(on_mounted_volume(Path("/definitely/not/here")), bool)


def test_health_reports_storage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.store import Store
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    settings = Settings(data_dir=tmp_path)
    store = Store(settings.db_path)
    Store(settings.db_path)                                    # second open (a "redeploy")
    st = TestClient(create_app(settings, store)).get("/health").json()["storage"]
    assert st["opens"] >= 2 and st["catalog_created_at"]
    if not st["on_mounted_volume"]:
        assert st["persistent"] is False                       # on Railway, not a volume
