"""Season sync tests.

Driven by a fake provider rather than fixtures. The corpus proves the *parser*
is right; these prove the *rules* are right, and rules need calendars that
Season 12 does not contain — a mid-season regrouping, a deadline moving
backwards, a double-header appearing after the fact.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.ingest.derive import (
    FIRST_UNLEASHED_SEASON_YEAR,
    derive_format,
    derive_meetings,
    earliest_qualifying_start,
    meeting_display_name,
)
from app.ingest.season import SeasonNotPublished, sync_season
from app.ingest.stages import (
    EXPECTED_QUALIFYING_SESSION_COUNT,
    UnrecognisedQualifyingSession,
    bracket_is_complete,
    derive_stage,
    normalise,
)
from app.models.calendar import (
    ROUND_FORMAT_EPRIX,
    ROUND_FORMAT_EPRIX_UNLEASHED,
    SESSION_TYPE_OTHER,
    SESSION_TYPE_PRACTICE,
    SESSION_TYPE_QUALIFYING,
    SESSION_TYPE_RACE,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_OTHER,
    STAGE_PRACTICE,
    STAGE_QUARTER_FINAL,
    STAGE_RACE,
    STAGE_SEMI_FINAL,
    Meeting,
    Round,
    Season,
    Session,
)
from app.models.grid import Driver, SeatEntry, Team
from app.models.result import (
    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
    CONFLICT_ROUND_DISAPPEARED,
    SyncConflict,
)
from app.providers.base import (
    Country,
    DriverStanding,
    EventSummary,
    Location,
    SeasonDetail,
    SeasonRef,
    SessionSummary,
    TeamParticipation,
    TeamStanding,
)

QUAL_NAMES = [
    "Qual Group A", "Qual Group B",
    "Qual Quarter-Final 1", "Qual Quarter-Final 2",
    "Qual Quarter-Final 3", "Qual Quarter-Final 4",
    "Qual Semi-Final 1", "Qual Semi-Final 2",
    "Qual Final",
]


# -----------------------------------------------------------------------------
# Builders
# -----------------------------------------------------------------------------


def make_location(loc_id="loc-london", city="London"):
    return Location(id=loc_id, name=f"Streets of {city}", city=city,
                    country=Country(name="UK", two_code="GB", three_code="GBR"))


def make_sessions(day: date, *, quali_hour=9, include_quali=True, include_other=False,
                  quali_names=None):
    base = datetime(day.year, day.month, day.day, quali_hour, tzinfo=timezone.utc)
    out = [SessionSummary(id=f"s-fp-{day}", name="Free Practice 3",
                          type=SESSION_TYPE_PRACTICE,
                          start_time=base - timedelta(hours=2),
                          end_time=base - timedelta(hours=1), status="completed")]
    if include_other:
        out.append(SessionSummary(id=f"s-sd-{day}", name="Shakedown",
                                  type=SESSION_TYPE_OTHER,
                                  start_time=base - timedelta(hours=4),
                                  end_time=base - timedelta(hours=3), status="completed"))
    if include_quali:
        for i, name in enumerate(quali_names or QUAL_NAMES):
            out.append(SessionSummary(id=f"s-q{i}-{day}", name=name,
                                      type=SESSION_TYPE_QUALIFYING,
                                      start_time=base + timedelta(minutes=10 * i),
                                      end_time=base + timedelta(minutes=10 * i + 8),
                                      status="completed"))
    out.append(SessionSummary(id=f"s-race-{day}", name="Race", type=SESSION_TYPE_RACE,
                              start_time=base + timedelta(hours=5),
                              end_time=base + timedelta(hours=6), status="completed"))
    return tuple(out)


def make_event(event_id, day: date, location=None, *, status="completed", **kwargs):
    return EventSummary(
        id=event_id,
        name=f"2026 Sponsor {(location or make_location()).city} E-Prix",
        date_start=day, date_end=day, status=status,
        location=location or make_location(),
        sessions=make_sessions(day, **kwargs),
    )


def make_detail(events, year=2026):
    team = TeamStanding(id="t1", name="PORSCHE", short_name="POR", color="000000",
                        position=1, points=300)
    driver = DriverStanding(
        id="d1", first_name="Pascal", last_name="Wehrlein", code="WEH", number=94,
        position=1, points=169,
        teams=(TeamParticipation(team_id="t1", name="PORSCHE", short_name="POR",
                                 color="000000",
                                 participation_rounds=tuple(range(1, len(events) + 1))),),
    )
    return SeasonDetail(
        season=SeasonRef(id="season-uuid", year=year),
        drivers=(driver,), teams=(team,), schedule=tuple(events),
    )


class FakeProvider:
    """Implements just enough of ResultsProvider to drive a sync."""

    def __init__(self, events, year=2026, published=True):
        self.events = events
        self.year = year
        self.published = published

    def resolve_season(self, ending_year):
        if not self.published or ending_year != self.year:
            return None
        return SeasonRef(id="season-uuid", year=self.year)

    def get_season_detail(self, season_id):
        return make_detail(self.events, self.year)

    def events_for_season(self, detail, page_size=50):
        return list(self.events)


# -----------------------------------------------------------------------------
# Stage derivation
# -----------------------------------------------------------------------------


def test_normalise_flattens_punctuation_and_case():
    assert normalise("Qual Quarter-Final 1") == "qual quarter final 1"
    assert normalise("QUAL  GROUP   A") == "qual group a"


@pytest.mark.parametrize("name,stage,index", [
    ("Qual Group A", STAGE_GROUP, 1),
    ("Qual Group B", STAGE_GROUP, 2),
    ("Qual Quarter-Final 1", STAGE_QUARTER_FINAL, 1),
    ("Qual Quarter-Final 4", STAGE_QUARTER_FINAL, 4),
    ("Qual Semi-Final 2", STAGE_SEMI_FINAL, 2),
    ("Qual Final", STAGE_FINAL, None),
])
def test_qualifying_stages_derive_from_names(name, stage, index):
    assert derive_stage(name, SESSION_TYPE_QUALIFYING) == (stage, index)


def test_quarter_and_semi_are_matched_before_final():
    """All three names contain "final"; order of checks is what keeps them
    apart."""
    assert derive_stage("Qual Quarter-Final 2", SESSION_TYPE_QUALIFYING)[0] == STAGE_QUARTER_FINAL
    assert derive_stage("Qual Semi-Final 1", SESSION_TYPE_QUALIFYING)[0] == STAGE_SEMI_FINAL
    assert derive_stage("Qual Final", SESSION_TYPE_QUALIFYING)[0] == STAGE_FINAL


def test_matching_tolerates_renaming():
    """Provider names are not a contract, so matching is deliberately loose."""
    for variant in ("QUALIFYING GROUP A", "Qualifying - Group A", "qual group a"):
        assert derive_stage(variant, SESSION_TYPE_QUALIFYING) == (STAGE_GROUP, 1)


def test_an_unrecognised_qualifying_name_raises():
    """Loud on purpose: skipping it would silently lose a driver's points."""
    with pytest.raises(UnrecognisedQualifyingSession):
        derive_stage("Qual Superpole Shootout", SESSION_TYPE_QUALIFYING)


