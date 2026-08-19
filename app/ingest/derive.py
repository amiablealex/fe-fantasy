"""Derivation: turning a flat list of events into meetings, rounds and formats.

Pure functions over provider dataclasses. No database, no Flask — so the rules
that decide what a race weekend *is* can be tested directly, which matters
because they are the rules most likely to need adjusting when the calendar does
something unexpected.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.calendar import ROUND_FORMAT_EPRIX, ROUND_FORMAT_EPRIX_UNLEASHED
from app.providers.base import EventSummary

# Two events at the same location within this many days are the same meeting.
# Formula E double-headers run on consecutive days, so 1 would do; 3 leaves room
# for a Friday/Sunday split without grouping two separate visits to the same
# circuit months apart.
DEFAULT_ADJACENCY_DAYS = 3

# Season 13 (ending year 2027) is the first with two race formats. Before that,
# every race was a standard E-Prix — including both halves of a double-header.
#
# This gate is not cosmetic. Applying the Season 13 rule to the Season 12
# backfill would label half the calendar as sprints that never happened, and the
# Phase 2 simulation would then draw format-aware conclusions from fiction.
FIRST_UNLEASHED_SEASON_YEAR = 2027


@dataclass(frozen=True)
class DerivedRound:
    event_id: str
    round_number: int
    number_in_meeting: int
    format: str


@dataclass(frozen=True)
class DerivedMeeting:
    sequence: int
    location_provider_id: str
    display_name: str
    rounds: tuple[DerivedRound, ...]

    @property
    def event_ids(self) -> frozenset[str]:
        return frozenset(r.event_id for r in self.rounds)

    @property
    def first_round(self) -> DerivedRound:
        return min(self.rounds, key=lambda r: r.round_number)

    @property
    def is_double_header(self) -> bool:
        return len(self.rounds) > 1


def meeting_display_name(event: EventSummary) -> str:
    """A clean name for the weekend.

    Never the event name: that carries the sponsor ("2026 Hankook London
    E-Prix"), which changes year to year and would make "every London race" an
    impossible query.
    """
    location = event.location
    if location is None:
        return event.name or "Unknown"
    return location.city or location.name or "Unknown"


def assign_round_numbers(events: list[EventSummary]) -> list[int]:
    """Round numbers are position in the season calendar, 1-based.

    The API has no round field anywhere. The only source is order within
    `season_detail.schedule`, and that ordering is also what the provider's
    `participationRounds` arrays refer to — so calendar order is used as given
    rather than re-sorted by date, because re-sorting would desynchronise the
    two.
    """
    return list(range(1, len(events) + 1))


def calendar_is_date_ordered(events: list[EventSummary]) -> bool:
    """Whether the calendar is ascending by date.

    Expected, but not relied upon. If it ever comes back unordered the sync logs
    it rather than reordering, because reordering would break the mapping to
    `participationRounds`.
    """
    dates = [e.date_start for e in events if e.date_start]
    return dates == sorted(dates)


def derive_format(
    season_ending_year: int, number_in_meeting: int, rounds_in_meeting: int
) -> str:
    """Which race format a round runs.

    From Season 13, a double-header's first race is an E-Prix Unleashed (30
    minutes, high downforce, no Pit Boost) and its second a standard E-Prix.
    Single-headers are always standard.

    The regulations say double-headers "typically" carry one of each, so this is
    a default and `Round.format_locked` exists to override it.
    """
    if season_ending_year < FIRST_UNLEASHED_SEASON_YEAR:
        return ROUND_FORMAT_EPRIX
    if rounds_in_meeting <= 1:
        return ROUND_FORMAT_EPRIX
    return ROUND_FORMAT_EPRIX_UNLEASHED if number_in_meeting == 1 else ROUND_FORMAT_EPRIX


def _same_meeting(previous: EventSummary, current: EventSummary, adjacency_days: int) -> bool:
    if previous.location is None or current.location is None:
        return False
    if previous.location.id != current.location.id:
        return False
    if previous.date_start is None or current.date_start is None:
        return False
    return abs((current.date_start - previous.date_start).days) <= adjacency_days


def derive_meetings(
    events: list[EventSummary],
    season_ending_year: int,
    adjacency_days: int = DEFAULT_ADJACENCY_DAYS,
) -> list[DerivedMeeting]:
    """Group calendar events into meetings.

    Grouping is on `location.id` plus date adjacency, over *consecutive* events
    only. Consecutiveness is what stops two separate visits to the same circuit
    — Berlin in May and Berlin again in July, say — collapsing into one weekend.
    """
    if not events:
        return []

    round_numbers = assign_round_numbers(events)
    groups: list[list[tuple[EventSummary, int]]] = []

    for event, round_number in zip(events, round_numbers):
        if groups and _same_meeting(groups[-1][-1][0], event, adjacency_days):
            groups[-1].append((event, round_number))
        else:
            groups.append([(event, round_number)])

    meetings: list[DerivedMeeting] = []
    for sequence, group in enumerate(groups, start=1):
        size = len(group)
        rounds = tuple(
            DerivedRound(
                event_id=event.id,
                round_number=round_number,
                number_in_meeting=index,
                format=derive_format(season_ending_year, index, size),
            )
            for index, (event, round_number) in enumerate(group, start=1)
        )
        first_event = group[0][0]
        meetings.append(
            DerivedMeeting(
                sequence=sequence,
                location_provider_id=(
                    first_event.location.id if first_event.location else ""
                ),
                display_name=meeting_display_name(first_event),
                rounds=rounds,
            )
        )
    return meetings


def earliest_qualifying_start(events: list[EventSummary]) -> datetime | None:
    """The deadline instant for a meeting: earliest qualifying session start
    across the given events (in practice, the meeting's first round).

    None when the schedule has not been published yet, which is a normal state
    for a future meeting and must leave the meeting unlocked rather than
    locking it by accident.
    """
    times = [
        session.start_time
        for event in events
        for session in event.qualifying_sessions
        if session.start_time
    ]
    return min(times) if times else None
