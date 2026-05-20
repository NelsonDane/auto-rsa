"""EDGAR fetch parsing, fully mocked (no network)."""

import requests

from src.edgar import fetch


class _Resp:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            msg = "no json"
            raise ValueError(msg)
        return self._payload


def test_efts_search_parses_hits(monkeypatch):
    payload = {
        "hits": {
            "hits": [
                {
                    "_id": "0001234567-26-000123:doc.htm",
                    "_source": {
                        "ciks": ["0001234567"],
                        "display_names": ["Acme Corp (ACME) (CIK 0001234567)"],
                        "file_date": "2026-05-10",
                        "file_type": "8-K",
                    },
                },
                {  # missing cik -> skipped
                    "_id": "x:y",
                    "_source": {"display_names": ["No CIK Inc"]},
                },
            ],
        },
    }
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        fetch.requests, "get", lambda *a, **k: _Resp(200, payload),
    )
    hits = fetch.efts_search('"reverse stock split"', "2026-05-01", "2026-05-15")
    assert len(hits) == 1
    h = hits[0]
    assert h.accession == "0001234567-26-000123"
    assert h.cik == "1234567"  # leading zeros stripped
    assert h.ticker == "ACME"
    assert h.filing_date == "2026-05-10"
    assert h.link == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000123/doc.htm"
    )


def test_efts_search_failures_return_empty(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        fetch.requests, "get", lambda *a, **k: _Resp(403, None, "denied"),
    )
    assert fetch.efts_search("q", "a", "b") == []

    def boom(*_a, **_k):
        raise requests.RequestException

    monkeypatch.setattr(fetch.requests, "get", boom)
    assert fetch.efts_search("q", "a", "b") == []


def test_cik_to_ticker(monkeypatch):
    fetch.cik_to_ticker.cache_clear()
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        fetch.requests,
        "get",
        lambda *a, **k: _Resp(200, {"tickers": ["lcid", "lcidw"]}),
    )
    assert fetch.cik_to_ticker("0000099999") == "LCID"
    # cached: a raising get must not be hit again for same cik
    monkeypatch.setattr(
        fetch.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError),
    )
    assert fetch.cik_to_ticker("99999") == "LCID"


def test_fetch_filing_text_strips_and_caps(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: None)
    html = "<html><body><p>Reverse stock split " + "x" * 30000 + "</p></body></html>"
    monkeypatch.setattr(
        fetch.requests, "get", lambda *a, **k: _Resp(200, None, html),
    )
    out = fetch.fetch_filing_text("https://sec.gov/a")
    assert "Reverse stock split" in out
    assert "<" not in out
    assert len(out) <= 20000
    assert fetch.fetch_filing_text("") == ""