def test_non_qualifying_types_never_raise():
    """Season 13 adds a shakedown day; inventing a failure for it would be
    worse than useless."""
    assert derive_stage("Shakedown", SESSION_TYPE_OTHER) == (STAGE_OTHER, None)
    assert derive_stage("Anything At All", "some-new-type") == (STAGE_OTHER, None)
    assert derive_stage("Free Practice 3", SESSION_TYPE_PRACTICE) == (STAGE_PRACTICE, 3)
    assert derive_stage("Race", SESSION_TYPE_RACE) == (STAGE_RACE, None)


def test_a_complete_bracket_is_nine_sessions():
    stages = [derive_stage(n, SESSION_TYPE_QUALIFYING)[0] for n in QUAL_NAMES]
    assert len(stages) == EXPECTED_QUALIFYING_SESSION_COUNT
    assert bracket_is_complete(stages) is True
    assert bracket_is_complete(stages[:-1]) is False


# -----------------------------------------------------------------------------
# Meeting derivation
# -----------------------------------------------------------------------------


def test_consecutive_days_at_one_location_form_a_double_header():
    london = make_location()
    events = [make_event("e1", date(2026, 7, 25), london),
              make_event("e2", date(2026, 7, 26), london)]
    meetings = derive_meetings(events, 2026)
    assert len(meetings) == 1
    assert meetings[0].is_double_header is True
    assert [r.round_number for r in meetings[0].rounds] == [1, 2]


