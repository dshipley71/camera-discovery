from __future__ import annotations

import time

import httpx


def _get_with_retry(client: httpx.Client, url: str, *, retries: int = 1) -> httpx.Response:
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(url)
            if resp.status_code < 500:
                return resp
            if attempt < retries:
                time.sleep(2 ** attempt)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    if last_exc:
        raise last_exc
    if resp is not None:
        return resp
    raise httpx.ConnectError(f"No response returned for {url}")
