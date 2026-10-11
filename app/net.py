# one door for outside HTTP: retries with short pauses, then the host is set aside and later calls skip it
import threading
import time
from functools import cache
from urllib.parse import urlparse

import httpx
import logging_setup
import settings
import yaml

log = logging_setup.get_logger(__name__)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


class SourceDown(httpx.HTTPError):
    def __init__(self, host: str, reason: str):
        super().__init__(f"{host} is set aside: {reason}")
        self.host, self.reason = host, reason


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "net.yaml").read_text())


# kept in Postgres so the api sees what the worker set aside; the dict serves when the database is away
_inactive: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _db_rows() -> dict[str, tuple[float, str]] | None:
    try:
        from orm.db import Session
        from sqlalchemy import text

        with Session() as session:
            rows = session.execute(text("SELECT host, extract(epoch FROM until - now()), reason FROM outside_hosts"
                                        " WHERE until > now()")).all()
        return {host: (time.monotonic() + float(left), reason) for host, left, reason in rows}
    except Exception:
        return None


def _db_write(host: str, seconds: float, reason: str) -> None:
    try:
        from orm.db import Session
        from sqlalchemy import text

        with Session() as session:
            upsert = text("INSERT INTO outside_hosts (host, until, reason) VALUES (:h, now() + make_interval("
                          "secs => :s), :r) ON CONFLICT (host) DO UPDATE SET until = excluded.until, "
                          "reason = excluded.reason, updated_at = now()")
            session.execute(upsert, {"h": host, "s": seconds, "r": reason})
            session.commit()
    except Exception:
        pass


def _db_clear(host: str | None) -> None:
    try:
        from orm.db import Session
        from sqlalchemy import text

        with Session() as session:
            if host is None:
                session.execute(text("DELETE FROM outside_hosts"))
            else:
                session.execute(text("DELETE FROM outside_hosts WHERE host = :h"), {"h": host})
            session.commit()
    except Exception:
        pass


def host_of(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def inactive() -> dict[str, dict]:
    now = time.monotonic()
    with _lock:
        for host in [h for h, (until, _) in _inactive.items() if until <= now]:
            del _inactive[host]
        merged = dict(_inactive)
    merged.update(_db_rows() or {})
    return {h: {"seconds_left": round(until - now), "reason": why} for h, (until, why) in merged.items()}


def _set_aside(host: str, reason: str) -> None:
    if host in conf()["never_inactive"]:
        return
    with _lock:
        _inactive[host] = (time.monotonic() + conf()["inactive_seconds"], reason)
    _db_write(host, conf()["inactive_seconds"], reason)
    log.warning("net.set_aside", host=host, reason=reason)


def reset(host: str | None = None) -> None:
    with _lock:
        if host is None:
            _inactive.clear()
        else:
            _inactive.pop(host, None)
    _db_clear(host)


def _retried(host: str, send) -> httpx.Response:
    if host in inactive():
        raise SourceDown(host, inactive()[host]["reason"])
    delays = [0.0, *conf()["delays"]]
    reason = ""
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            seen = send()
        except httpx.ReadTimeout as e:
            # the request reached the server and it is still working: sending it again only queues it twice
            reason = f"ReadTimeout: {e}"
            break
        except httpx.TransportError as e:
            reason = f"{type(e).__name__}: {e}"
            continue
        if seen.status_code not in conf()["retry_status"]:
            return seen
        seen.close()
        reason = f"HTTP {seen.status_code}"
        if attempt == len(delays) - 1:
            break
    _set_aside(host, reason)
    raise SourceDown(host, reason)


def request(method: str, url: str, client: httpx.Client | None = None, **kwargs) -> httpx.Response:
    if client is None:
        kwargs.setdefault("timeout", 25)
        return _retried(host_of(url), lambda: httpx.request(method, url, **kwargs))
    return _retried(host_of(url), lambda: client.request(method, url, **kwargs))


# for SDKs that take an httpx client (the openai one): their calls get the same retries and set-aside rule
class Transport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport | None = None):
        self._inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return _retried(host_of(str(request.url)), lambda: self._inner.handle_request(request))

    def close(self) -> None:
        self._inner.close()


def get(url: str, **kwargs) -> httpx.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> httpx.Response:
    return request("POST", url, **kwargs)


# a client whose get/post go through the same retries and set-aside rule
class Client:
    def __init__(self, timeout: float = 25, headers: dict | None = None):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True,
                                    headers={"User-Agent": UA, **(headers or {})})

    def get(self, url: str, **kwargs) -> httpx.Response:
        return request("GET", url, client=self._client, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return request("POST", url, client=self._client, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return request("PUT", url, client=self._client, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()