def test_separate_visits_to_one_circuit_stay_separate():
    """Consecutiveness is what stops Berlin in May and Berlin in July collapsing
    into a single weekend."""
    berlin = make_location("loc-berlin", "Berlin")
    monaco = make_location("loc-monaco", "Monaco")
    events = [make_event("e1", date(2026, 5, 10), berlin),
              make_event("e2", date(2026, 6, 6), monaco),
              make_event("e3", date(2026, 7, 11), berlin)]
    meetings = derive_meetings(events, 2026)
    assert len(meetings) == 3
    assert [m.display_name for m in meetings] == ["Berlin", "Monaco", "Berlin"]


def test_round_numbers_run_across_the_season_not_the_meeting():
    london = make_location()
    monaco = make_location("loc-monaco", "Monaco")
    events = [make_event("e1", date(2026, 5, 10), monaco),
              make_event("e2", date(2026, 7, 25), london),
              make_event("e3", date(2026, 7, 26), london)]
    meetings = derive_meetings(events, 2026)
    assert [r.round_number for m in meetings for r in m.rounds] == [1, 2, 3]
    assert [r.number_in_meeting for r in meetings[1].rounds] == [1, 2]


def test_display_name_ignores_the_sponsor():
    event = make_event("e1", date(2026, 7, 25))
    assert "Sponsor" in event.name
    assert meeting_display_name(event) == "London"


# -----------------------------------------------------------------------------
# Format derivation
# -----------------------------------------------------------------------------


def test_season_12_double_headers_are_both_standard_eprix():
    """Applying the Season 13 rule to the backfill would label half the calendar
    as sprints that never happened, and the simulation would then tune against
    fiction."""
    assert derive_format(2026, 1, 2) == ROUND_FORMAT_EPRIX
    assert derive_format(2026, 2, 2) == ROUND_FORMAT_EPRIX


def test_season_13_double_headers_run_unleashed_first():
    year = FIRST_UNLEASHED_SEASON_YEAR
    assert derive_format(year, 1, 2) == ROUND_FORMAT_EPRIX_UNLEASHED
    assert derive_format(year, 2, 2) == ROUND_FORMAT_EPRIX


def test_single_headers_are_always_standard():
    assert derive_format(FIRST_UNLEASHED_SEASON_YEAR, 1, 1) == ROUND_FORMAT_EPRIX
    assert derive_format(2026, 1, 1) == ROUND_FORMAT_EPRIX


def test_formats_come_through_the_derivation(  ):
    london = make_location()
    events = [make_event("e1", date(2026, 12, 18), london),
              make_event("e2", date(2026, 12, 19), london)]
    meeting = derive_meetings(events, FIRST_UNLEASHED_SEASON_YEAR)[0]
    assert [r.format for r in meeting.rounds] == [
        ROUND_FORMAT_EPRIX_UNLEASHED, ROUND_FORMAT_EPRIX
    ]


# -----------------------------------------------------------------------------
# Deadlines
# -----------------------------------------------------------------------------


def test_deadline_is_the_earliest_qualifying_start():
    event = make_event("e1", date(2026, 7, 25), quali_hour=9)
    deadline = earliest_qualifying_start([event])
    assert deadline == datetime(2026, 7, 25, 9, tzinfo=timezone.utc)
    # Practice starts earlier and must not count.
    assert min(s.start_time for s in event.sessions) < deadline


def test_no_qualifying_sessions_means_no_deadline():
    """A future meeting with an unpublished schedule must stay unlocked rather
    than locking by accident."""
    event = make_event("e1", date(2026, 7, 25), include_quali=False)
    assert earliest_qualifying_start([event]) is None


# -----------------------------------------------------------------------------
# Full sync
# -----------------------------------------------------------------------------


@pytest.fixture()
def calendar():
    london = make_location()
    monaco = make_location("loc-monaco", "Monaco")
    return [
        make_event("e1", date(2026, 5, 10), monaco),
        make_event("e2", date(2026, 7, 25), london),
        make_event("e3", date(2026, 7, 26), london),
    ]


def test_sync_writes_the_calendar(db, calendar):
    report = sync_season(FakeProvider(calendar), 2026)

    assert report.ok
    assert report.meetings_created == 2
    assert report.rounds_created == 3

    meetings = db.session.scalars(select(Meeting).order_by(Meeting.sequence)).all()
    assert [m.display_name for m in meetings] == ["Monaco", "London"]
    assert [m.sequence for m in meetings] == [1, 2]
    assert meetings[1].is_double_header is True


