"""Fetching samples from open repositories for Explore.

- **Repository file lists**: Figshare and Zenodo have public APIs listing a
  record's files with sizes and direct download URLs, so no agent is needed
  for datasets hosted there (found from the card's URL, links, citation or
  access text: figshare.com/articles/…/<id>, 10.6084/m9.figshare.<id>,
  zenodo.org/records/<id>, 10.5281/zenodo.<id>).
- **Remote zip sampling**: a multi-GB archive can still be sampled. Over HTTP
  range requests we read only the zip's central directory, pick a spread of
  members (images, tables, signal files), and download just those bytes.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

import requests

from .download import is_public_host

log = logging.getLogger(__name__)
_UA = {"User-Agent": "pahl-datasets explorer (+https://datasets.paloaltohealthlabs.com)"}
SKIP_EXT = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".md", ".html", ".htm", ".py", ".ipynb",
            ".r", ".m", ".js")
SAMPLE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".csv", ".tsv", ".txt", ".xlsx",
              ".json", ".edf", ".hea", ".dat", ".atr", ".nii", ".nii.gz", ".dcm", ".mat", ".npy")


def _texts(ds: dict) -> str:
    return " ".join(str(ds.get(k) or "") for k in ("url", "citation", "access_instructions",
                                                   "description")) + " " + " ".join(
        ds.get("download_urls") or [])


def repository_files(ds: dict, session: Any = None) -> tuple[str, list[dict]] | None:
    """(repository, [{name, size, url}]) for a Figshare/Zenodo-hosted dataset."""
    http = session or requests
    t = _texts(ds)
    m = (re.search(r"figshare\.com/articles/(?:[^/\s]+/)*?(\d{6,})", t)
         or re.search(r"10\.6084/m9\.figshare\.(\d{6,})", t, re.I))
    if m:
        try:
            r = http.get(f"https://api.figshare.com/v2/articles/{m.group(1)}", headers=_UA, timeout=30)
            if r.status_code == 200:
                return "figshare", [{"name": f["name"], "size": f.get("size") or 0,
                                     "url": f["download_url"]} for f in r.json().get("files", [])]
        except requests.RequestException as exc:
            log.warning("figshare lookup failed: %s", exc)
    m = (re.search(r"zenodo\.org/(?:records|record)/(\d{4,})", t)
         or re.search(r"10\.5281/zenodo\.(\d{4,})", t, re.I))
    if m:
        try:
            r = http.get(f"https://zenodo.org/api/records/{m.group(1)}", headers=_UA, timeout=30)
            if r.status_code == 200:
                files = r.json().get("files", [])
                return "zenodo", [{"name": f.get("key") or f.get("filename"), "size": f.get("size") or 0,
                                   "url": (f.get("links") or {}).get("self")} for f in files
                                  if (f.get("links") or {}).get("self")]
        except requests.RequestException as exc:
            log.warning("zenodo lookup failed: %s", exc)
    return None


class HTTPRangeFile(io.RawIOBase):
    """Seekable, read-only file over HTTP range requests (enough for zipfile)."""

    def __init__(self, url: str, size: int | None = None, session: Any = None, block: int = 1 << 20):
        self.url, self.http, self.block = url, session or requests.Session(), block
        self.pos = 0
        self._cache: dict[int, bytes] = {}
        self.size = size or self._head_size()
        self.fetched = 0

    def _head_size(self) -> int:
        r = self.http.get(self.url, headers={**_UA, "Range": "bytes=0-0"}, timeout=60,
                          allow_redirects=True, stream=True)
        cr = r.headers.get("Content-Range", "")
        r.close()
        m = re.search(r"/(\d+)$", cr)
        if r.status_code != 206 or not m:
            raise OSError("server does not support range requests")
        return int(m.group(1))

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _get(self, a: int, b: int) -> bytes:
        r = self.http.get(self.url, headers={**_UA, "Range": f"bytes={a}-{b}"}, timeout=120,
                          allow_redirects=True)
        if r.status_code != 206:
            raise OSError(f"range request failed: HTTP {r.status_code}")
        self.fetched += len(r.content)
        return r.content

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if not n:
            return b""
        if n > self.block * 4:           # large member bodies: one direct request
            data = self._get(self.pos, self.pos + n - 1)
        else:
            out, p, end = [], self.pos, self.pos + n
            while p < end:
                k = p // self.block
                if k not in self._cache:
                    a = k * self.block
                    self._cache[k] = self._get(a, min(self.size, a + self.block) - 1)
                    if len(self._cache) > 64:
                        self._cache.pop(next(iter(self._cache)))
                chunk = self._cache[k]
                off = p - k * self.block
                take = chunk[off: off + (end - p)]
                out.append(take)
                p += len(take)
                if not take:
                    break
            data = b"".join(out)
        self.pos += len(data)
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def sample_zip(url: str, dest: Path, max_bytes: int, size: int | None = None,
               max_members: int = 400, session: Any = None, log_=lambda m: None) -> dict:
    """Extract a spread of data members from a remote zip without downloading it."""
    if not is_public_host(url):
        raise OSError("refusing a non-public host")
    f = HTTPRangeFile(url, size, session)
    with zipfile.ZipFile(f) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename
                 and i.filename.lower().endswith(SAMPLE_EXT)]
        small = [i for i in infos if i.filename.lower().endswith((".csv", ".tsv", ".xlsx", ".json"))
                 and i.file_size < 50_000_000]
        rest = [i for i in infos if i not in small]
        # A spread across the archive (and so across class folders), not the first N.
        step = max(1, len(rest) // max(1, max_members))
        picks = small + rest[::step][:max_members]
        got, total = 0, 0
        for i in picks:
            if total + i.compress_size > max_bytes:
                continue
            out = dest / i.filename
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(out, "wb") as fh:
                fh.write(src.read())
            got += 1
            total += i.compress_size
            if got % 50 == 0:
                log_(f"sampled {got} files ({total / 1e6:.0f} MB) from {Path(url).name}")
    return {"members": len(infos), "sampled": got, "bytes": total, "fetched": f.fetched}
