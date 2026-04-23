"""Jupiter aggregator — quotes + swap simulation for honeypot detection.

Safety stage 4 asks Jupiter for a dust-amount quote in both directions; if
the sell path fails or slippage massively exceeds the quote, we flag the
token as a honeypot.
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterClient(BaseAdapter):
    name = "jupiter"
    base_url = "https://quote-api.jup.ag"
    rps = 5.0
    burst = 10
    retries = 3

    async def quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 300,
        swap_mode: str = "ExactIn",
    ) -> dict[str, Any]:
        resp = await self._get(
            "/v6/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
                "swapMode": swap_mode,
            },
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"jupiter: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("jupiter: quote not an object", adapter=self.name)
        return data

    async def can_roundtrip(self, mint: str, *, lamports: int = 10_000_000) -> dict[str, Any]:
        """Simulate USDC→mint→USDC on a dust amount. Returns both legs.

        Phase 1 returns raw Jupiter quote dicts; safety stage 4 in Phase 2 will
        translate them into a ``HoneypotVerdict`` with tax + slippage math.
        """
        buy = await self.quote(input_mint=USDC_MINT, output_mint=mint, amount=lamports)
        out_amount = int(buy.get("outAmount", "0") or 0)
        sell = await self.quote(input_mint=mint, output_mint=USDC_MINT, amount=out_amount)
        return {"buy": buy, "sell": sell}

    async def ping(self) -> dict[str, object]:
        q = await self.quote(input_mint=USDC_MINT, output_mint=SOL_MINT, amount=10_000_000)
        return {"adapter": self.name, "ok": "outAmount" in q}
