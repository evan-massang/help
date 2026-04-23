"""External API adapters.

Every adapter inherits from :class:`BaseAdapter` for consistent rate limiting,
retry, typed errors, and cassette-backed tests. See plan §6 for the full
catalog of endpoints and per-adapter notes.
"""
