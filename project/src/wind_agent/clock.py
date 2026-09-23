"""Explicit clocks and point-in-time knowledge filtering."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar

from wind_agent.errors import ContractNotConfirmedError
from wind_agent.schemas import AvailableRecord, ContractMode, HourlyInterval


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class ReplayClock:
    """A fixed clock; replay code cannot accidentally inspect wall time."""

    origin_utc: datetime

    def __post_init__(self) -> None:
        _require_utc(self.origin_utc, "origin_utc")

    def now(self) -> datetime:
        return self.origin_utc


def hourly_intervals(origin_utc: datetime, horizon: int = 48) -> tuple[HourlyInterval, ...]:
    """Generate consecutive [start, end) UTC intervals after an origin."""

    _require_utc(origin_utc, "origin_utc")
    if horizon < 1:
        raise ValueError("horizon must be at least one interval")
    return tuple(
        HourlyInterval(
            start_utc=origin_utc + timedelta(hours=lead - 1),
            end_utc=origin_utc + timedelta(hours=lead),
            lead_end_hours=lead,
        )
        for lead in range(1, horizon + 1)
    )


RecordT = TypeVar("RecordT", bound=AvailableRecord)


@dataclass(frozen=True)
class KnowledgePolicy:
    """Permit only records known no later than the forecast origin."""

    mode: ContractMode
    time_contract_confirmed: bool
    version: str = "1"

    def validate_operation(self) -> None:
        if self.mode is ContractMode.STRICT and not self.time_contract_confirmed:
            raise ContractNotConfirmedError(
                "strict mode requires a confirmed SCADA time and availability contract"
            )

    def known_at(self, records: Iterable[RecordT], origin_utc: datetime) -> list[RecordT]:
        self.validate_operation()
        _require_utc(origin_utc, "origin_utc")
        return [record for record in records if record.available_at_utc <= origin_utc]


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must use UTC")
