"""Metadata describing how each supported broker's credentials map to env vars.

This is the single source of truth the GUI uses to render credential forms
and to assemble the environment variables the existing broker scripts read.

Only the brokers the user requested are exposed here:
Chase, Robinhood, Wells Fargo, Fennel, Fidelity, DSPAC, BBAE, Schwab,
Webull, Public. (Ally is not supported by this repo.)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A single credential input for a broker account."""

    key: str
    label: str
    secret: bool = False
    optional: bool = False
    # Value substituted into the env string when the user leaves this blank.
    # e.g. the TOTP slot must become "NA" for Robinhood/Fidelity/Schwab.
    empty_value: str | None = None
    # If True and left blank, the field (and trailing separator) is omitted
    # entirely instead of inserting empty_value. Only valid for trailing fields.
    omit_if_empty: bool = False
    help: str = ""


@dataclass(frozen=True, slots=True)
class BrokerMeta:
    """How one broker's account credentials map to an env variable."""

    key: str  # internal key + StockOrder/CLI broker name
    display_name: str
    env_var: str
    fields: tuple[FieldSpec, ...]
    notes: str = ""
    # Optional broker-level extra env vars (not per-account), e.g. Schwab
    # account numbers. Maps env var name -> human label.
    extra_env: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    browser_based: bool = False

    def assemble_account(self, values: dict[str, str]) -> str:
        """Build the colon-delimited env value for a single account."""
        parts: list[str] = []
        for spec in self.fields:
            raw = (values.get(spec.key) or "").strip()
            if not raw and spec.omit_if_empty:
                # Trailing optional field: drop it entirely.
                continue
            if not raw and spec.empty_value is not None:
                raw = spec.empty_value
            parts.append(raw)
        return ":".join(parts)

    def assemble_env_value(self, accounts: list[dict[str, str]]) -> str:
        """Build the full env value (multiple accounts joined by comma)."""
        return ",".join(
            self.assemble_account(acc)
            for acc in accounts
            if any((v or "").strip() for v in acc.values())
        )


_USERNAME = FieldSpec("username", "Username / Email")
_PASSWORD = FieldSpec("password", "Password", secret=True)


SUPPORTED_BROKERS: tuple[BrokerMeta, ...] = (
    BrokerMeta(
        key="bbae",
        display_name="BBAE",
        env_var="BBAE",
        fields=(_USERNAME, _PASSWORD),
    ),
    BrokerMeta(
        key="chase",
        display_name="Chase",
        env_var="CHASE",
        browser_based=True,
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec("phone_last_four", "Cell phone last 4 digits"),
            FieldSpec(
                "debug",
                "Debug (true/false)",
                optional=True,
                omit_if_empty=True,
                help="Leave blank unless debugging the Chase browser flow.",
            ),
        ),
        notes="Browser-based (Selenium). Expect a phone verification prompt.",
    ),
    BrokerMeta(
        key="dspac",
        display_name="DSPAC",
        env_var="DSPAC",
        fields=(_USERNAME, _PASSWORD),
    ),
    BrokerMeta(
        key="fennel",
        display_name="Fennel",
        env_var="FENNEL",
        fields=(
            FieldSpec(
                "pat",
                "Fennel access token (PAT)",
                secret=True,
                help="Personal access token from the Fennel app.",
            ),
        ),
    ),
    BrokerMeta(
        key="fidelity",
        display_name="Fidelity",
        env_var="FIDELITY",
        browser_based=True,
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec(
                "totp_secret",
                "TOTP secret (optional)",
                secret=True,
                optional=True,
                empty_value="NA",
                help="Authenticator secret. Leave blank if 2FA is not enabled.",
            ),
        ),
        notes="Browser-based (Playwright). Slower; may prompt for a 2FA code.",
    ),
    BrokerMeta(
        key="public",
        display_name="Public",
        env_var="PUBLIC_BROKER",
        fields=(
            FieldSpec(
                "api_key",
                "Public API key",
                secret=True,
                help="API key generated from your Public account.",
            ),
        ),
    ),
    BrokerMeta(
        key="robinhood",
        display_name="Robinhood",
        env_var="ROBINHOOD",
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec(
                "totp_secret",
                "TOTP secret (optional)",
                secret=True,
                optional=True,
                empty_value="NA",
                help="Authenticator secret. Leave blank if 2FA is not enabled "
                "(you'll get a phone-app prompt instead).",
            ),
        ),
    ),
    BrokerMeta(
        key="schwab",
        display_name="Schwab",
        env_var="SCHWAB",
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec(
                "totp_secret",
                "TOTP secret (optional)",
                secret=True,
                optional=True,
                empty_value="NA",
                help="Authenticator secret. Leave blank if 2FA is not enabled.",
            ),
        ),
        extra_env=(("SCHWAB_ACCOUNT_NUMBERS", "Account numbers (colon-separated, optional)"),),
    ),
    BrokerMeta(
        key="sofi",
        display_name="SoFi",
        env_var="SOFI",
        browser_based=True,
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec(
                "totp_secret",
                "TOTP secret (optional)",
                secret=True,
                optional=True,
                omit_if_empty=True,
                help="Authenticator secret. With it, login is automatic "
                "and the browser is remembered (unattended-ready). Leave "
                "blank to use SMS 2FA each run.",
            ),
        ),
        notes="Browser-based (nodriver — needs system Google Chrome).",
    ),
    BrokerMeta(
        key="webull",
        display_name="Webull",
        env_var="WEBULL",
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec("did", "Device ID (DID)", help="Webull device id."),
            FieldSpec("trading_pin", "Trading PIN", secret=True),
        ),
    ),
    BrokerMeta(
        key="wellsfargo",
        display_name="Wells Fargo",
        env_var="WELLSFARGO",
        browser_based=True,
        fields=(
            _USERNAME,
            _PASSWORD,
            FieldSpec("phone_last_four", "Phone last 4 digits"),
        ),
        notes="Browser-based (Selenium). Expect a phone verification prompt.",
    ),
)

BROKERS_BY_KEY: dict[str, BrokerMeta] = {b.key: b for b in SUPPORTED_BROKERS}


def get_broker(key: str) -> BrokerMeta:
    """Look up a broker's metadata by key."""
    return BROKERS_BY_KEY[key]
