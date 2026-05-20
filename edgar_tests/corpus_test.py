"""Data-driven corpus regression (skips when fixtures are absent).

Two guards (see edgar_tests/fixtures/README.md):
  * hist_alerts_v1.csv  -> real-money: announced ROUND_UP that actually
    wasn't a round-up must stay rare.
  * corpus_evidence.csv -> the ported classifier must still reproduce
    the hand-labeled policy, with zero dangerous flips.

Both print their baseline numbers so the thresholds can be tuned.
"""

import csv
from pathlib import Path

import pytest

from src.edgar.classify import parse_fractional_policy

_FIXTURES = Path(__file__).parent / "fixtures"
_HIST = _FIXTURES / "hist_alerts_v1.csv"
_EVID = _FIXTURES / "corpus_evidence.csv"

# Tune after seeing the first printed baseline.
MAX_FALSE_ROUND_UP_RATE = 0.05
MIN_PARITY_RATE = 0.95

_ROUNDUP = {"ROUND_UP", "ROUNDUP", "ROUND UP", "ROUNDED_UP"}
_NONPLAY = {
    "CASH_IN_LIEU",
    "AGGREGATED_SOLD_CASH",
    "ROUND_DOWN",
    "NO_FRACTIONAL_SHARES",
}


def _norm(v: object) -> str:
    return str(v or "").strip().upper().replace("-", "_").replace(" ", "_")


def _is_roundup(v: object) -> bool:
    n = _norm(v)
    return "ROUND_UP" in n or n in _ROUNDUP


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _col(row: dict[str, str], name: str) -> str:
    for k, v in row.items():
        if str(k).strip().upper() == name:
            return v
    return ""


@pytest.mark.skipif(not _HIST.exists(), reason="hist_alerts_v1.csv not provided")
def test_no_false_round_up_vs_actual_outcome():
    rows = _rows(_HIST)
    announced_up = [
        r for r in rows if _is_roundup(_col(r, "ANNOUNCED_FRACTIONAL_POLICY"))
    ]
    assert announced_up, "no ANNOUNCED ROUND_UP rows found — check headers"
    false_pos = [
        r
        for r in announced_up
        if _col(r, "ACTUAL_OUTCOME").strip()
        and not _is_roundup(_col(r, "ACTUAL_OUTCOME"))
    ]
    rate = len(false_pos) / len(announced_up)
    print(
        f"\n[hist_alerts_v1] announced ROUND_UP={len(announced_up)} "
        f"false (actual != round-up)={len(false_pos)} rate={rate:.3f}",
    )
    for r in false_pos[:20]:
        print(
            f"  {_col(r, 'TICKER')} {_col(r, 'EFFECTIVE_DATE')}: "
            f"actual={_col(r, 'ACTUAL_OUTCOME')!r} "
            f"cat={_col(r, 'OUTCOME_CATEGORY')!r}",
        )
    assert rate <= MAX_FALSE_ROUND_UP_RATE, (
        f"false ROUND_UP rate {rate:.3f} > {MAX_FALSE_ROUND_UP_RATE}"
    )


@pytest.mark.skipif(not _EVID.exists(), reason="corpus_evidence.csv not provided")
def test_classifier_parity_against_corpus():
    rows = _rows(_EVID)
    checked = matched = 0
    dangerous: list[tuple[str, str]] = []
    mismatches: list[tuple[str, str, str]] = []
    for r in rows:
        evidence = _col(r, "FRACTIONAL_EVIDENCE")
        recorded = _norm(_col(r, "FRACTIONAL_POLICY"))
        if not evidence or not recorded:
            continue
        checked += 1
        predicted = _norm(parse_fractional_policy(evidence).policy)
        if predicted == recorded:
            matched += 1
        else:
            mismatches.append((recorded, predicted, evidence[:90]))
            if predicted in _ROUNDUP and recorded in _NONPLAY:
                dangerous.append((recorded, evidence[:120]))
    assert checked, "no usable evidence/policy rows — check headers"
    parity = matched / checked
    print(
        f"\n[corpus_evidence] checked={checked} parity={parity:.3f} "
        f"dangerous_flips={len(dangerous)}",
    )
    for rec, pred, ev in mismatches[:20]:
        print(f"  recorded={rec} predicted={pred} :: {ev}")
    assert not dangerous, (
        f"{len(dangerous)} non-play(s) misclassified as ROUND_UP: "
        f"{dangerous[:5]}"
    )
    assert parity >= MIN_PARITY_RATE, (
        f"classifier parity {parity:.3f} < {MIN_PARITY_RATE}"
    )
