"""Contains Info For All Brokerages."""

from dataclasses import dataclass, field
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
    """Base Class for Broker Information."""

    name: BrokerName
    nicknames: tuple[str, ...]
    day1: bool
    fast: bool


@dataclass(frozen=True, slots=True)
class BbaeInfo(BrokerInfo):
    """Broker Information for BBAE."""

    name: BrokerName = BrokerName.BBAE
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("bb",))
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class ChaseInfo(BrokerInfo):
    """Broker Information for CHASE."""

    name: BrokerName = BrokerName.CHASE
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = False


@dataclass(frozen=True, slots=True)
class DspacInfo(BrokerInfo):
    """Broker Information for DSPAC."""

    name: BrokerName = BrokerName.DSPAC
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("ds",))
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class FennelInfo(BrokerInfo):
    """Broker Information for FENNEL."""

    name: BrokerName = BrokerName.FENNEL
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = False


@dataclass(frozen=True, slots=True)
class FidelityInfo(BrokerInfo):
    """Broker Information for FIDELITY."""

    name: BrokerName = BrokerName.FIDELITY
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("fid", "fido"))
    day1: bool = False
    fast: bool = False


@dataclass(frozen=True, slots=True)
class FirstradeInfo(BrokerInfo):
    """Broker Information for FIRSTRADE."""

    name: BrokerName = BrokerName.FIRSTRADE
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("ft",))
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class PublicInfo(BrokerInfo):
    """Broker Information for PUBLIC."""

    name: BrokerName = BrokerName.PUBLIC
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class RobinhoodInfo(BrokerInfo):
    """Broker Information for ROBINHOOD."""

    name: BrokerName = BrokerName.ROBINHOOD
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("rh",))
    day1: bool = False
    fast: bool = True


@dataclass(frozen=True, slots=True)
class SchwabInfo(BrokerInfo):
    """Broker Information for SCHWAB."""

    name: BrokerName = BrokerName.SCHWAB
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class SofiInfo(BrokerInfo):
    """Broker Information for SOFI."""

    name: BrokerName = BrokerName.SOFI
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = False


@dataclass(frozen=True, slots=True)
class TastytradeInfo(BrokerInfo):
    """Broker Information for TASTYTRADE."""

    name: BrokerName = BrokerName.TASTYTRADE
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("tt", "tasty"))
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class TornadoInfo(BrokerInfo):
    """Broker Information for TORNADO."""

    name: BrokerName = BrokerName.TORNADO
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = False
    fast: bool = True


@dataclass(frozen=True, slots=True)
class TradierInfo(BrokerInfo):
    """Broker Information for TRADIER."""

    name: BrokerName = BrokerName.TRADIER
    nicknames: tuple[str, ...] = field(default_factory=tuple[str, ...])
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class VanguardInfo(BrokerInfo):
    """Broker Information for VANGUARD."""

    name: BrokerName = BrokerName.VANGUARD
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("vg",))
    day1: bool = False
    fast: bool = False


@dataclass(frozen=True, slots=True)
class WebullInfo(BrokerInfo):
    """Broker Information for WEBULL."""

    name: BrokerName = BrokerName.WEBULL
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("wb",))
    day1: bool = True
    fast: bool = True


@dataclass(frozen=True, slots=True)
class WellsFargoInfo(BrokerInfo):
    """Broker Information for WELLS FARGO."""

    name: BrokerName = BrokerName.WELLS_FARGO
    nicknames: tuple[str, ...] = field(default_factory=lambda: ("wf",))
    day1: bool = False
    fast: bool = False


class AllBrokersInfo:
    """Aggregate Broker Information for all supported brokers."""

    def __init__(self) -> None:
        """Initialize All Brokers Information."""
        self.brokers: list[BrokerInfo] = [
            BbaeInfo(),
            ChaseInfo(),
            DspacInfo(),
            FennelInfo(),
            FidelityInfo(),
            FirstradeInfo(),
            PublicInfo(),
            RobinhoodInfo(),
            SchwabInfo(),
            SofiInfo(),
            TastytradeInfo(),
            TornadoInfo(),
            TradierInfo(),
            VanguardInfo(),
            WebullInfo(),
            WellsFargoInfo(),
        ]

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
