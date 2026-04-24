"""Solana program IDs the scanner cares about.

Kept dep-free so pure modules (``scanner.parser`` and friends) can import it
without pulling in ``websockets`` or any network library.
"""

from __future__ import annotations

PROGRAM_IDS: dict[str, str] = {
    "raydium_v4": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "raydium_clmm": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "pumpfun_bc": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "pumpfun_amm": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "moonshot": "MoonCVVNZfSYcdACpJCAp6QpVaqdTH83PMjkcmEsDaT",
    "meteora_dlmm": "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
}
