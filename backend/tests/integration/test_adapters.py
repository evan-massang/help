"""Smoke tests for each adapter. Use pytest-vcr cassettes for offline replay.

Missing cassettes are skipped (see conftest). To record a fresh cassette
against live APIs:

    RECORD=1 pytest tests/integration/test_adapters.py::test_birdeye_price
"""

from __future__ import annotations

import pytest

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.dexscreener import DexscreenerClient
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.jupiter import JupiterClient
from memeterm.adapters.rugcheck import RugcheckClient
from memeterm.adapters.twitter import TwitterClient

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
SOL = "So11111111111111111111111111111111111111112"


@pytest.mark.vcr
async def test_birdeye_price() -> None:
    async with BirdeyeClient() as c:
        data = await c.price(USDC)
    assert "value" in data


@pytest.mark.vcr
async def test_birdeye_token_overview() -> None:
    async with BirdeyeClient() as c:
        data = await c.token_overview(BONK)
    assert data.get("address") == BONK


@pytest.mark.vcr
async def test_dexscreener_best_pair() -> None:
    async with DexscreenerClient() as c:
        pair = await c.best_solana_pair(BONK)
    assert pair is not None
    assert pair["chainId"] == "solana"


@pytest.mark.vcr
async def test_helius_get_asset() -> None:
    async with HeliusClient() as c:
        asset = await c.get_asset(BONK)
    assert asset.get("id") == BONK


@pytest.mark.vcr
async def test_helius_get_health() -> None:
    async with HeliusClient() as c:
        status = await c.ping()
    assert status["ok"] is True


@pytest.mark.vcr
async def test_jupiter_quote_usdc_to_sol() -> None:
    async with JupiterClient() as c:
        q = await c.quote(input_mint=USDC, output_mint=SOL, amount=10_000_000)
    assert int(q["outAmount"]) > 0


@pytest.mark.vcr
async def test_rugcheck_report() -> None:
    async with RugcheckClient() as c:
        report = await c.token_report(BONK)
    assert "score" in report or "risks" in report


@pytest.mark.vcr
async def test_twitter_counts_recent() -> None:
    async with TwitterClient() as c:
        counts = await c.counts_recent("solana lang:en")
    assert counts.get("meta", {}).get("total_tweet_count") is not None
