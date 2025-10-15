# tests/test_dates.py
from time import struct_time
from veille_tech import normalize_ts

def test_normalize_ts_with_published_parsed():
    entry = {"published_parsed": struct_time((2025, 10, 14, 9, 30, 0, 0, 287, -1))}
    ts = normalize_ts(entry)
    assert isinstance(ts, int)
    assert ts > 0

def test_normalize_ts_with_rfc2822_string():
    entry = {"published": "Tue, 14 Oct 2025 09:00:00 GMT"}
    ts = normalize_ts(entry)
    assert isinstance(ts, int)
    assert ts > 0

def test_normalize_ts_returns_none_when_missing():
    entry = {"title": "No date here"}
    assert normalize_ts(entry) is None