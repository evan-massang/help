from __future__ import annotations

from memeterm.safety.stages import authority


def _asset(mint_auth=None, freeze_auth=None, update_auth=None) -> dict:
    return {
        "token_info": {"mint_authority": mint_auth, "freeze_authority": freeze_auth},
        "authorities": [{"address": update_auth}] if update_auth else [],
    }


def test_clean_authorities_pass() -> None:
    result = authority.evaluate(_asset())
    assert result.verdict == "pass"


def test_freeze_authority_is_hard_fail() -> None:
    result = authority.evaluate(_asset(freeze_auth="SomeKey"))
    assert result.verdict == "fail"
    assert any("freeze_authority" in r for r in result.reasons)


def test_mint_authority_with_low_dev_is_warn() -> None:
    result = authority.evaluate(_asset(mint_auth="MintKey"), dev_pct=0.5)
    assert result.verdict == "warn"
    assert result.penalty == 1


def test_mint_authority_with_high_dev_is_fail() -> None:
    result = authority.evaluate(_asset(mint_auth="MintKey"), dev_pct=5.0)
    assert result.verdict == "fail"


def test_known_safe_update_authority_passes() -> None:
    # Pump.fun's metadata authority is in the safe set.
    result = authority.evaluate(_asset(update_auth="TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"))
    assert result.verdict == "pass"


def test_unknown_update_authority_adds_penalty() -> None:
    result = authority.evaluate(_asset(update_auth="RandomKey"))
    assert result.verdict == "warn"
    assert result.penalty >= 1
