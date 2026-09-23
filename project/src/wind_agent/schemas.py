"""Shared, versioned contracts for time and data availability."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractMode(StrEnum):
    STRICT = "strict"
    PROVISIONAL = "provisional"
    SYNTHETIC = "synthetic"


class TimestampSemantics(StrEnum):
    INTERVAL_START = "interval_start"
    INTERVAL_END = "interval_end"


class HourlyInterval(BaseModel):
    """A left-closed, right-open forecast interval in UTC."""

    model_config = ConfigDict(frozen=True)

    start_utc: datetime
    end_utc: datetime
    lead_end_hours: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_utc_interval(self) -> "HourlyInterval":
        for value in (self.start_utc, self.end_utc):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("interval datetimes must be timezone-aware")
        if self.start_utc.utcoffset().total_seconds() != 0:
            raise ValueError("start_utc must use UTC")
        if self.end_utc.utcoffset().total_seconds() != 0:
            raise ValueError("end_utc must use UTC")
        if (self.end_utc - self.start_utc).total_seconds() != 3600:
            raise ValueError("an hourly interval must be exactly 3600 seconds")
        return self


class AvailableRecord(BaseModel):
    """Minimal record carrying point-in-time availability metadata."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    available_at_utc: datetime

    @model_validator(mode="after")
    def validate_available_at(self) -> "AvailableRecord":
        value = self.available_at_utc
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at_utc must be timezone-aware")
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("available_at_utc must use UTC")
        return self
