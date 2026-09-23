from datetime import UTC, datetime, timedelta

import pytest

from wind_agent.clock import KnowledgePolicy, ReplayClock, hourly_intervals
from wind_agent.errors import ContractNotConfirmedError
from wind_agent.schemas import AvailableRecord, ContractMode


def test_replay_clock_never_reads_wall_clock() -> None:
    origin = datetime(2026, 2, 28, tzinfo=UTC)
    assert ReplayClock(origin).now() == origin


def test_hourly_intervals_are_left_closed_and_have_correct_leads() -> None:
    origin = datetime(2026, 1, 31, tzinfo=UTC)
    intervals = hourly_intervals(origin, 48)
    assert len(intervals) == 48
    assert intervals[0].start_utc == origin
    assert intervals[0].end_utc == origin + timedelta(hours=1)
    assert intervals[-1].end_utc == origin + timedelta(hours=48)
    assert intervals[-1].lead_end_hours == 48


def test_hourly_intervals_support_leap_day() -> None:
    origin = datetime(2024, 2, 28, 23, tzinfo=UTC)
    assert hourly_intervals(origin, 2)[1].end_utc == datetime(2024, 2, 29, 1, tzinfo=UTC)


def test_hourly_intervals_reject_naive_origin() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        hourly_intervals(datetime(2026, 1, 31))


def test_strict_policy_rejects_unconfirmed_time_contract() -> None:
    policy = KnowledgePolicy(ContractMode.STRICT, time_contract_confirmed=False)
    with pytest.raises(ContractNotConfirmedError):
        policy.known_at([], datetime(2026, 1, 31, tzinfo=UTC))


def test_knowledge_policy_excludes_future_records() -> None:
    origin = datetime(2026, 1, 31, tzinfo=UTC)
    records = [
        AvailableRecord(record_id="known", available_at_utc=origin),
        AvailableRecord(record_id="future", available_at_utc=origin + timedelta(seconds=1)),
    ]
    policy = KnowledgePolicy(ContractMode.PROVISIONAL, time_contract_confirmed=False)
    assert [record.record_id for record in policy.known_at(records, origin)] == ["known"]
