"""Shared test setup: the dashboard cache is off in the API tests (they mutate the database directly and read back at once);
`tests/test_unit4.py` exercises the cache explicitly with its own TTL."""
import os

os.environ.setdefault("MABANIQ_CACHE_TTL", "0")
# the in-process retention scheduler would write to the shared SQLite file 30 s into a long test run ("database is locked"); test_unit4 calls it directly
os.environ.setdefault("MABANIQ_RETENTION", "0")