def test_sync_writes_sessions_with_derived_stages(db, calendar):
    sync_season(FakeProvider(calendar), 2026)
    sessions = db.session.scalars(select(Session)).all()
    # 11 per event across 3 events.
    assert len(sessions) == 33
    finals = [s for s in sessions if s.stage == STAGE_FINAL]
    assert len(finals) == 3


def test_sync_sets_the_deadline_and_its_provenance(db, calendar):
    sync_season(FakeProvider(calendar), 2026)
    london = db.session.scalar(select(Meeting).where(Meeting.display_name == "London"))
    assert london.deadline_at == datetime(2026, 7, 25, 9, tzinfo=timezone.utc)
    assert london.deadline_session is not None
    assert london.deadline_session.name == "Qual Group A"


def test_sync_writes_the_roster(db, calendar):
    sync_season(FakeProvider(calendar), 2026)
    assert db.session.scalar(select(Driver)) is not None
    assert db.session.scalar(select(Team)) is not None
    seat = db.session.scalar(select(SeatEntry))
    assert seat.participation_rounds == [1, 2, 3]


def test_sync_is_idempotent(db, calendar):
    first = sync_season(FakeProvider(calendar), 2026)
    second = sync_season(FakeProvider(calendar), 2026)

    assert second.meetings_created == 0
    assert second.rounds_created == 0
    assert second.sessions_created == 0
    assert second.ok

    assert len(db.session.scalars(select(Meeting)).all()) == 2
    assert len(db.session.scalars(select(Round)).all()) == 3
    assert len(db.session.scalars(select(Session)).all()) == 33
    assert first.season_id == second.season_id


def test_an_unpublished_season_raises_a_named_error(db, calendar):
    with pytest.raises(SeasonNotPublished):
        sync_season(FakeProvider(calendar, published=False), 2027)


def test_a_new_event_appearing_is_applied_silently(db):
    """A meeting gaining a round is just a new event, which SPEC.md §6 calls
    safe — flagging it would make every legitimate addition a conflict."""
    london = make_location()
    first_pass = [make_event("e1", date(2026, 7, 25), london)]
    sync_season(FakeProvider(first_pass), 2026)

    second_pass = first_pass + [make_event("e2", date(2026, 7, 26), london)]
    report = sync_season(FakeProvider(second_pass), 2026)

    assert report.ok
    assert report.rounds_created == 1
    meeting = db.session.scalar(select(Meeting))
    assert len(meeting.rounds) == 2


def test_a_deadline_moving_later_is_applied(db, calendar):
    sync_season(FakeProvider(calendar), 2026)

    london = make_location()
    shifted = [
        calendar[0],
        make_event("e2", date(2026, 7, 25), london, quali_hour=11),
        make_event("e3", date(2026, 7, 26), london),
    ]
    report = sync_season(FakeProvider(shifted), 2026)

    assert report.ok
    meeting = db.session.scalar(select(Meeting).where(Meeting.display_name == "London"))
    assert meeting.deadline_at == datetime(2026, 7, 25, 11, tzinfo=timezone.utc)


def test_a_deadline_moving_earlier_is_refused_and_flagged(db, calendar):
    """The monotonic rule. Otherwise a schedule shift retroactively locks people
    out of a meeting they were still editing."""
    sync_season(FakeProvider(calendar), 2026)
    london = db.session.scalar(select(Meeting).where(Meeting.display_name == "London"))
    original = london.deadline_at

    shifted_location = make_location()
    earlier = [
        calendar[0],
        make_event("e2", date(2026, 7, 25), shifted_location, quali_hour=7),
        make_event("e3", date(2026, 7, 26), shifted_location),
    ]
    report = sync_season(FakeProvider(earlier), 2026)

    assert not report.ok
    assert report.meetings_skipped == 1

    db.session.expire_all()
    london = db.session.scalar(select(Meeting).where(Meeting.display_name == "London"))
    assert london.deadline_at == original, "the meeting must be left untouched"

    conflict = db.session.scalar(
        select(SyncConflict).where(
            SyncConflict.kind == CONFLICT_DEADLINE_WOULD_MOVE_EARLIER
        )
    )
    assert conflict is not None
    assert conflict.is_open


