"""Season sync.

Fetches a season from the provider and writes it down: locations, drivers,
teams, seat entries, meetings, rounds, sessions and deadlines.

Two structural commitments, both from SPEC.md §6:

  1. **Each meeting commits in its own transaction.** An unsafe change rolls
     that meeting back untouched and records a conflict; the other twelve apply
     normally. Nothing ever half-applies, and one calendar oddity never blocks
     a whole sync.

  2. **Safe changes apply silently, unsafe ones stop and flag.** The whole point
     is that this can run unattended twice a day and only ask for attention when
     something genuinely needs a human.

Idempotent throughout: running it twice produces the same database as once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.ingest.conflicts import record_conflict
from app.ingest.derive import (
    DEFAULT_ADJACENCY_DAYS,
    DerivedMeeting,
    calendar_is_date_ordered,
    derive_meetings,
    earliest_qualifying_start,
)
from app.ingest.stages import (
    EXPECTED_QUALIFYING_SESSION_COUNT,
    UnrecognisedQualifyingSession,
    derive_stage,
)
from app.models.calendar import (
    SESSION_TYPE_QUALIFYING,
    Location,
    Meeting,
    Round,
    Season,
    Session,
    default_season_display_name,
)
from app.models.grid import Driver, SeatEntry, Team
from app.models.result import (
    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
    CONFLICT_MEETING_REGROUPED,
    CONFLICT_ROUND_DISAPPEARED,
    CONFLICT_ROUND_RENUMBERED,
    CONFLICT_UNEXPECTED_SESSION_SHAPE,
    CONFLICT_UNRECOGNISED_QUALIFYING_SESSION,
)
from app.providers.base import EventSummary, SeasonDetail
from app.scoring.rules import CURRENT_VERSION

log = logging.getLogger(__name__)

# Sequences are renumbered via a temporary offset so a shifted calendar cannot
# collide with the (season_id, sequence) unique constraint mid-update.
_SEQUENCE_OFFSET = 10_000


class SeasonNotPublished(RuntimeError):
    """The provider has no season for that ending year yet.

    A normal condition, not a failure: Season 13 will not appear in the seasons
    index until the vendor adds it.
    """


@dataclass
class SyncReport:
    season_year: int
    season_id: int | None = None
    meetings_created: int = 0
    meetings_updated: int = 0
    meetings_skipped: int = 0
    rounds_created: int = 0
    sessions_created: int = 0
    sessions_updated: int = 0
    drivers_seen: int = 0
    teams_seen: int = 0
    seat_entries_written: int = 0
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def summary(self) -> str:
        return (
            f"season {self.season_year}: "
            f"{self.meetings_created} meetings created, "
            f"{self.meetings_updated} updated, "
            f"{self.meetings_skipped} skipped, "
            f"{self.rounds_created} rounds, "
            f"{self.sessions_created} sessions, "
            f"{len(self.conflicts)} conflicts"
        )


# -----------------------------------------------------------------------------
# Upsert helpers
# -----------------------------------------------------------------------------


def _upsert_season(detail: SeasonDetail) -> Season:
    season = db.session.scalar(
        select(Season).where(Season.provider_season_id == detail.season.id)
    )
    if season is None:
        season = Season(
            provider_season_id=detail.season.id,
            year=detail.season.year,
            display_name=default_season_display_name(detail.season.year),
        )
        db.session.add(season)
    season.last_synced_at = datetime.now(timezone.utc)
    return season


def _upsert_location(event: EventSummary) -> Location | None:
    if event.location is None:
        return None
    provider_id = event.location.id
    location = db.session.scalar(
        select(Location).where(Location.provider_location_id == provider_id)
    )
    if location is None:
        location = Location(provider_location_id=provider_id)
        db.session.add(location)
    location.name = event.location.name
    location.city = event.location.city
    if event.location.country:
        location.country_name = event.location.country.name
        location.country_two_code = event.location.country.two_code
        location.country_three_code = event.location.country.three_code
    return location


def _upsert_driver(standing) -> Driver:
    driver = db.session.scalar(
        select(Driver).where(Driver.provider_driver_id == standing.id)
    )
    if driver is None:
        driver = Driver(provider_driver_id=standing.id)
        db.session.add(driver)
    driver.first_name = standing.first_name
    driver.last_name = standing.last_name
    driver.code = standing.code
    driver.number = standing.number
    return driver


def _upsert_team(team_id: str, name=None, short_name=None, color=None) -> Team:
    team = db.session.scalar(select(Team).where(Team.provider_team_id == team_id))
    if team is None:
        team = Team(provider_team_id=team_id)
        db.session.add(team)
    if name is not None:
        team.name = name
    if short_name is not None:
        team.short_name = short_name
    if color is not None:
        team.color = color
    return team


def _sync_grid(detail: SeasonDetail, season: Season, report: SyncReport) -> None:
    """Drivers, teams and seat entries.

    Committed before any meeting work so a later per-meeting rollback cannot
    take the roster with it.
    """
    for team_standing in detail.teams:
        _upsert_team(
            team_standing.id,
            name=team_standing.name,
            short_name=team_standing.short_name,
            color=team_standing.color,
        )
    db.session.flush()

    for standing in detail.drivers:
        driver = _upsert_driver(standing)
        db.session.flush()

        for participation in standing.teams:
            team = _upsert_team(
                participation.team_id,
                name=participation.name,
                short_name=participation.short_name,
                color=participation.color,
            )
            db.session.flush()

            seat = db.session.scalar(
                select(SeatEntry).where(
                    SeatEntry.season_id == season.id,
                    SeatEntry.driver_id == driver.id,
                    SeatEntry.team_id == team.id,
                )
            )
            if seat is None:
                seat = SeatEntry(
                    season_id=season.id, driver_id=driver.id, team_id=team.id
                )
                db.session.add(seat)
            # Always overwrite: this is a live counter that grows through the
            # season, and the provider is authoritative for it.
            seat.participation_rounds = list(participation.participation_rounds)
            report.seat_entries_written += 1

    report.drivers_seen = len(detail.drivers)
    report.teams_seen = len(detail.teams)


# -----------------------------------------------------------------------------
# Session sync for one round
# -----------------------------------------------------------------------------


def _sync_sessions(round_row: Round, event: EventSummary, report: SyncReport) -> None:
    """Write the round's sessions.

    Raises UnrecognisedQualifyingSession if a qualifying session cannot be
    placed in the bracket — the caller turns that into a conflict and rolls the
    meeting back, because scoring an incomplete bracket would silently lose
    points.
    """
    for ordinal, session in enumerate(event.sessions, start=1):
        stage, stage_index = derive_stage(session.name, session.type)

        row = db.session.scalar(
            select(Session).where(Session.provider_session_id == session.id)
        )
        if row is None:
            row = Session(provider_session_id=session.id, round_id=round_row.id)
            db.session.add(row)
            report.sessions_created += 1
        else:
            report.sessions_updated += 1

        row.round_id = round_row.id
        row.name = session.name
        row.type = session.type
        row.stage = stage
        row.stage_index = stage_index
        row.ordinal = ordinal
        row.start_time = session.start_time
        row.end_time = session.end_time
        row.status = session.status


def _check_bracket_shape(event: EventSummary) -> int | None:
    """Return the qualifying session count if it looks wrong, else None.

    Only meaningful once a round has actually happened: a future round often has
    a partial schedule, and flagging that every twelve hours would train you to
    ignore the conflicts page.
    """
    qualifying = [s for s in event.sessions if s.type == SESSION_TYPE_QUALIFYING]
    if not qualifying:
        return None
    if event.status != "completed":
        return None
    if len(qualifying) != EXPECTED_QUALIFYING_SESSION_COUNT:
        return len(qualifying)
    return None


# -----------------------------------------------------------------------------
# One meeting
# -----------------------------------------------------------------------------


def _sync_meeting(
    season: Season,
    derived: DerivedMeeting,
    events_by_id: dict[str, EventSummary],
    report: SyncReport,
) -> None:
    """Sync one meeting inside its own transaction.

    Commits on success; rolls back and records a conflict on anything unsafe.
    """
    event_ids = [r.event_id for r in derived.rounds]
    existing_rounds = list(
        db.session.scalars(
            select(Round).where(Round.provider_event_id.in_(event_ids))
        )
    )
    meeting_ids = {r.meeting_id for r in existing_rounds}

    try:
        # --- guard: the rounds must not already be split across meetings -----
        if len(meeting_ids) > 1:
            raise _Unsafe(
                CONFLICT_MEETING_REGROUPED,
                {
                    "reason": "rounds of this weekend currently belong to different meetings",
                    "display_name": derived.display_name,
                    "event_ids": event_ids,
                    "meeting_ids": sorted(m for m in meeting_ids if m is not None),
                },
                identity=(derived.location_provider_id, tuple(sorted(event_ids))),
            )

        meeting = None
        if meeting_ids:
            meeting = db.session.get(Meeting, meeting_ids.pop())

        # --- guard: a stored meeting must not lose rounds --------------------
        if meeting is not None:
            stored_event_ids = {r.provider_event_id for r in meeting.rounds}
            lost = stored_event_ids - set(event_ids)
            if lost:
                raise _Unsafe(
                    CONFLICT_ROUND_DISAPPEARED,
                    {
                        "display_name": meeting.display_name,
                        "missing_event_ids": sorted(lost),
                        "still_present": sorted(set(event_ids)),
                    },
                    identity=(meeting.id, tuple(sorted(lost))),
                )

        # --- guard: round numbers are immutable once assigned ---------------
        for stored in existing_rounds:
            proposed = next(
                r.round_number for r in derived.rounds
                if r.event_id == stored.provider_event_id
            )
            if stored.round_number != proposed:
                raise _Unsafe(
                    CONFLICT_ROUND_RENUMBERED,
                    {
                        "event_id": stored.provider_event_id,
                        "stored_round_number": stored.round_number,
                        "proposed_round_number": proposed,
                    },
                    identity=(stored.provider_event_id,),
                )

        # --- guard: bracket shape on completed rounds -----------------------
        for derived_round in derived.rounds:
            event = events_by_id[derived_round.event_id]
            wrong_count = _check_bracket_shape(event)
            if wrong_count is not None:
                raise _Unsafe(
                    CONFLICT_UNEXPECTED_SESSION_SHAPE,
                    {
                        "event_id": event.id,
                        "round_number": derived_round.round_number,
                        "qualifying_sessions": wrong_count,
                        "expected": EXPECTED_QUALIFYING_SESSION_COUNT,
                    },
                    identity=(event.id, wrong_count),
                )

        # --- create or update the meeting -----------------------------------
        location = _upsert_location(events_by_id[derived.rounds[0].event_id])
        db.session.flush()

        if meeting is None:
            meeting = Meeting(
                season_id=season.id,
                location_id=location.id if location else None,
                sequence=derived.sequence + _SEQUENCE_OFFSET,
                display_name=derived.display_name,
            )
            db.session.add(meeting)
            db.session.flush()
            report.meetings_created += 1
        else:
            if not meeting.grouping_locked:
                meeting.display_name = derived.display_name
                if location is not None:
                    meeting.location_id = location.id
            report.meetings_updated += 1

        # --- rounds and sessions --------------------------------------------
        for derived_round in derived.rounds:
            event = events_by_id[derived_round.event_id]
            row = db.session.scalar(
                select(Round).where(Round.provider_event_id == event.id)
            )
            if row is None:
                row = Round(
                    provider_event_id=event.id,
                    season_id=season.id,
                    meeting_id=meeting.id,
                    round_number=derived_round.round_number,
                    scoring_ruleset_version=CURRENT_VERSION,
                )
                db.session.add(row)
                report.rounds_created += 1

            row.meeting_id = meeting.id
            row.number_in_meeting = derived_round.number_in_meeting
            if not row.format_locked:
                row.format = derived_round.format
            row.provider_name = event.name
            row.date = event.date_start
            row.status = event.status
            db.session.flush()

            _sync_sessions(row, event, report)

        # --- deadline --------------------------------------------------------
        first = derived.first_round
        first_event = events_by_id[first.event_id]
        proposed_deadline = earliest_qualifying_start([first_event])

        if proposed_deadline is not None:
            stored = meeting.deadline_at
            if stored is not None and proposed_deadline < stored:
                raise _Unsafe(
                    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
                    {
                        "display_name": meeting.display_name,
                        "stored_deadline": stored.isoformat(),
                        "proposed_deadline": proposed_deadline.isoformat(),
                    },
                    identity=(meeting.id, proposed_deadline.isoformat()),
                )
            meeting.deadline_at = proposed_deadline
            deadline_session = db.session.scalar(
                select(Session)
                .where(Session.round_id.in_(select(Round.id).where(
                    Round.provider_event_id == first_event.id)))
                .where(Session.start_time == proposed_deadline)
                .order_by(Session.ordinal)
            )
            meeting.deadline_session_id = deadline_session.id if deadline_session else None

        db.session.commit()

    except UnrecognisedQualifyingSession as exc:
        db.session.rollback()
        record_conflict(
            season_id=season.id,
            kind=CONFLICT_UNRECOGNISED_QUALIFYING_SESSION,
            detail={"display_name": derived.display_name, "error": str(exc)},
            identity=(derived.display_name, str(exc)),
        )
        db.session.commit()
        report.meetings_skipped += 1
        report.conflicts.append(f"{derived.display_name}: {exc}")

    except _Unsafe as unsafe:
        db.session.rollback()
        record_conflict(
            season_id=season.id,
            kind=unsafe.kind,
            detail=unsafe.detail,
            meeting_id=unsafe.detail.get("meeting_id"),
            identity=unsafe.identity,
        )
        db.session.commit()
        report.meetings_skipped += 1
        report.conflicts.append(f"{derived.display_name}: {unsafe.kind}")


class _Unsafe(Exception):
    """Internal signal: this meeting must not be written."""

    def __init__(self, kind: str, detail: dict, identity: tuple):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail
        self.identity = identity


# -----------------------------------------------------------------------------
# Sequence renumbering
# -----------------------------------------------------------------------------


def _renumber_sequences(season: Season, order: list[str]) -> None:
    """Set meeting sequences to calendar order, atomically.

    Done as a separate pass with a temporary offset because `(season_id,
    sequence)` is unique: a new event inserted mid-calendar shifts every later
    meeting, and assigning final numbers one at a time would collide.
    """
    meetings = list(
        db.session.scalars(select(Meeting).where(Meeting.season_id == season.id))
    )
    if not meetings:
        return

    position = {location_id: index for index, location_id in enumerate(order, start=1)}

    by_first_round: list[tuple[int, Meeting]] = []
    for meeting in meetings:
        rounds = sorted(meeting.rounds, key=lambda r: r.round_number)
        key = rounds[0].round_number if rounds else position.get(meeting.id, 9_999)
        by_first_round.append((key, meeting))

    for _, meeting in by_first_round:
        meeting.sequence = meeting.sequence + _SEQUENCE_OFFSET * 2
    db.session.flush()

    for index, (_, meeting) in enumerate(sorted(by_first_round, key=lambda p: p[0]), start=1):
        meeting.sequence = index
    db.session.commit()


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


def sync_season(
    provider,
    ending_year: int,
    adjacency_days: int = DEFAULT_ADJACENCY_DAYS,
) -> SyncReport:
    """Sync one season. `ending_year` is the year the season finishes."""
    report = SyncReport(season_year=ending_year)

    season_ref = provider.resolve_season(ending_year)
    if season_ref is None:
        raise SeasonNotPublished(
            f"No season published for ending year {ending_year}. "
            "Season 13 will not appear until the provider adds it."
        )

    detail = provider.get_season_detail(season_ref.id)
    events = provider.events_for_season(detail)

    if not events:
        report.warnings.append("no events matched the season calendar")
        return report

    if not calendar_is_date_ordered(events):
        # Not reordered: calendar order is what `participationRounds` refers to,
        # so re-sorting here would desynchronise round numbers from the roster.
        report.warnings.append("calendar is not in date order; using provider order")
        log.warning("Season %s calendar is not date-ordered", ending_year)

    # Phase A: season and roster, committed before any meeting work.
    season = _upsert_season(detail)
    db.session.flush()
    _sync_grid(detail, season, report)
    db.session.commit()
    report.season_id = season.id

    # Phase B: one transaction per meeting.
    events_by_id = {e.id: e for e in events}
    derived_meetings = derive_meetings(events, detail.season.year, adjacency_days)
    for derived in derived_meetings:
        _sync_meeting(season, derived, events_by_id, report)

    # Phase C: calendar order, atomically.
    _renumber_sequences(season, [m.location_provider_id for m in derived_meetings])

    log.info("Season sync complete: %s", report.summary())
    return report
