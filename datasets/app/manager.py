"""Crawl session lifecycle: start / track / cancel crawls in background threads
and fan recorded datasets out to a download pool.

In-process by design for v0 (one API container). The same entry point,
``run_crawl_blocking``, backs the CLI in ``jobs/crawl.py`` for cron use.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import crawler, download
from .config import Settings
from .store import Store

log = logging.getLogger(__name__)
SEED_CONDITIONS = Path(__file__).resolve().parent.parent / "seed" / "conditions.json"


def load_seed() -> list[dict]:
    try:
        return json.loads(SEED_CONDITIONS.read_text())
    except (OSError, ValueError):
        return []


class CrawlBusy(RuntimeError):
    pass


class CrawlManager:
    def __init__(self, store: Store, settings: Settings,
                 client_factory: Callable[[Settings], object] | None = None):
        self.store = store
        self.settings = settings
        self.client_factory = client_factory or crawler.make_client
        self._cancel: dict[int, threading.Event] = {}
        self._threads: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
        self._downloads = ThreadPoolExecutor(max_workers=3, thread_name_prefix="dl")

    # ------------------------------------------------------------ public
    def llm_ready(self) -> bool:
        return bool(self.settings.anthropic_api_key) or self.client_factory is not crawler.make_client

    def active(self) -> list[int]:
        with self._lock:
            return [cid for cid, t in self._threads.items() if t.is_alive()]

    def start(self, mode: str, query: str | None = None, minutes: int | None = None) -> int:
        if mode not in ("query", "broad"):
            raise ValueError("mode must be 'query' or 'broad'")
        if mode == "query" and not (query or "").strip():
            raise ValueError("query is required")
        if len(self.active()) >= self.settings.max_concurrent_crawls:
            raise CrawlBusy("too many crawls running; try again when one finishes")
        minutes = minutes or (self.settings.broad_crawl_minutes if mode == "broad"
                              else self.settings.query_crawl_minutes)
        minutes = max(1, min(int(minutes), 180))
        crawl_id = self.store.create_crawl(mode, query, minutes)
        cancel = threading.Event()
        t = threading.Thread(target=self._run, args=(crawl_id, mode, query, minutes, cancel),
                             name=f"crawl-{crawl_id}", daemon=True)
        with self._lock:
            self._cancel[crawl_id] = cancel
            self._threads[crawl_id] = t
        t.start()
        return crawl_id

    def cancel(self, crawl_id: int) -> bool:
        with self._lock:
            ev = self._cancel.get(crawl_id)
        if ev:
            ev.set()
            return True
        return False

    def wait(self, crawl_id: int, timeout: float | None = None) -> None:
        with self._lock:
            t = self._threads.get(crawl_id)
        if t:
            t.join(timeout)

    def queue_download(self, ds_id: str) -> None:
        self._downloads.submit(self._download_safe, ds_id)

    # ------------------------------------------------------------ internals
    def _download_safe(self, ds_id: str) -> None:
        try:
            download.fetch_dataset_files(self.store, self.settings, ds_id)
        except Exception:
            log.exception("download failed for %s", ds_id)

    def _run(self, crawl_id: int, mode: str, query: str | None, minutes: int,
             cancel: threading.Event) -> None:
        self.run_crawl_blocking(crawl_id, mode, query, minutes, cancel)

    def run_crawl_blocking(self, crawl_id: int, mode: str, query: str | None,
                           minutes: int, cancel: threading.Event | None = None) -> None:
        ctx = crawler.CrawlContext(
            crawl_id=crawl_id, store=self.store, settings=self.settings,
            deadline=time.monotonic() + minutes * 60,
            cancel=cancel or threading.Event(),
            on_dataset=lambda ds_id, _new: self.queue_download(ds_id))
        self.store.update_crawl(crawl_id, status="running")
        try:
            client = self.client_factory(self.settings)
            if mode == "broad":
                crawler.run_broad(client, ctx, load_seed())
            else:
                crawler.run_swarm(client, ctx, query or "")
            status = "cancelled" if ctx.cancel.is_set() else "done"
            self.store.update_crawl(crawl_id, status=status, finished_at=_now())
            ctx.log(f"crawl {status}")
        except Exception as exc:
            log.exception("crawl %s failed", crawl_id)
            self.store.update_crawl(crawl_id, status="failed", finished_at=_now(),
                                    error=f"{type(exc).__name__}: {str(exc)[:500]}")
        finally:
            with self._lock:
                self._cancel.pop(crawl_id, None)

    def drain_downloads(self) -> None:
        """Block until queued downloads finish (CLI use)."""
        self._downloads.shutdown(wait=True)

    def shutdown(self) -> None:
        for ev in list(self._cancel.values()):
            ev.set()
        self._downloads.shutdown(wait=False, cancel_futures=True)


def _now() -> str:
    from .store import now_iso
    return now_iso()
