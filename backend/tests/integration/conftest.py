"""VCR config for adapter integration tests.

Cassettes live under ``tests/integration/cassettes``. To record new fixtures
against live APIs, fill in .env and run:

    RECORD=1 pytest tests/integration -k <adapter>

Offline runs use ``record_mode=none`` — if a cassette is missing, the test
is skipped so CI stays green when we add a new adapter but haven't recorded
yet.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    record_mode = "new_episodes" if os.environ.get("RECORD") else "none"
    return {
        "record_mode": record_mode,
        "filter_headers": [
            ("authorization", "REDACTED"),
            ("x-api-key", "REDACTED"),
            ("X-API-KEY", "REDACTED"),
            ("cookie", "REDACTED"),
        ],
        "filter_query_parameters": [("api-key", "REDACTED")],
        "match_on": ["method", "scheme", "host", "path", "query"],
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    module = request.node.fspath.purebasename
    target = CASSETTE_DIR / module
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip VCR tests with missing cassettes instead of failing."""
    if os.environ.get("RECORD"):
        return
    skip = pytest.mark.skip(reason="cassette missing; re-run with RECORD=1 to record")
    for item in items:
        vcr_marker = item.get_closest_marker("vcr")
        if vcr_marker is None:
            continue
        module_name = item.nodeid.split("::")[0].rsplit("/", 1)[-1].removesuffix(".py")
        test_name = item.name.split("[")[0]
        cassette = CASSETTE_DIR / module_name / f"{test_name}.yaml"
        if not cassette.exists():
            item.add_marker(skip)
