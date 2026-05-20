"""Producer pipeline, network fully mocked."""

from src.edgar import producer
from src.edgar.fetch import Hit


def _hit(acc, ticker, title, cik="1", link="https://sec.gov/a"):
    return Hit(
        accession=acc,
        cik=cik,
        ticker=ticker,
        form="8-K",
        filing_date="2026-05-10",
        link=f"{link}/{acc}",
        title=title,
    )


def test_discover_filters_classifies_and_dedupes(monkeypatch):
    round_up = (
        "Acme Corp announced a 1-for-40 reverse stock split that will "
        "become effective on June 1, 2026. No fractional shares will be "
        "issued; fractional interests will be rounded up to the nearest "
        "whole share."
    )
    cash = (
        "Beta Inc 1-for-10 reverse split effective July 2, 2026; "
        "stockholders will receive cash in lieu of fractional shares."
    )
    nothing = "Gamma Co quarterly earnings call scheduled."

    hits = {
        '"reverse stock split"': [
            _hit("A-1", "ACME", "Acme reverse split", link="https://s/x"),
            _hit("A-1", "ACME", "dupe accession", link="https://s/x"),  # dup
            _hit("B-2", "BETA", "Beta consolidation"),
            _hit("C-3", "GAMA", "Gamma earnings"),
        ],
        '"reverse split"': [_hit("A-9", "ACME", "Acme again, same play")],
    }
    bodies = {
        "https://s/x/A-1": round_up,
        "https://sec.gov/a/B-2": cash,
        "https://sec.gov/a/C-3": nothing,
        "https://sec.gov/a/A-9": round_up,  # same economic play as A-1
    }
    monkeypatch.setattr(
        producer, "efts_search", lambda q, *a, **k: hits.get(q, []),
    )
    monkeypatch.setattr(
        producer, "fetch_filing_text", lambda url: bodies.get(url, ""),
    )
    monkeypatch.setattr(producer, "cik_to_ticker", lambda _c: None)

    plays = producer.discover(window_days=14)
    by_ticker = {p.ticker: p for p in plays}

    # Gamma (no split language) and Beta (CASH_IN_LIEU — a non-play, not
    # in the alert policy set) are both excluded; Acme round-up appears
    # exactly once despite the duplicate accession + second query
    # (accession + split_key dedupe).
    assert set(by_ticker) == {"ACME"}
    assert sum(p.ticker == "ACME" for p in plays) == 1
    acme = by_ticker["ACME"]
    assert acme.fractional_policy == "ROUND_UP"
    assert acme.ratio == "1-for-40"
    assert acme.effective_date == "June 1, 2026"
    assert acme.expectation == "ROUND_UP_CONFIRMED"


def test_to_gui_rows_schema():
    p = producer.Play(
        ticker="ACME",
        ratio="1-for-40",
        effective_date="June 1, 2026",
        fractional_policy="ROUND_UP",
        confidence=0.93,
        expectation="ROUND_UP_CONFIRMED",
        source="SEC_EFTS",
        key="abc",
        split_key="ACME|1-FOR-40|JUNE 1, 2026|ROUND_UP",
        link="https://sec.gov/a",
    )
    (row,) = producer.to_gui_rows([p])
    assert len(row) == len(producer.GUI_QUEUE_HEADER)
    assert row[1] == "ACME"
    assert row[2] == "buy"
    assert row[6] == "ROUND_UP"
    assert row[10] == "PENDING"
    # pre-split deadline = last NYSE session before 6/1/2026 (Mon) = Fri 5/29
    assert row[5] == "May 29 by 4pm (Eastern Time)"


def test_unspecified_is_not_alert_worthy(monkeypatch):
    monkeypatch.setattr(
        producer,
        "efts_search",
        lambda q, *a, **k: [_hit("Z-1", "ZZZZ", "Z reverse split")],
    )
    monkeypatch.setattr(
        producer,
        "fetch_filing_text",
        lambda _u: "The board approved a 1-for-5 reverse stock split.",
    )
    monkeypatch.setattr(producer, "cik_to_ticker", lambda _c: None)
    # UNSPECIFIED policy -> not alert-worthy -> no rows.
    assert producer.discover(window_days=7) == []
