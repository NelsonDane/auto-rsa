"""Chase response-vs-request verification + tradeErrorMessages flattening (Phase 4 follow-up)."""

from __future__ import annotations

from src.brokerages.chase_api import _flatten_chase_error, _verify_chase_response


# --- _flatten_chase_error ---------------------------------------------

def test_flatten_empty_returns_empty():
    assert _flatten_chase_error("") == ""
    assert _flatten_chase_error([]) == ""
    assert _flatten_chase_error(None) == ""


def test_flatten_string_passthrough():
    assert _flatten_chase_error("Trade rejected") == "Trade rejected"


def test_flatten_list_joins_with_semicolon():
    """Operator should see a sentence-like reason, not a Python list repr."""
    out = _flatten_chase_error([
        "Trade rejected: insufficient buying power",
        "Account on hold",
    ])
    assert out == (
        "Trade rejected: insufficient buying power; Account on hold"
    )


def test_flatten_skips_empty_list_entries():
    assert _flatten_chase_error(["a", "", "b", None]) == "a; b"


def test_flatten_non_list_non_string_falls_back_to_str():
    assert _flatten_chase_error({"err": "x"}) == "{'err': 'x'}"


# --- _verify_chase_response -------------------------------------------

def _ok_validation(symbol="ICCM", qty=1, action="BUY"):
    """Build a plausible Chase ORDER VALIDATION dict."""
    return {
        "ORDER VALIDATION": {
            "securitySymbolCode": symbol,
            "orderQuantity": qty,
            "tradeActionName": action,
            "financialInformationExchangeSystemOrderIdentifier": "FIX-1",
        },
        "ORDER INVALID": "",
        "ORDER CONFIRMATION": "",
    }


def test_verify_match_returns_empty_string():
    msgs = _ok_validation(symbol="ICCM", qty=1, action="BUY")
    assert _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    ) == ""


def test_verify_wrong_symbol_returns_mismatch():
    msgs = _ok_validation(symbol="ICCMX", qty=1, action="BUY")
    out = _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    )
    assert "wrong symbol" in out
    assert "ICCM" in out and "ICCMX" in out


def test_verify_wrong_quantity_returns_mismatch():
    msgs = _ok_validation(symbol="ICCM", qty=2, action="BUY")
    out = _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    )
    assert "wrong quantity" in out


def test_verify_wrong_action_returns_mismatch():
    msgs = _ok_validation(symbol="ICCM", qty=1, action="SELL")
    out = _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    )
    assert "wrong action" in out


def test_verify_uses_order_confirmation_when_present():
    """Live runs populate ORDER CONFIRMATION; dry runs use ORDER VALIDATION.
    The verifier should pick either."""
    msgs = {
        "ORDER VALIDATION": "",
        "ORDER CONFIRMATION": {
            "securitySymbolCode": "WRONG",
            "orderQuantity": 1,
            "tradeActionName": "BUY",
        },
        "ORDER INVALID": "",
    }
    out = _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    )
    assert "wrong symbol" in out


def test_verify_no_response_dict_is_no_op():
    """Order short-circuited before validation responded — nothing to verify."""
    msgs = {
        "ORDER VALIDATION": "",
        "ORDER CONFIRMATION": "",
        "ORDER INVALID": "Some early failure",
    }
    assert _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    ) == ""


def test_verify_response_missing_symbol_field_is_no_op():
    """If Chase's response shape changes and securitySymbolCode is
    absent, don't fail loudly — just trust the existing ORDER INVALID
    pathway. We only abort on CLEAR mismatches, not on missing data."""
    msgs = {"ORDER VALIDATION": {"orderQuantity": 1, "tradeActionName": "BUY"}}
    assert _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    ) == ""


def test_verify_case_insensitive_match():
    """Chase's responses can return uppercase even when we sent
    mixed case. The boundary normalization in _execute_single_order
    uppercases the input; the verifier uppercases both sides too."""
    msgs = _ok_validation(symbol="iccm", qty=1, action="buy")
    assert _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    ) == ""


def test_verify_unparseable_quantity_does_not_block():
    """Chase has been observed to return qty as a string in some
    fields. Don't fail the order because of a serialization quirk."""
    msgs = {
        "ORDER VALIDATION": {
            "securitySymbolCode": "ICCM",
            "orderQuantity": "n/a",
            "tradeActionName": "BUY",
        },
    }
    # No exception, no mismatch on a flaky qty field.
    assert _verify_chase_response(
        msgs, symbol="ICCM", quantity=1, action="BUY",
    ) == ""
