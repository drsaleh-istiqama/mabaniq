"""Shared test setup: the dashboard cache is off in the API tests (they mutate the database directly and read back at once);
`tests/test_unit4.py` exercises the cache explicitly with its own TTL."""
import os

os.environ.setdefault("MABANIQ_CACHE_TTL", "0")
