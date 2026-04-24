"""Stage 1 — authorities.

* Mint authority must be null / revoked. Hard-fail if present AND the dev
  holds > 2% of supply (their ability to mint is then an active risk).
* Freeze authority must be null. Hard-fail if present (signer can freeze
  holder balances).
* Update authority is known-safe OR null (warn otherwise — a live update
  authority can change token metadata).

Input: a Helius ``getAsset`` DAS payload for the mint.
"""

from __future__ import annotations

from typing import Any

from memeterm.safety.types import StageResult


def evaluate(asset: dict[str, Any], *, dev_pct: float | None = None) -> StageResult:
    content = asset.get("content") or {}
    ownership = asset.get("ownership") or {}
    token_info = asset.get("token_info") or {}
    authorities = asset.get("authorities") or []

    mint_authority = token_info.get("mint_authority") or None
    freeze_authority = token_info.get("freeze_authority") or None
    update_authority = (
        (authorities[0].get("address") if authorities else None)
        or ownership.get("owner")
        or content.get("metadata", {}).get("update_authority")
    )

    reasons: list[str] = []
    penalty = 0
    is_fail = False

    if freeze_authority:
        reasons.append(f"freeze_authority={freeze_authority}")
        is_fail = True

    if mint_authority:
        if dev_pct is not None and dev_pct > 2.0:
            reasons.append(
                f"mint_authority={mint_authority} with dev_pct={dev_pct:.2f}"
            )
            is_fail = True
        else:
            reasons.append(f"mint_authority={mint_authority} (dev_pct ok)")
            penalty += 1

    if update_authority and not _is_known_safe(update_authority):
        reasons.append(f"update_authority={update_authority} not in safe list")
        penalty += 1

    if is_fail:
        return StageResult(
            verdict="fail",
            reasons=reasons,
            data={
                "mint_authority": mint_authority,
                "freeze_authority": freeze_authority,
                "update_authority": update_authority,
            },
        )
    if penalty > 0:
        return StageResult(
            verdict="warn",
            reasons=reasons,
            data={
                "mint_authority": mint_authority,
                "freeze_authority": freeze_authority,
                "update_authority": update_authority,
            },
            penalty=penalty,
        )
    return StageResult(
        verdict="pass",
        reasons=[],
        data={
            "mint_authority": None,
            "freeze_authority": None,
            "update_authority": update_authority,
        },
    )


# Well-known safe metadata update authorities (meme launchpads). Extended
# incrementally as we learn more.
_SAFE_UPDATE_AUTHORITIES: set[str] = {
    # Pump.fun metadata update authority
    "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM",
}


def _is_known_safe(pubkey: str) -> bool:
    return pubkey in _SAFE_UPDATE_AUTHORITIES
