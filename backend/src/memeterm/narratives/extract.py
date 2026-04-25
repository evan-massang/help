"""Pure text-extraction helpers for social mentions.

* mint references (Solana base58 32–44 char addresses + a small known list)
* hashtag keywords
* clean-text shingle (used by the burst detector via :mod:`memeterm.hype.burst`)

Kept dep-free + sync so the ingest service can call thousands of times per
minute without touching the event loop.
"""

from __future__ import annotations

import re

_BASE58 = "[1-9A-HJ-NP-Za-km-z]"
_MINT_RE = re.compile(rf"\b({_BASE58}{{32,44}})\b")
_HASHTAG_RE = re.compile(r"#(\w{2,40})")
_TICKER_RE = re.compile(r"\$([A-Z][A-Z0-9]{1,9})\b")


def extract_mints(text: str) -> list[str]:
    """Return potential Solana mint pubkeys mentioned in the text.

    False positives are possible (any base58 32–44 char string matches);
    the caller should cross-check against the ``coins`` table before
    storing.
    """
    return [m.group(1) for m in _MINT_RE.finditer(text)]


def extract_hashtags(text: str) -> list[str]:
    return [m.group(1).lower() for m in _HASHTAG_RE.finditer(text)]


def extract_tickers(text: str) -> list[str]:
    return [m.group(1).upper() for m in _TICKER_RE.finditer(text)]


def clean_for_embedding(text: str) -> str:
    """Strip URLs / @-handles / RT prefixes so the embedding focuses on
    semantic content rather than spam structure."""
    cleaned = re.sub(r"https?://\S+", "", text)
    cleaned = re.sub(r"@\w+", "", cleaned)
    cleaned = re.sub(r"^RT\s+", "", cleaned)
    return " ".join(cleaned.split())[:512]
