"""Toast / native-notification sidecar client.

The Rust ``notifier.exe`` listens on ``127.0.0.1:8788`` and accepts JSON
payloads ``{title, body, url, sound}``. We POST to it via a short-timeout
``httpx`` client; failures are logged but never raise — toast delivery is
best-effort. The Linux side (WSL2) reaches it over the Windows host's
loopback (forwarded by WSL2's port mapper).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

NOTIFIER_URL = "http://127.0.0.1:8788/notify"
NOTIFIER_TIMEOUT_S = 0.8


async def post_toast(*, title: str, body: str, url: str | None = None, sound: str | None = None) -> bool:
    payload: dict[str, Any] = {"title": title[:80], "body": body[:280]}
    if url:
        payload["url"] = url
    if sound:
        payload["sound"] = sound
    try:
        async with httpx.AsyncClient(timeout=NOTIFIER_TIMEOUT_S) as client:
            resp = await client.post(NOTIFIER_URL, json=payload)
        return 200 <= resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.debug("alerts.notifier.unavailable", extra={"err": str(exc)})
        return False
