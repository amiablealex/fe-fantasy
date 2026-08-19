"""Ingestion model tests.

These run against Postgres, which matters more here than for the auth models:
`participation_rounds` is a Postgres array, `detail` is JSONB, and the sync
conflict dedupe relies on a partial unique index. None of that exists on SQLite,
so a suite that passed on another engine would be telling you very little.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.calendar import (
    ROUND_FORMAT_EPRIX,
    ROUND_FORMAT_EPRIX_UNLEASHED,
    SESSION_TYPE_OTHER,
    SESSION_TYPE_QUALIFYING,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_OTHER,
    STAGE_QUARTER_FINAL,
    STAGE_RACE,
    Location,
    Meeting,
    Round,
    Season,
    Session,
    default_season_display_name,
    season_number_for_year,
)
from app.models.grid import Driver, SeatEntry, Team
from app.models.result import (
    CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
    Result,
    SyncConflict,
)
from app.scoring.rules import CURRENT_VERSION


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


@pytest.fixture()
def season(db):
    s = Season(
        provider_season_id="3552d83c-1896-4909-a8c8-31b07917f151",
        year=2026,
        display_name=default_season_display_name(2026),
    )
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture()
def location(db):
    loc = Location(
        provider_location_id="097c4b3c",
        name="Streets of London",
        city="London",
        country_name="United Kingdom",
        country_two_code="GB",
        country_three_code="GBR",
    )
    db.session.add(loc)
    db.session.commit()
    return loc


@pytest.fixture()
def meeting(db, season, location):
    m = Meeting(
        season_id=season.id, location_id=location.id, sequence=1, display_name="London"
    )
    db.session.add(m)
    db.session.commit()
    return m


def _round(db, season, meeting, number, *, in_meeting=1, fmt=ROUND_FORMAT_EPRIX):
    r = Round(
        season_id=season.id,
        meeting_id=meeting.id,
        provider_event_id=f"event-{number}",
        round_number=number,
        number_in_meeting=in_meeting,
        format=fmt,
        provider_name=f"2026 Sponsor London E-Prix {number}",
        date=date(2026, 7, 25),
        status="completed",
        scoring_ruleset_version=CURRENT_VERSION,
    )
    db.session.add(r)
    db.session.commit()
    return r


# -----------------------------------------------------------------------------
# Season
# -----------------------------------------------------------------------------


def test_season_number_derives_from_the_ending_year():
    """The API has no season number. Season 12 ended in 2026."""
    assert season_number_for_year(2026) == 12
    assert season_number_for_year(2027) == 13
    assert default_season_display_name(2027) == "Season 13"


def test_season_year_is_unique(db, season):
    db.session.add(Season(provider_season_id="other", year=2026, display_name="Dup"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_display_name_is_editable_not_computed(db, season):
    """Stored rather than derived on read, so an admin can correct it if the
    epoch arithmetic ever stops holding."""
    season.display_name = "Season Twelve"
    db.session.commit()
    assert db.session.get(Season, season.id).display_name == "Season Twelve"


# -----------------------------------------------------------------------------
# Meeting
# -----------------------------------------------------------------------------


def test_meeting_sequence_is_unique_within_a_season(db, season, location, meeting):
    db.session.add(
        Meeting(season_id=season.id, location_id=location.id, sequence=1,
                display_name="Duplicate")
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_a_meeting_without_a_deadline_is_not_locked(db, meeting):
    """An unsynced meeting must stay editable rather than locking by default."""
    assert meeting.deadline_at is None
    assert meeting.is_locked() is False


def test_meeting_locks_once_the_deadline_passes(db, meeting):
    meeting.deadline_at = _utc(2026, 7, 25, 9, 0)
    db.session.commit()
    assert meeting.is_locked(now=_utc(2026, 7, 25, 8, 59)) is False
    assert meeting.is_locked(now=_utc(2026, 7, 25, 9, 0)) is True


def test_double_header_detection(db, season, meeting):
    _round(db, season, meeting, 16, in_meeting=1, fmt=ROUND_FORMAT_EPRIX_UNLEASHED)
    db.session.refresh(meeting)
    assert meeting.is_double_header is False
    _round(db, season, meeting, 17, in_meeting=2, fmt=ROUND_FORMAT_EPRIX)
    db.session.refresh(meeting)
    assert meeting.is_double_header is True


def test_deadline_session_records_provenance(db, season, meeting):
    """So the UI can say "locks at Qual Group A, 09:00" rather than showing a
    bare timestamp nobody can sanity-check."""
    rnd = _round(db, season, meeting, 16)
    sess = Session(
        round_id=rnd.id, provider_session_id="s-group-a", name="Qual Group A",
        type=SESSION_TYPE_QUALIFYING, stage=STAGE_GROUP, stage_index=1, ordinal=1,
        start_time=_utc(2026, 7, 25, 9, 0),
    )
    db.session.add(sess)
    db.session.commit()

    meeting.deadline_at = sess.start_time
    meeting.deadline_session_id = sess.id
    db.session.commit()
    db.session.refresh(meeting)

    assert meeting.deadline_session.name == "Qual Group A"
    assert meeting.deadline_at == sess.start_time


def test_deleting_a_deadline_session_nulls_the_reference(db, season, meeting):
    """SET NULL, not cascade: losing a session must not delete the meeting."""
    rnd = _round(db, season, meeting, 16)
    sess = Session(
        round_id=rnd.id, provider_session_id="s-x", name="Qual Group A",
        type=SESSION_TYPE_QUALIFYING, stage=STAGE_GROUP, stage_index=1, ordinal=1,
    )
    db.session.add(sess)
    db.session.commit()
    meeting.deadline_session_id = sess.id
    db.session.commit()

    db.session.delete(sess)
    db.session.commit()
    db.session.refresh(meeting)

    assert db.session.get(Meeting, meeting.id) is not None
    assert meeting.deadline_session_id is None


# -----------------------------------------------------------------------------
# Round
# -----------------------------------------------------------------------------


def test_round_number_is_unique_within_a_season(db, season, meeting):
    _round(db, season, meeting, 16)
    dup = Round(
        season_id=season.id, meeting_id=meeting.id, provider_event_id="event-other",
        round_number=16, scoring_ruleset_version=CURRENT_VERSION,
    )
    db.session.add(dup)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_provider_event_id_is_globally_unique(db, season, meeting):
    _round(db, season, meeting, 16)
    dup = Round(
        season_id=season.id, meeting_id=meeting.id, provider_event_id="event-16",
        round_number=99, scoring_ruleset_version=CURRENT_VERSION,
    )
    db.session.add(dup)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_round_records_the_ruleset_in_force(db, season, meeting):
    """Changing point values must never rewrite a completed round."""
    rnd = _round(db, season, meeting, 16)
    assert rnd.scoring_ruleset_version == CURRENT_VERSION


def test_round_format_labels(db, season, meeting):
    unleashed = _round(db, season, meeting, 16, fmt=ROUND_FORMAT_EPRIX_UNLEASHED)
    standard = _round(db, season, meeting, 17, fmt=ROUND_FORMAT_EPRIX)
    assert unleashed.format_label == "E-Prix Unleashed"
    assert standard.format_label == "E-Prix"


def test_deleting_a_season_cascades_to_rounds_and_meetings(db, season, meeting):
    _round(db, season, meeting, 16)
    db.session.delete(season)
    db.session.commit()
    assert db.session.scalar(select(Round)) is None
    assert db.session.scalar(select(Meeting)) is None


# -----------------------------------------------------------------------------
# Session
# -----------------------------------------------------------------------------


def test_stage_and_index_are_stored_separately(db, season, meeting):
    """Splitting "Qual Quarter-Final 3" into stage plus index means a future
    change to the bracket shape needs no schema change."""
    rnd = _round(db, season, meeting, 16)
    qf3 = Session(
        round_id=rnd.id, provider_session_id="s-qf3", name="Qual Quarter-Final 3",
        type=SESSION_TYPE_QUALIFYING, stage=STAGE_QUARTER_FINAL, stage_index=3,
        ordinal=5,
    )
    db.session.add(qf3)
    db.session.commit()
    assert qf3.stage == STAGE_QUARTER_FINAL
    assert qf3.stage_index == 3
    assert qf3.is_scoring_qualifying is True


def test_race_and_other_stages_do_not_score_as_qualifying(db, season, meeting):
    rnd = _round(db, season, meeting, 16)
    race = Session(round_id=rnd.id, provider_session_id="s-race", name="Race",
                   stage=STAGE_RACE, type="race", ordinal=10)
    shakedown = Session(round_id=rnd.id, provider_session_id="s-sd", name="Shakedown",
                        stage=STAGE_OTHER, type=SESSION_TYPE_OTHER, ordinal=0)
    db.session.add_all([race, shakedown])
    db.session.commit()

    assert race.is_race is True
    assert race.is_scoring_qualifying is False
    assert shakedown.is_scoring_qualifying is False


def test_sessions_keep_provider_order(db, season, meeting):
    rnd = _round(db, season, meeting, 16)
    db.session.add_all([
        Session(round_id=rnd.id, provider_session_id="s-race", name="Race",
                stage=STAGE_RACE, type="race", ordinal=10),
        Session(round_id=rnd.id, provider_session_id="s-ga", name="Qual Group A",
                stage=STAGE_GROUP, stage_index=1, type=SESSION_TYPE_QUALIFYING, ordinal=1),
        Session(round_id=rnd.id, provider_session_id="s-fin", name="Qual Final",
                stage=STAGE_FINAL, type=SESSION_TYPE_QUALIFYING, ordinal=9),
    ])
    db.session.commit()
    db.session.refresh(rnd)
    assert [s.ordinal for s in rnd.sessions] == [1, 9, 10]


# -----------------------------------------------------------------------------
# Grid and seat entries
# -----------------------------------------------------------------------------


def test_driver_label_falls_back_when_code_is_null(db):
    """Sixteen of twenty drivers have no code, so it can never be the label."""
    coded = Driver(provider_driver_id="d1", first_name="Pascal", last_name="Wehrlein",
                   code="WEH", number=94)
    uncoded = Driver(provider_driver_id="d2", first_name="Nick", last_name="Cassidy",
                     code=None, number=37)
    numberless = Driver(provider_driver_id="d3", number=55)
    db.session.add_all([coded, uncoded, numberless])
    db.session.commit()

    assert uncoded.display_name == "Nick Cassidy"
    assert uncoded.short_label == "Cassidy"
    assert numberless.short_label == "#55"


def test_participation_rounds_round_trips_as_an_array(db, season):
    driver = Driver(provider_driver_id="d1", last_name="Wehrlein")
    team = Team(provider_team_id="t1", name="PORSCHE FORMULA E TEAM")
    db.session.add_all([driver, team])
    db.session.commit()

    seat = SeatEntry(season_id=season.id, driver_id=driver.id, team_id=team.id,
                     participation_rounds=list(range(1, 18)))
    db.session.add(seat)
    db.session.commit()

    stored = db.session.get(SeatEntry, seat.id)
    assert stored.participation_rounds == list(range(1, 18))
    assert stored.rounds_participated == 17


def test_a_mid_season_switch_is_two_seats_with_disjoint_rounds(db, season):
    """Which is what lets the one-driver-per-team constraint know which team a
    driver was on at a given meeting."""
    driver = Driver(provider_driver_id="d1", last_name="Cassidy")
    team_a = Team(provider_team_id="ta", name="TEAM A")
    team_b = Team(provider_team_id="tb", name="TEAM B")
    db.session.add_all([driver, team_a, team_b])
    db.session.commit()

    db.session.add_all([
        SeatEntry(season_id=season.id, driver_id=driver.id, team_id=team_a.id,
                  participation_rounds=[1, 2, 3, 4]),
        SeatEntry(season_id=season.id, driver_id=driver.id, team_id=team_b.id,
                  participation_rounds=list(range(5, 18))),
    ])
    db.session.commit()

    seats = db.session.scalars(
        select(SeatEntry).where(SeatEntry.driver_id == driver.id)
    ).all()
    assert len(seats) == 2

    at_round_3 = [s for s in seats if s.covers_round(3)]
    at_round_9 = [s for s in seats if s.covers_round(9)]
    assert len(at_round_3) == 1 and at_round_3[0].team_id == team_a.id
    assert len(at_round_9) == 1 and at_round_9[0].team_id == team_b.id


def test_a_driver_who_has_not_raced_has_an_empty_array(db, season):
    """Empty, not null — which is why this is display data and never a
    statement about who is on the grid."""
    driver = Driver(provider_driver_id="d1", last_name="Reserve")
    team = Team(provider_team_id="t1", name="TEAM")
    db.session.add_all([driver, team])
    db.session.commit()

    seat = SeatEntry(season_id=season.id, driver_id=driver.id, team_id=team.id,
                     participation_rounds=[])
    db.session.add(seat)
    db.session.commit()
    assert seat.rounds_participated == 0
    assert seat.covers_round(1) is False


def test_seat_entry_is_unique_per_season_driver_team(db, season):
    driver = Driver(provider_driver_id="d1")
    team = Team(provider_team_id="t1")
    db.session.add_all([driver, team])
    db.session.commit()
    db.session.add(SeatEntry(season_id=season.id, driver_id=driver.id,
                             team_id=team.id, participation_rounds=[1]))
    db.session.commit()

    db.session.add(SeatEntry(season_id=season.id, driver_id=driver.id,
                             team_id=team.id, participation_rounds=[2]))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------


@pytest.fixture()
def race_session(db, season, meeting):
    rnd = _round(db, season, meeting, 16)
    sess = Session(round_id=rnd.id, provider_session_id="s-race", name="Race",
                   stage=STAGE_RACE, type="race", ordinal=10)
    db.session.add(sess)
    db.session.commit()
    return sess


def _driver_and_team(db, suffix="1"):
    driver = Driver(provider_driver_id=f"d{suffix}", last_name=f"Driver{suffix}")
    team = Team(provider_team_id=f"t{suffix}", name=f"TEAM {suffix}")
    db.session.add_all([driver, team])
    db.session.commit()
    return driver, team


def test_result_flags(db, season, race_session):
    driver, team = _driver_and_team(db)
    result = Result(
        season_id=season.id, session_id=race_session.id, provider_result_id="r1",
        driver_id=driver.id, team_id=team.id, position=3, grid_position=8,
        status=None, points=16, fastest_lap_rank=1, car_number=1,
        lap_time="1:15.300", display_time="1:01:13.217",
    )
    db.session.add(result)
    db.session.commit()

    assert result.set_fastest_lap is True
    assert result.is_retirement is False
    assert result.has_grid_position is True


def test_a_pit_lane_start_reports_no_grid_position(db, season, race_session):
    """Places gained/lost scores 0 there rather than guessing a slot."""
    driver, team = _driver_and_team(db)
    result = Result(season_id=season.id, session_id=race_session.id,
                    provider_result_id="r1", driver_id=driver.id, team_id=team.id,
                    position=15, grid_position=0)
    db.session.add(result)
    db.session.commit()
    assert result.has_grid_position is False


def test_a_retirement_keeps_its_position(db, season, race_session):
    driver, team = _driver_and_team(db)
    result = Result(season_id=season.id, session_id=race_session.id,
                    provider_result_id="r1", driver_id=driver.id, team_id=team.id,
                    position=18, grid_position=1, status="DNF")
    db.session.add(result)
    db.session.commit()
    assert result.is_retirement is True
    assert result.position == 18


def test_one_result_per_driver_per_session(db, season, race_session):
    driver, team = _driver_and_team(db)
    db.session.add(Result(season_id=season.id, session_id=race_session.id,
                          provider_result_id="r1", driver_id=driver.id,
                          team_id=team.id, position=1))
    db.session.commit()

    db.session.add(Result(season_id=season.id, session_id=race_session.id,
                          provider_result_id="r2", driver_id=driver.id,
                          team_id=team.id, position=2))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_qualifying_results_tolerate_absent_points_and_status(db, season, meeting):
    """Those keys are absent from qualifying payloads, so the columns must be
    nullable and the ingest must not require them."""
    rnd = _round(db, season, meeting, 16)
    sess = Session(round_id=rnd.id, provider_session_id="s-final",
                   name="Qual Final", stage=STAGE_FINAL,
                   type=SESSION_TYPE_QUALIFYING, ordinal=9)
    db.session.add(sess)
    db.session.commit()
    driver, team = _driver_and_team(db)

    result = Result(season_id=season.id, session_id=sess.id, provider_result_id="q1",
                    driver_id=driver.id, team_id=team.id, position=1,
                    grid_position=None, status=None, points=None,
                    lap_time=None, display_time="1:12.341")
    db.session.add(result)
    db.session.commit()
    assert result.points is None
    assert result.display_time == "1:12.341"


def test_results_survive_a_driver_with_no_seat_entry(db, season, race_session):
    """A reserve can appear in results before the next standings sync creates
    their seat. Keying results on the seat would fail here."""
    driver, team = _driver_and_team(db, "reserve")
    assert db.session.scalar(
        select(SeatEntry).where(SeatEntry.driver_id == driver.id)
    ) is None

    db.session.add(Result(season_id=season.id, session_id=race_session.id,
                          provider_result_id="r-res", driver_id=driver.id,
                          team_id=team.id, position=19))
    db.session.commit()
    assert db.session.scalar(select(Result)) is not None


def test_deleting_a_session_cascades_to_its_results(db, season, race_session):
    driver, team = _driver_and_team(db)
    db.session.add(Result(season_id=season.id, session_id=race_session.id,
                          provider_result_id="r1", driver_id=driver.id,
                          team_id=team.id, position=1))
    db.session.commit()

    db.session.delete(race_session)
    db.session.commit()
    assert db.session.scalar(select(Result)) is None


# -----------------------------------------------------------------------------
# Sync conflicts
# -----------------------------------------------------------------------------


def _conflict(season, meeting, fingerprint="abc123"):
    return SyncConflict(
        season_id=season.id,
        meeting_id=meeting.id,
        kind=CONFLICT_DEADLINE_WOULD_MOVE_EARLIER,
        fingerprint=fingerprint,
        detail={"stored": "2026-07-25T09:00:00Z", "proposed": "2026-07-25T08:00:00Z"},
    )


def test_an_open_conflict_cannot_be_duplicated(db, season, meeting):
    """The partial unique index. A twice-daily sync must bump the existing row
    rather than insert a new one every twelve hours."""
    db.session.add(_conflict(season, meeting))
    db.session.commit()

    db.session.add(_conflict(season, meeting))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_the_same_conflict_may_recur_after_resolution(db, season, meeting):
    """Which is the point of making the index partial rather than plain."""
    first = _conflict(season, meeting)
    db.session.add(first)
    db.session.commit()

    first.resolved_at = datetime.now(timezone.utc)
    db.session.commit()

    db.session.add(_conflict(season, meeting))
    db.session.commit()

    rows = db.session.scalars(select(SyncConflict)).all()
    assert len(rows) == 2
    assert len([r for r in rows if r.is_open]) == 1


def test_recurrence_is_counted_on_the_existing_row(db, season, meeting):
    conflict = _conflict(season, meeting)
    db.session.add(conflict)
    db.session.commit()

    conflict.occurrences += 1
    conflict.last_seen_at = conflict.first_seen_at + timedelta(hours=12)
    db.session.commit()

    stored = db.session.get(SyncConflict, conflict.id)
    assert stored.occurrences == 2
    assert stored.last_seen_at > stored.first_seen_at


def test_conflict_detail_stores_arbitrary_evidence(db, season, meeting):
    """JSONB on purpose: every conflict kind carries different evidence, and
    the admin page renders it as key-value pairs rather than parsing it."""
    conflict = _conflict(season, meeting)
    conflict.detail = {"rounds": [16, 17], "nested": {"was": 3, "now": 2}}
    db.session.add(conflict)
    db.session.commit()

    stored = db.session.get(SyncConflict, conflict.id)
    assert stored.detail["nested"]["now"] == 2
    assert stored.detail["rounds"] == [16, 17]


def test_conflict_has_a_human_label(db, season, meeting):
    conflict = _conflict(season, meeting)
    assert conflict.label == "Deadline would move earlier"


def test_deleting_a_meeting_keeps_the_conflict(db, season, meeting):
    """The conflict is often the record of *why* a meeting looks wrong, so it
    must outlive the meeting rather than cascade away with it."""
    db.session.add(_conflict(season, meeting))
    db.session.commit()

    db.session.delete(meeting)
    db.session.commit()

    stored = db.session.scalar(select(SyncConflict))
    assert stored is not None
    assert stored.meeting_id is None