def test_one_bad_meeting_does_not_block_the_others(db, calendar):
    """The reason each meeting commits in its own transaction."""
    sync_season(FakeProvider(calendar), 2026)

    london = make_location()
    monaco = make_location("loc-monaco", "Monaco")
    mixed = [
        make_event("e1", date(2026, 5, 10), monaco, quali_hour=14),   # later: fine
        make_event("e2", date(2026, 7, 25), london, quali_hour=7),    # earlier: refused
        make_event("e3", date(2026, 7, 26), london),
    ]
    report = sync_season(FakeProvider(mixed), 2026)

    assert report.meetings_skipped == 1
    db.session.expire_all()
    monaco_row = db.session.scalar(select(Meeting).where(Meeting.display_name == "Monaco"))
    assert monaco_row.deadline_at == datetime(2026, 5, 10, 14, tzinfo=timezone.utc)


def test_a_round_disappearing_is_refused_and_flagged(db, calendar):
    sync_season(FakeProvider(calendar), 2026)

    without_second_london_race = [calendar[0], calendar[1]]
    report = sync_season(FakeProvider(without_second_london_race), 2026)

    assert not report.ok
    conflict = db.session.scalar(
        select(SyncConflict).where(SyncConflict.kind == CONFLICT_ROUND_DISAPPEARED)
    )
    assert conflict is not None
    assert "e3" in conflict.detail["missing_event_ids"]

    meeting = db.session.scalar(select(Meeting).where(Meeting.display_name == "London"))
    assert len(meeting.rounds) == 2, "the meeting must keep both rounds"


def test_a_repeat_conflict_bumps_rather_than_duplicates(db, calendar):
    sync_season(FakeProvider(calendar), 2026)
    reduced = [calendar[0], calendar[1]]
    sync_season(FakeProvider(reduced), 2026)
    sync_season(FakeProvider(reduced), 2026)
    sync_season(FakeProvider(reduced), 2026)

    conflicts = db.session.scalars(
        select(SyncConflict).where(SyncConflict.kind == CONFLICT_ROUND_DISAPPEARED)
    ).all()
    assert len(conflicts) == 1
    assert conflicts[0].occurrences == 3


def test_an_unrecognised_qualifying_session_skips_that_meeting(db):
    london = make_location()
    bad_names = list(QUAL_NAMES)
    bad_names[3] = "Qual Superpole Shootout"
    events = [
        make_event("e1", date(2026, 5, 10), make_location("loc-monaco", "Monaco")),
        make_event("e2", date(2026, 7, 25), london, quali_names=bad_names),
    ]
    report = sync_season(FakeProvider(events), 2026)

    assert not report.ok
    assert report.meetings_skipped == 1
    # Monaco still landed.
    assert db.session.scalar(
        select(Meeting).where(Meeting.display_name == "Monaco")
    ) is not None
    assert db.session.scalar(
        select(Meeting).where(Meeting.display_name == "London")
    ) is None


def test_a_shakedown_session_is_ingested_without_complaint(db):
    """Season 13 adds one, and it must not look like a broken bracket."""
    events = [make_event("e1", date(2026, 12, 18), include_other=True)]
    report = sync_season(FakeProvider(events), 2026)

    assert report.ok
    other = db.session.scalar(select(Session).where(Session.stage == STAGE_OTHER))
    assert other is not None
    assert other.name == "Shakedown"


def test_format_lock_survives_a_resync(db):
    """The admin override exists because the regulations say "typically"."""
    london = make_location()
    events = [make_event("e1", date(2026, 12, 18), london),
              make_event("e2", date(2026, 12, 19), london)]
    sync_season(FakeProvider(events), 2026)

    first_round = db.session.scalar(select(Round).where(Round.round_number == 1))
    first_round.format = ROUND_FORMAT_EPRIX_UNLEASHED
    first_round.format_locked = True
    db.session.commit()

    sync_season(FakeProvider(events), 2026)
    db.session.expire_all()
    first_round = db.session.scalar(select(Round).where(Round.round_number == 1))
    assert first_round.format == ROUND_FORMAT_EPRIX_UNLEASHED


def test_rounds_record_the_ruleset_version(db, calendar):
    from app.scoring.rules import CURRENT_VERSION

    sync_season(FakeProvider(calendar), 2026)
    rounds = db.session.scalars(select(Round)).all()
    assert all(r.scoring_ruleset_version == CURRENT_VERSION for r in rounds)


def test_season_display_name_is_derived(db, calendar):
    sync_season(FakeProvider(calendar), 2026)
    season = db.session.scalar(select(Season))
    assert season.display_name == "Season 12"
    assert season.year == 2026
    assert season.last_synced_at is not None
