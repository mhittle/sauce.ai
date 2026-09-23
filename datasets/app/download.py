"""Flat-file downloader.

Only direct links to flat files are fetched (tabular, archives, and common
medical formats such as NIfTI/EDF/DICOM). HTML responses — landing pages,
login walls — are rejected, as are private/loopback addresses (the URLs come
from an LLM reading the open web, so treat them as untrusted) and anything
over the size cap.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

log = logging.getLogger(__name__)
_UA = {"User-Agent": "Mozilla/5.0 (compatible; sauce.ai-datasets/0.1)"}

FLAT_EXTENSIONS = (
    # tabular / text
    ".csv", ".tsv", ".txt", ".json", ".jsonl", ".ndjson", ".parquet", ".feather",
    ".xlsx", ".xls", ".xml", ".arff", ".sav", ".dta", ".sas7bdat",
    # archives
    ".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".bz2", ".tar.bz2", ".xz", ".7z",
    # medical / scientific
    ".nii", ".nii.gz", ".dcm", ".edf", ".mat", ".h5", ".hdf5", ".npy", ".npz",
    ".mha", ".mhd", ".nrrd", ".dat", ".hea", ".wfdb",
)
_REJECT_TYPES = ("text/html", "application/xhtml")


@dataclass
class DownloadResult:
    status: str                 # downloaded | skipped | failed
    note: str | None = None
    filename: str | None = None
    local_path: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    content_type: str | None = None


def flat_extension(url_or_name: str) -> str | None:
    path = unquote(urlsplit(url_or_name).path).lower()
    for ext in sorted(FLAT_EXTENSIONS, key=len, reverse=True):
        if path.endswith(ext):
            return ext
    return None


def is_public_host(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def safe_filename(name: str, fallback: str = "download") -> str:
    name = unquote(name).split("/")[-1].split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:180] or fallback


def _cd_filename(resp: requests.Response) -> str | None:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.I)
    return m.group(1) if m else None


class _Blocked(Exception):
    pass


def _get(url: str, allow_private: bool, timeout: float,
         max_redirects: int = 5) -> requests.Response:
    """Streaming GET that re-checks the host on every redirect hop, so a
    public URL can't bounce the server onto an internal address."""
    for _ in range(max_redirects + 1):
        if not allow_private and not is_public_host(url):
            raise _Blocked("non-public or invalid host")
        resp = requests.get(url, headers=_UA, stream=True, timeout=timeout,
                            allow_redirects=False)
        if resp.is_redirect and resp.headers.get("Location"):
            url = requests.compat.urljoin(url, resp.headers["Location"])
            resp.close()
            continue
        return resp
    raise _Blocked("too many redirects")


def probe(url: str, allow_private: bool = False, timeout: float = 20) -> dict:
    """Cheap look at a URL for the crawl agent: final URL, content type,
    size, and whether it looks like a downloadable flat file."""
    try:
        resp = _get(url, allow_private, timeout)
    except _Blocked as exc:
        return {"url": url, "ok": False, "error": str(exc)}
    except requests.RequestException as exc:
        return {"url": url, "ok": False, "error": str(exc)[:200]}
    with resp:
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        size = resp.headers.get("Content-Length")
        name = _cd_filename(resp) or resp.url
        ext = flat_extension(name) or flat_extension(url)
        is_html = ctype.startswith(_REJECT_TYPES)
        return {
            "url": url, "final_url": resp.url, "ok": resp.ok, "status": resp.status_code,
            "content_type": ctype or None,
            "bytes": int(size) if size and size.isdigit() else None,
            "filename": safe_filename(name) if not is_html else None,
            "looks_like_flat_file": bool(ext) and not is_html and resp.ok,
            "looks_like_login_or_landing_page": is_html,
        }


def download(url: str, dest_dir: Path, max_bytes: int, allow_private: bool = False,
             timeout: float = 60) -> DownloadResult:
    # Extension-less URLs are allowed through to here; headers decide.
    try:
        resp = _get(url, allow_private, timeout)
    except _Blocked as exc:
        return DownloadResult("skipped", str(exc))
    except requests.RequestException as exc:
        return DownloadResult("failed", str(exc)[:300])
    with resp:
        if not resp.ok:
            return DownloadResult("failed", f"HTTP {resp.status_code}")
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype.startswith(_REJECT_TYPES):
            return DownloadResult("skipped", "HTML page (landing or login), not a file",
                                  content_type=ctype)
        name = _cd_filename(resp) or resp.url
        if not (flat_extension(name) or flat_extension(url)):
            return DownloadResult("skipped", f"not a recognised flat-file type ({ctype})",
                                  content_type=ctype)
        size = resp.headers.get("Content-Length")
        if size and size.isdigit() and int(size) > max_bytes:
            return DownloadResult(
                "skipped", f"{int(size) / 1e6:.0f} MB exceeds the "
                f"{max_bytes / 1e6:.0f} MB cap; download manually", content_type=ctype,
                bytes=int(size))
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_filename(name)
        path = dest_dir / filename
        h = hashlib.sha256()
        total = 0
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    total += len(chunk)
                    if total > max_bytes:
                        raise OverflowError
                    h.update(chunk)
                    fh.write(chunk)
        except OverflowError:
            tmp.unlink(missing_ok=True)
            return DownloadResult("skipped", f"exceeds the {max_bytes / 1e6:.0f} MB cap;"
                                  " download manually", content_type=ctype)
        except (requests.RequestException, OSError) as exc:
            tmp.unlink(missing_ok=True)
            return DownloadResult("failed", str(exc)[:300], content_type=ctype)
        tmp.replace(path)
        return DownloadResult("downloaded", None, filename, str(path), total,
                              h.hexdigest(), ctype or None)


def fetch_dataset_files(store, settings, ds_id: str) -> str:
    """Download a dataset's direct flat-file links (open access only) and set
    its download_status: downloaded | partial | manual | none."""
    ds = store.get_dataset(ds_id)
    if not ds:
        return "none"
    if ds["access_type"] not in ("open", "unknown"):
        store.set_download_status(ds_id, "manual")
        return "manual"
    if not settings.download_enabled:
        return ds["download_status"]
    seen = store.file_urls(ds_id)
    urls = [u for u in ds["download_urls"] if u.startswith(("http://", "https://"))]
    for url in urls[: settings.max_files_per_dataset]:
        if seen.get(url) == "downloaded":
            continue
        res = download(url, settings.files_dir / ds_id, settings.max_download_mb * 1_000_000,
                       allow_private=settings.allow_private_hosts)
        store.record_file(ds_id, url, res.status, filename=res.filename,
                          local_path=res.local_path, bytes=res.bytes, sha256=res.sha256,
                          content_type=res.content_type, note=res.note)
        log.info("dataset %s file %s -> %s %s", ds_id, url, res.status, res.note or "")
    statuses = list(store.file_urls(ds_id).values())
    n_ok = statuses.count("downloaded")
    if n_ok and n_ok == len(statuses):
        status = "downloaded"
    elif n_ok:
        status = "partial"
    elif ds["access_type"] == "open" and not urls:
        status = "none"
    else:
        status = "manual"
    store.set_download_status(ds_id, status)
    return status
