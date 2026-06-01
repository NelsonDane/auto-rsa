"""Audit broker modules for missing real-money safety guards.

Two structural checks per broker, both verified missing today in
every broker except Fidelity (see the audit summary's C1 + C2):

  C1. ``record_intent`` + ``mark_result`` called in the broker's
      ``<broker>_transaction`` body — the ledger idempotency that
      prevents a double-buy on retry, crash-resume, or re-queued
      signal.

  C2. ``account_allowed(...)`` called in the same body — the
      per-broker sub-account allow-list the GUI persists via
      ``RSA_ACCOUNT_FILTER``. Without this call the broker iterates
      every account, ignoring the operator's per-account filter.

Run as a pre-commit / CI gate so a new broker that forgets these
guards fails loudly. Exit code 1 if any broker is missing either
guard; 0 otherwise.

To opt a broker out (e.g., explicitly not ledger-participant), add
it to ``EXEMPT_*`` below with a recorded reason — don't quietly
delete it.

Invoke:

    uv run --no-sync python scripts/audit_broker_safety.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Brokers explicitly exempt from one or both checks. Each entry
# needs a tracked reason — don't add without explaining why a real
# safety guard isn't required.
EXEMPT_LEDGER: dict[str, str] = {
    # Operator-confirmed unused brokers. Module still ships so a
    # future operator could enable them, but they're not on the
    # C1/C2 critical path until someone actually runs them.
    "vanguard": "operator does not use Vanguard",
    "tradier": "operator does not use Tradier",
    "tornado": "operator does not use Tornado",
    "tasty": "operator does not use Tastytrade",
}
EXEMPT_ACCOUNT_FILTER: dict[str, str] = {
    # Same list, same rationale.
    "vanguard": "operator does not use Vanguard",
    "tradier": "operator does not use Tradier",
    "tornado": "operator does not use Tornado",
    "tasty": "operator does not use Tastytrade",
}

LEDGER_GUARD_CALLS = frozenset({"record_intent", "mark_result"})
ACCOUNT_FILTER_CALL = "account_allowed"

# The recommended helpers in src/helper_api.py wrap both guards into
# one call each. If a broker uses both helpers, treat C1 + C2 as
# satisfied without requiring the underlying primitives to be called
# directly.
HELPER_PRE_CALL = "reserve_or_skip"  # combines account_allowed + record_intent
HELPER_POST_CALL = "complete_or_fail"  # wraps mark_result


def _is_broker_module(path: Path) -> bool:
    """Return True for ``<broker>_api.py``; skip the ``_*`` patch helpers."""
    name = path.name
    return name.endswith("_api.py") and not name.startswith("_")


def _broker_key(path: Path) -> str:
    """``bbae_api.py`` -> ``bbae``."""
    return path.stem.removesuffix("_api")


def _function_calls(node: ast.AST) -> set[str]:
    """All callable names referenced anywhere in this subtree.

    Catches both bare ``record_intent(...)`` and ``self.X.mark_result(...)``
    via the attribute name. We're doing presence/absence detection
    (which is what the C1/C2 findings need), not flow analysis.
    """
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _calls_with_followed_helpers(
    tree: ast.Module,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Calls in ``fn`` PLUS calls inside any same-module functions it calls.

    SoFi-style brokers split ``broker_transaction`` into private async
    helpers (``_sofi_buy`` / ``_sofi_sell``); the C1/C2 guards must
    live somewhere in that call chain. One level of follow-through is
    enough — anything deeper is a code smell worth flagging anyway.
    """
    direct = _function_calls(fn)
    # Index this module's other top-level functions by name.
    by_name: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            by_name[node.name] = node
    followed: set[str] = set(direct)
    for name in direct:
        target = by_name.get(name)
        if target is not None and target is not fn:
            followed |= _function_calls(target)
    return followed


