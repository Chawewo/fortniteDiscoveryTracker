"""Client for Epic's public Fortnite Data API (no login). Paced to stay under its rate limit."""
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config


class OutOfTime(Exception):
    """The run's time budget is spent; remaining work waits for the next run."""


class EpicAPI:
    def __init__(self, seconds=config.RUN_SECONDS, rate=config.REQUESTS_PER_SECOND):
        self.deadline = time.monotonic() + seconds
        self.gap = 1 / rate
        self.next_at = 0.0
        self.lock = threading.Lock()
        self.calls = 0
        self.retries = 0

    def has_time(self, margin=0):
        return time.monotonic() + margin < self.deadline

    def _wait_turn(self):
        with self.lock:
            at = max(time.monotonic(), self.next_at)
            self.next_at = at + self.gap
        time.sleep(max(0.0, at - time.monotonic()))

    def _back_off(self, seconds):
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)
            self.retries += 1

    def get(self, path, **params):
        """GET a JSON path. Returns None for 404; raises after repeated throttling or errors."""
        query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        url = config.API + path + ("?" + query if query else "")
        for attempt in range(5):
            if not self.has_time():
                raise OutOfTime(path)
            self._wait_turn()
            try:
                with urlopen(Request(url, headers={"User-Agent": config.USER_AGENT,
                                                   "Accept": "application/json"}), timeout=30) as response:
                    body = response.read()
                with self.lock:
                    self.calls += 1
                # The API has answered throttled requests with an empty 200 body.
                if not body.strip():
                    self._back_off(4 * (attempt + 1))
                    continue
                return json.loads(body)
            except HTTPError as error:
                with self.lock:
                    self.calls += 1
                if error.code == 404:
                    return None
                if error.code == 429 or error.code >= 500:
                    self._back_off(4 * (attempt + 1))
                    continue
                raise RuntimeError(f"Epic API {error.code} for {path}: {error.read()[:200]!r}") from None
            except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
                self._back_off(3 * (attempt + 1))
        raise RuntimeError(f"Epic API kept failing for {path}")

    def pages(self, path, max_pages=None, **params):
        """Follow cursor pagination; yields each page's data list."""
        after, count = None, 0
        while max_pages is None or count < max_pages:
            payload = self.get(path, after=after, **params)
            if not payload:
                return
            yield payload.get("data") or []
            count += 1
            after = ((payload.get("meta") or {}).get("page") or {}).get("nextCursor")
            if not after:
                return
