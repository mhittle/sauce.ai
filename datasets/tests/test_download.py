import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import download
from app.config import Settings
from app.store import Store


@pytest.fixture()
def server(tmp_path):
    (tmp_path / "labels.csv").write_text("id,label\n1,ptx\n")
    (tmp_path / "big.csv").write_text("x" * 5000)
    (tmp_path / "page.html").write_text("<html>login</html>")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_flat_extension():
    assert download.flat_extension("https://x.org/a/b.nii.gz?dl=1") == ".nii.gz"
    assert download.flat_extension("https://x.org/data.CSV") == ".csv"
    assert download.flat_extension("https://x.org/dataset/123") is None


def test_private_hosts_blocked_by_default(server, tmp_path):
    assert not download.is_public_host(server)
    assert not download.is_public_host("file:///etc/passwd")
    r = download.download(f"{server}/labels.csv", tmp_path / "out", 10_000)
    assert r.status == "skipped" and "non-public" in r.note


def test_download_flat_file(server, tmp_path):
    r = download.download(f"{server}/labels.csv", tmp_path / "out", 10_000, allow_private=True)
    assert r.status == "downloaded" and r.bytes == 15 and len(r.sha256) == 64
    assert (tmp_path / "out" / "labels.csv").read_text().startswith("id,label")


def test_download_rejects_html_and_oversize(server, tmp_path):
    r = download.download(f"{server}/page.html", tmp_path / "o", 10_000, allow_private=True)
    assert r.status == "skipped" and "HTML" in r.note
    r = download.download(f"{server}/big.csv", tmp_path / "o", 1000, allow_private=True)
    assert r.status == "skipped" and "cap" in r.note
    assert not list((tmp_path / "o").glob("*.part"))


def test_probe(server):
    p = download.probe(f"{server}/labels.csv", allow_private=True)
    assert p["looks_like_flat_file"] and not p["looks_like_login_or_landing_page"]
    p = download.probe(f"{server}/page.html", allow_private=True)
    assert p["looks_like_login_or_landing_page"] and not p["looks_like_flat_file"]


def test_fetch_dataset_files_statuses(server, tmp_path):
    settings = Settings(data_dir=tmp_path / "d", allow_private_hosts=True, max_download_mb=1)
    s = Store(settings.db_path)
    open_id, _ = s.upsert_dataset({
        "title": "PTX labels", "url": "https://x.org/ptx", "access_type": "open",
        "download_urls": [f"{server}/labels.csv", f"{server}/page.html"]})
    assert download.fetch_dataset_files(s, settings, open_id) == "partial"
    files = s.get_dataset(open_id)["files"]
    assert {f["status"] for f in files} == {"downloaded", "skipped"}
    gated, _ = s.upsert_dataset({"title": "MIMIC", "url": "https://physionet.org/mimic",
                                 "access_type": "credentialed",
                                 "download_urls": [f"{server}/labels.csv"]})
    assert download.fetch_dataset_files(s, settings, gated) == "manual"
    assert s.get_dataset(gated)["files"] == []
