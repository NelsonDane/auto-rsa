"""Unattended executor — M5.

Phase 1 (this module today) is **shadow only**: it reads GUI_QUEUE,
plans what it *would* buy, and reports it. It places NO orders, calls
NO brokers, and writes neither the sheet nor the ledger. Zero money
risk — its only job is to prove selection quality before any real
unattended trading is enabled (see docs/AUTO_EXECUTOR_DESIGN.md).
"""
