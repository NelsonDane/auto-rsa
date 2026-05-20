"""Deterministic reverse-split scraper/classifier (M3).

A faithful Python port of the hand-tuned Apps Script logic
(``Reverse Split Automation v2.2``). Pure, network-free, and
unit-tested against the labeled corpus so precision/recall can't
silently regress — the test harness Apps Script could never have.

EDGAR fetching and the GUI_QUEUE producer build on this core in M3b.
"""