def _transaction_function(
    tree: ast.Module, broker_key: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the broker's transaction function at module top level.

    Prefers ``<broker_key>_transaction`` (e.g. ``bbae_transaction``)
    but also accepts any top-level function ending in ``_transaction``
    so file/function-prefix mismatches (e.g. ``tasty_api.py`` ->
    ``tastytrade_transaction``) don't escape audit.
    """
    target = f"{broker_key}_transaction"
    fallback: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == target:
            return node
        if node.name.endswith("_transaction") and fallback is None:
            fallback = node
    return fallback


def audit_file(path: Path) -> tuple[str, list[str]]:
    """Return ``(broker_key, findings)``; findings empty if clean."""
    broker = _broker_key(path)
    findings: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = _transaction_function(tree, broker)
    if fn is None:
        # Module exists but has no <broker>_transaction. Either
        # holdings-only or a non-conforming layout — surface it
        # but don't fail; the broker can't place orders so the
        # guards are moot.
        return broker, []
    calls = _calls_with_followed_helpers(tree, fn)

    # The helpers in src/helper_api.py wrap both guards. If both are
    # present, treat C1 + C2 as satisfied — but if only one helper is
    # present, that's a coding mistake worth flagging.
    helper_pre = HELPER_PRE_CALL in calls
    helper_post = HELPER_POST_CALL in calls
    uses_helpers = helper_pre and helper_post
    if (helper_pre and not helper_post) or (helper_post and not helper_pre):
        findings.append(
            f"helper mismatch: {fn.name} uses one of "
            f"{HELPER_PRE_CALL}/{HELPER_POST_CALL} but not both — these "
            "must be paired; an unmatched reserve leaks an INTENDED "
            "ledger row, an unmatched complete is a coding error.",
        )

    if broker not in EXEMPT_LEDGER and not uses_helpers:
        missing = LEDGER_GUARD_CALLS - calls
        if missing:
            findings.append(
                f"C1 ledger: {fn.name} does not call "
                f"{sorted(missing)} (or the helper pair "
                f"{HELPER_PRE_CALL}+{HELPER_POST_CALL}) — double-buy "
                "risk on retry. See src/brokerages/fidelity_api.py:267,288.",
            )

    if (
        broker not in EXEMPT_ACCOUNT_FILTER
        and not uses_helpers
        and ACCOUNT_FILTER_CALL not in calls
    ):
        findings.append(
            f"C2 filter: {fn.name} does not call "
            f"account_allowed() (or the helper {HELPER_PRE_CALL}) — "
            "RSA_ACCOUNT_FILTER silently bypassed. See "
            "src/brokerages/fidelity_api.py:247.",
        )

    return broker, findings


def audit_repo(repo_root: Path) -> tuple[int, list[tuple[str, list[str]]]]:
    """Walk ``src/brokerages/*_api.py`` and return ``(exit_code, results)``."""
    broker_dir = repo_root / "src" / "brokerages"
    files = sorted(p for p in broker_dir.glob("*.py") if _is_broker_module(p))
    results = [audit_file(p) for p in files]
    failed = any(findings for _, findings in results)
    return (1 if failed else 0), results


def main() -> int:
    """Run the audit against the current repo and return the exit code."""
    repo = Path(__file__).resolve().parents[1]
    code, results = audit_repo(repo)
    print(f"Auditing {len(results)} broker modules in {repo / 'src/brokerages'}\n")
    total_findings = 0
    for broker, findings in results:
        if findings:
            print(f"FAIL  {broker}")
            for f in findings:
                print(f"      {f}")
            total_findings += len(findings)
        else:
            print(f"ok    {broker}")
    print()
    if code:
        print(
            f"\n{total_findings} guard(s) missing across "
            f"{sum(1 for _, f in results if f)} broker(s).",
        )
        print(
            "Every broker that places orders must mirror "
            "src/brokerages/fidelity_api.py:",
        )
        print("  - account_allowed(broker_key, account, action) BEFORE the order")
        print("  - record_intent(Play(...), amount) BEFORE the order")
        print("  - mark_result(play, success=..., detail=...) AFTER the order")
    else:
        print("All brokers carry the required real-money guards.")
    return code


if __name__ == "__main__":
    sys.exit(main())
