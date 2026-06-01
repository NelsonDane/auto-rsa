"""Per-signal-type performance dashboard (Phase 9).

Aggregates ledger rows by ``signal_type`` and surfaces simple,
honest metrics. Deliberately does NOT compute real per-fill P&L —
that would need price data the ledger doesn't capture today
(different brokers round at different days, fill prices vary per
account and per day). Instead, the operator sets an EXPECTED
average profit per fill per signal type, and the dashboard
multiplies it by the actual fill count.

This trades precision for honesty: the operator sees that the
"$X" number is a tunable estimate, not a claim about realized
profits. The completion-rate metrics (alerts → actionable → filled
→ sold) are 100% real, sourced directly from the ledger.
"""

from src.dashboard.per_signal_type import (
    SignalTypeMetrics,
    aggregate_by_signal_type,
)

__all__ = ["SignalTypeMetrics", "aggregate_by_signal_type"]
