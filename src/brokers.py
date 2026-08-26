"""Contains Info For All Brokerages."""

from dataclasses import dataclass
from enum import StrEnum


class BrokerName(StrEnum):
    """Enumeration of Broker Names."""

    BBAE = "bbae"
    CHASE = "chase"
    DSPAC = "dspac"
    FENNEL = "fennel"
    FIDELITY = "fidelity"
    FIRSTRADE = "firstrade"
    PUBLIC = "public"
    ROBINHOOD = "robinhood"
    SCHWAB = "schwab"
    SOFI = "sofi"
    TASTYTRADE = "tastytrade"
    TORNADO = "tornado"
    TRADIER = "tradier"
    VANGUARD = "vanguard"
    WEBULL = "webull"
    WELLS_FARGO = "wellsfargo"


@dataclass(frozen=True, slots=True)
class BrokerInfo:
    """Information about a single supported brokerage."""

    name: BrokerName
    nicknames: tuple[str, ...]
    day1: bool
    fast: bool


# Data table of all supported brokers. Add a new broker by adding a row here.
ALL_BROKERS: tuple[BrokerInfo, ...] = (
    BrokerInfo(name=BrokerName.BBAE, nicknames=("bb",), day1=True, fast=True),
    BrokerInfo(name=BrokerName.CHASE, nicknames=(), day1=True, fast=False),
    BrokerInfo(name=BrokerName.DSPAC, nicknames=("ds",), day1=True, fast=True),
    BrokerInfo(name=BrokerName.FENNEL, nicknames=(), day1=True, fast=False),
    BrokerInfo(name=BrokerName.FIDELITY, nicknames=("fid", "fido"), day1=False, fast=False),
    BrokerInfo(name=BrokerName.FIRSTRADE, nicknames=("ft",), day1=True, fast=True),
    BrokerInfo(name=BrokerName.PUBLIC, nicknames=(), day1=True, fast=True),
    BrokerInfo(name=BrokerName.ROBINHOOD, nicknames=("rh",), day1=False, fast=True),
    BrokerInfo(name=BrokerName.SCHWAB, nicknames=(), day1=True, fast=True),
    BrokerInfo(name=BrokerName.SOFI, nicknames=(), day1=True, fast=False),
    BrokerInfo(name=BrokerName.TASTYTRADE, nicknames=("tt", "tasty"), day1=True, fast=True),
    BrokerInfo(name=BrokerName.TORNADO, nicknames=(), day1=False, fast=True),
    BrokerInfo(name=BrokerName.TRADIER, nicknames=(), day1=True, fast=True),
    BrokerInfo(name=BrokerName.VANGUARD, nicknames=("vg",), day1=False, fast=False),
    BrokerInfo(name=BrokerName.WEBULL, nicknames=("wb",), day1=True, fast=True),
    BrokerInfo(name=BrokerName.WELLS_FARGO, nicknames=("wf",), day1=False, fast=False),
)


class AllBrokersInfo:
    """Aggregate Broker Information for all supported brokers."""

    def __init__(self) -> None:
        """Initialize All Brokers Information."""
        self.brokers: list[BrokerInfo] = list(ALL_BROKERS)

    def parse_input(self, user_input: str) -> BrokerInfo | None:
        """Parse user input and return the corresponding BrokerInfo object."""
        user_input = user_input.lower()
        for broker in self.brokers:
            if broker.name.lower() == user_input or user_input in broker.nicknames:
                return broker
        return None

    def get_day_one(self) -> list[BrokerInfo]:
        """Get a list of brokers that support Day 1 trading."""
        return [broker for broker in self.brokers if broker.day1]

    def get_fast(self) -> list[BrokerInfo]:
        """Get a list of brokers that aren't slow as molasses."""
        return [broker for broker in self.brokers if broker.fast]

    def get_all(self) -> list[BrokerInfo]:
        """Get a list of all brokers."""
        return self.brokers

    def get_most(self) -> list[BrokerInfo]:
        """Get all except Vanguard. Not sure why we have this."""
        return [broker for broker in self.brokers if broker.name != BrokerName.VANGUARD]
