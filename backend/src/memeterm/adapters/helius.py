"""Helius — primary Solana data source.

Covers the REST/JSON-RPC surface used by the scanner and position monitor.
The WebSocket ``logsSubscribe`` / ``accountSubscribe`` is wired separately
from :mod:`memeterm.adapters.helius_ws` so each can fail independently.

Endpoints used here:

- JSON-RPC (``/?api-key=...``): ``getTokenAccountsByOwner``, ``getAccountInfo``,
  ``getTransaction``, ``getMultipleAccounts``
- DAS (``/?api-key=...`` with ``getAsset``): token metadata + mint authorities
- Enhanced transactions (``https://api.helius.xyz/v0/addresses/{wallet}/transactions``)
"""

from __future__ import annotations

from typing import Any

import httpx

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData
from memeterm.config import get_settings


class HeliusClient(BaseAdapter):
    name = "helius"
    rps = 8.0
    burst = 16
    retries = 4

    @property
    def base_url(self) -> str:  # type: ignore[override]
        url = get_settings().HELIUS_RPC_URL
        return url or "https://mainnet.helius-rpc.com"

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Content-Type"] = "application/json"
        return headers

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = await self._post(self.base_url, json=body)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BadData(f"helius: non-json rpc body: {exc}", adapter=self.name) from exc
        if "error" in payload:
            err = payload["error"]
            raise BadData(
                f"helius: rpc error {err.get('code')}: {err.get('message')}",
                adapter=self.name,
            )
        return payload.get("result")

    # ---- DAS ---------------------------------------------------------------

    async def get_asset(self, mint: str) -> dict[str, Any]:
        return await self._rpc("getAsset", [{"id": mint}])

    # ---- plain RPC ---------------------------------------------------------

    async def get_token_accounts_by_owner(self, owner: str) -> list[dict[str, Any]]:
        result = await self._rpc(
            "getTokenAccountsByOwner",
            [
                owner,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"},
            ],
        )
        value = result.get("value", []) if isinstance(result, dict) else []
        return list(value)

    async def get_transaction(self, signature: str) -> dict[str, Any] | None:
        return await self._rpc(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )

    # ---- enhanced API ------------------------------------------------------

    async def enhanced_wallet_transactions(
        self,
        wallet: str,
        *,
        limit: int = 100,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        key = get_settings().HELIUS_API_KEY.get_secret_value()
        params: dict[str, str | int] = {"api-key": key, "limit": limit}
        if before:
            params["before"] = before
        # Enhanced API lives on a different host; call it via a one-off client
        # so we keep RPC traffic on the primary base_url.
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.get(url, params=params)
        self._check_status(resp)
        data = resp.json()
        if not isinstance(data, list):
            raise BadData("helius: enhanced tx response not a list", adapter=self.name)
        return data

    # ---- self-test ---------------------------------------------------------

    async def ping(self) -> dict[str, object]:
        # getHealth is cheap and cached at the RPC layer.
        result = await self._rpc("getHealth", [])
        return {"adapter": self.name, "ok": result == "ok", "result": result}
