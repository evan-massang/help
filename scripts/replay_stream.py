#!/usr/bin/env python
"""Replay a saved enhanced-transaction stream through the scanner parser.

Usage
-----

    python scripts/replay_stream.py FIXTURE.jsonl

Where ``FIXTURE.jsonl`` is newline-delimited JSON, one Helius enhanced
transaction per line. Prints one summary line per input describing the
resulting :class:`~memeterm.scanner.parser.LaunchCandidate` or the reason
it was skipped.

Regression harness: any time we change ``parse_enhanced_tx`` or the safety
pipeline, re-run this against the checked-in fixtures and diff the output
against the ``.expected`` golden file next to the input.

Exit code 0 iff every line parsed without raising.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memeterm.scanner.parser import parse_enhanced_tx


def replay(input_path: Path) -> int:
    errors = 0
    with input_path.open() as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                tx = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"line {lineno}: JSON ERROR — {exc}")
                errors += 1
                continue
            try:
                candidate = parse_enhanced_tx(tx)
            except Exception as exc:  # noqa: BLE001
                print(f"line {lineno}: PARSE EXCEPTION — {type(exc).__name__}: {exc}")
                errors += 1
                continue
            if candidate is None:
                print(f"line {lineno}: skipped (no launch candidate)")
                continue
            print(
                "line {n}: {venue} mint={mint} pool={pool} lp_usd={lp} price_usd={price}".format(
                    n=lineno,
                    venue=candidate.venue,
                    mint=candidate.mint,
                    pool=candidate.pool,
                    lp=candidate.initial_liquidity_usd,
                    price=candidate.initial_price_usd,
                )
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="jsonl of enhanced transactions")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"no such file: {args.input}", file=sys.stderr)
        return 2
    errors = replay(args.input)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
