"""Runtime flags for live-mutable settings.

Subsystems that capture configuration at boot (e.g. the position service
reads ``PHANTOM_PUBKEY`` once and starts watcher/ticker tasks bound to
that wallet) need a way to find out when the user changes that
configuration through the dashboard.

This module exposes a tiny set of asyncio Events. The settings REST
handler signals a change; subsystems await on the matching event and
restart their inner TaskGroups when it fires.

Process-local only — there's exactly one event per signal kind, shared
across the whole supervisor.
"""

from __future__ import annotations

import asyncio


class _Flags:
    def __init__(self) -> None:
        self._phantom_changed = asyncio.Event()

    async def wait_phantom_change(self) -> None:
        await self._phantom_changed.wait()
        self._phantom_changed.clear()

    def signal_phantom_change(self) -> None:
        self._phantom_changed.set()


runtime = _Flags()
"""Process-wide singleton."""
