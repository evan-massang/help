# Adapter cassettes

Recorded HTTP fixtures for `tests/integration/test_adapters.py`. Each test
gets one cassette in a subdirectory named after the test file.

## Recording

```bash
cp .env.example .env         # fill in keys
cd backend
RECORD=1 pytest tests/integration/test_adapters.py -v
```

Headers matching `authorization`, `x-api-key`, `cookie` and query params
named `api-key` are filtered to `REDACTED` by `conftest.py` before the
cassette lands on disk. Review the YAML before committing to confirm
nothing sensitive leaked.

## Replay

```bash
pytest tests/integration/test_adapters.py
```

Missing cassettes are skipped (not failed) so CI stays green when adapters
land before cassettes do.
