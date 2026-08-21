"""The scoring pass, against a real bracket.

Builds a full round — two groups, four quarter-finals, two semi-finals, a final
and a race — over the conftest grid, then scores it. The bracket is
deterministic and the expected totals are worked out by hand in
`test_known_totals`, so a change in the engine shows up as a specific wrong
number rather than a vague failure.

`INGESTED_AT` sits deliberately in the past. The pass stamps `Round.scored_at`
from the real clock and the dirty check compares the two, so a fixture that
stamped results in the future would leave every round permanently dirty and
quietly disable the test that matters most here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.extensions import db as _db
from app.meetings.scoring import (
    completeness,
    needs_scoring,
    score_round,
    score_season,
)
from app.models.calendar import (
    SESSION_STATUS_COMPLETED,
    SESSION_TYPE_QUALIFYING,
    SESSION_TYPE_RACE,
    STAGE_FINAL,
    STAGE_GROUP,
    STAGE_QUARTER_FINAL,
    STAGE_RACE,
    STAGE_SEMI_FINAL,
    Session,
)
from app.models.lineup import LineupSnapshot
from app.models.result import Result
from app.models.score import SUBJECT_DRIVER, SUBJECT_TEAM, PickScore, RoundScore

INGESTED_AT = datetime(2026, 1, 17, 18, 0, tzinfo=timezone.utc)
QUALIFYING_STAGES = {STAGE_GROUP, STAGE_QUARTER_FINAL, STAGE_SEMI_FINAL, STAGE_FINAL}


# -----------------------------------------------------------------------------
# Building a round
# -----------------------------------------------------------------------------
#
# Group A is drivers 0-9 in index order, Group B is 10-19. The bracket then
# runs so that driver 0 wins everything and driver 1 loses only the final,
# which gives two drivers with different, hand-checkable qualifying totals.


def _bracket(drivers):
    return [
        (STAGE_GROUP, 1, [drivers[i] for i in range(10)]),
        (STAGE_GROUP, 2, [drivers[i] for i in range(10, 20)]),
        (STAGE_QUARTER_FINAL, 1, [drivers[0], drivers[13]]),
        (STAGE_QUARTER_FINAL, 2, [drivers[1], drivers[12]]),
        (STAGE_QUARTER_FINAL, 3, [drivers[2], drivers[11]]),
        (STAGE_QUARTER_FINAL, 4, [drivers[3], drivers[10]]),
        (STAGE_SEMI_FINAL, 1, [drivers[0], drivers[3]]),
        (STAGE_SEMI_FINAL, 2, [drivers[1], drivers[2]]),
        (STAGE_FINAL, None, [drivers[0], drivers[1]]),
    ]


def _lap_time(index: int) -> str:
    """Driver 19 sets the quickest lap from last on the road.

    Deliberately the back marker: the fantasy fastest-lap point is
    unconditional (SPEC.md §3), and a bracket where the winner also set the
    quickest lap would not notice if that restriction crept back in.
    """
    return "1:09.000" if index == 19 else f"1:{10 + index}.000"


@pytest.fixture()
def ingest(db, season, grid):
    """Write a round's sessions, and results for the stages asked for.

    Incremental on purpose. Sessions are created on the first call and reused
    afterwards, so a test can land the groups, score, then land the rest and
    score again — which is the live weekend this pass is built for rather than
    a contrived case.
    """
    drivers = grid.drivers

    def _plan():
        plan = [
            (stage, index, SESSION_TYPE_QUALIFYING, [
                {"driver": d, "position": p, "grid_position": None, "lap_time": None}
                for p, d in enumerate(entrants, start=1)
            ])
            for stage, index, entrants in _bracket(drivers)
        ]
        plan.append((STAGE_RACE, None, SESSION_TYPE_RACE, [
            {"driver": d, "position": i + 1, "grid_position": i + 1,
             "lap_time": _lap_time(i)}
            for i, d in enumerate(drivers)
        ]))
        return plan

    def _ingest(round_obj, *, stages=None, ingested_at=None):
        ingested_at = ingested_at or INGESTED_AT

        for ordinal, (stage, index, type_, rows) in enumerate(_plan(), start=1):
            key = f"sess-{round_obj.id}-{ordinal}"
            session = db.session.scalar(
                select(Session).where(Session.provider_session_id == key)
            )
            if session is None:
                session = Session(
                    round_id=round_obj.id,
                    provider_session_id=key,
                    name=f"{stage} {index or ''}".strip(),
                    type=type_,
                    stage=stage,
                    stage_index=index,
                    ordinal=ordinal,
                    status=SESSION_STATUS_COMPLETED,
                )
                db.session.add(session)
                db.session.flush()

            if stages is not None and stage not in stages:
                continue
            if session.results_ingested_at is not None:
                continue

            for row in rows:
                db.session.add(Result(
                    season_id=season.id,
                    session_id=session.id,
                    provider_result_id=f"res-{session.id}-{row['driver'].id}",
                    driver_id=row["driver"].id,
                    position=row["position"],
                    grid_position=row["grid_position"],
                    lap_time=row["lap_time"],
                ))
            session.results_ingested_at = ingested_at

        db.session.commit()

    return _ingest


@pytest.fixture()
def scored_round(db, season, grid, make_meeting, ingest):
    meeting = make_meeting(1, deadline_at=INGESTED_AT - timedelta(days=1))
    round_obj = meeting.rounds[0]
    ingest(round_obj)
    return round_obj


def _scores(round_obj):
    return {
        (s.kind, s.driver_id if s.kind == SUBJECT_DRIVER else s.team_id): s
        for s in _db.session.scalars(
            select(RoundScore).where(RoundScore.round_id == round_obj.id)
        )
    }


def _picks(user):
    return list(_db.session.scalars(
        select(PickScore).where(PickScore.user_id == user.id)
    ))


def _commit_lineup(db, user, season, meeting, lineup):
    snapshot = LineupSnapshot.build(
        user_id=user.id,
        season_id=season.id,
        meeting_id=meeting.id,
        lineup=lineup,
    )
    db.session.add(snapshot)
    db.session.commit()
    return snapshot


# -----------------------------------------------------------------------------
# What gets written
# -----------------------------------------------------------------------------


def test_every_driver_and_team_on_the_grid_gets_a_row(scored_round):
    score_round(scored_round)
    rows = _scores(scored_round)
    assert len(rows) == 30
    assert sum(1 for kind, _ in rows if kind == SUBJECT_DRIVER) == 20
    assert sum(1 for kind, _ in rows if kind == SUBJECT_TEAM) == 10


def test_known_totals(scored_round, grid):
    """Worked by hand from SPEC.md §3.

    Driver 0 tops Group A (2), wins a quarter-final, a semi-final and the final
    (1 each) and takes pole (3) for 8; then wins the race (5), takes the podium
    (5) and the points finish (2) from P1 on the grid for 12. Total 20.

    Driver 1 is second in Group A (2), wins a quarter-final and a semi-final
    (1 each) and loses the final, for 4; then P2 gives podium (5) and points
    (2) for 7. Total 11.
    """
    score_round(scored_round)
    rows = _scores(scored_round)

    assert rows[(SUBJECT_DRIVER, grid.driver_at(0, 0).id)].points == Decimal(20)
    assert rows[(SUBJECT_DRIVER, grid.driver_at(0, 1).id)].points == Decimal(11)
    # Driver 10 tops Group B and reaches the Duels, then finishes P11 — so the
    # 2 is the group progression and nothing else. Worth asserting alongside
    # the zero below, because these two are the pair that distinguishes "scored
    # nothing" from "was not scored".
    assert rows[(SUBJECT_DRIVER, grid.driver_at(5, 0).id)].points == Decimal(2)
    # Driver 14 is fifth in Group B, so out at the group stage; P15 on the road
    # from P15 on the grid, so no points finish and no places change; and the
    # lap record belongs to driver 19. A real, earned zero.
    assert rows[(SUBJECT_DRIVER, grid.driver_at(7, 0).id)].points == Decimal(0)


def test_fastest_lap_is_unconditional(scored_round, grid):
    """Driver 19 finishes last and still takes the point."""
    score_round(scored_round)
    backmarker = _scores(scored_round)[(SUBJECT_DRIVER, grid.driver_at(9, 1).id)]
    assert [c.rule for c in backmarker.components()] == ["fastest_lap"]
    assert backmarker.points == Decimal(1)


def test_the_breakdown_keeps_its_contest_split(scored_round, grid):
    score_round(scored_round)
    winner = _scores(scored_round)[(SUBJECT_DRIVER, grid.driver_at(0, 0).id)]
    assert sum(c.points for c in winner.qualifying_components) == Decimal(8)
    assert sum(c.points for c in winner.race_components) == Decimal(12)


def test_team_is_half_the_sum_and_stores_its_cars(scored_round, grid):
    """Drivers on 20 and 11 give the team 15.5. Halves are real and are never
    rounded, so this is the row that proves the Numeric column."""
    score_round(scored_round)
    team = _scores(scored_round)[(SUBJECT_TEAM, grid.teams[0].id)]

    assert team.points == Decimal("15.5")
    assert team.breakdown == []
    assert dict(team.cars) == {
        grid.driver_at(0, 0).id: Decimal(20),
        grid.driver_at(0, 1).id: Decimal(11),
    }


def test_the_ruleset_recorded_on_the_round_is_the_one_stored(scored_round):
    score_round(scored_round)
    versions = {s.ruleset_version for s in _scores(scored_round).values()}
    assert versions == {scored_round.scoring_ruleset_version}


# -----------------------------------------------------------------------------
# Idempotence
# -----------------------------------------------------------------------------


def _fingerprint(round_obj):
    return sorted(
        (s.kind, s.driver_id, s.team_id, str(s.points), str(s.breakdown), str(s.detail))
        for s in _scores(round_obj).values()
    )


def test_rescoring_reproduces_the_same_rows(scored_round):
    score_round(scored_round)
    first = _fingerprint(scored_round)
    score_round(scored_round)
    assert _fingerprint(scored_round) == first


def test_rescoring_replaces_rather_than_accumulates(scored_round):
    score_round(scored_round)
    score_round(scored_round)
    score_round(scored_round)
    assert len(_scores(scored_round)) == 30


def test_a_round_is_not_rescored_until_its_results_move(scored_round, season):
    score_round(scored_round)
    assert not needs_scoring(scored_round)
    assert score_season(season).rounds_scored == 0

    # After the pass ran, not merely after the fixture's stamp.
    scored_round.sessions[0].results_ingested_at = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    )
    _db.session.commit()

    assert needs_scoring(scored_round)
    assert score_season(season).rounds_scored == 1


def test_a_round_with_no_results_is_not_scoreable(db, season, make_meeting):
    round_obj = make_meeting(1).rounds[0]
    assert not needs_scoring(round_obj)
    assert not score_round(round_obj).scored
    assert round_obj.scored_at is None


# -----------------------------------------------------------------------------
# Partial rounds
# -----------------------------------------------------------------------------


def test_a_round_scores_from_what_has_landed_and_only_grows(
    db, season, grid, make_meeting, ingest
):
    """Qualifying finishes hours before the race, and every fantasy rule is
    additive per session, so a provisional score is a partial sum that only
    increases. The whole partial-scoring decision rests on that, so it is
    asserted rather than assumed."""
    round_obj = make_meeting(1).rounds[0]

    ingest(round_obj, stages={STAGE_GROUP})
    score_round(round_obj)
    assert round_obj.scoring_provisional
    after_groups = _scores(round_obj)[(SUBJECT_DRIVER, grid.driver_at(0, 0).id)].points
    assert after_groups == Decimal(2)

    ingest(round_obj)
    score_round(round_obj)
    assert not round_obj.scoring_provisional
    complete = _scores(round_obj)[(SUBJECT_DRIVER, grid.driver_at(0, 0).id)].points
    assert complete == Decimal(20)
    assert complete > after_groups


def test_a_round_without_its_race_stays_provisional(
    db, season, grid, make_meeting, ingest
):
    round_obj = make_meeting(1).rounds[0]
    ingest(round_obj, stages=QUALIFYING_STAGES)

    outcome = score_round(round_obj)
    assert outcome.scored
    assert outcome.provisional
    # Pole still lands: it is the Qual Final winner, not whoever starts P1.
    winner = _scores(round_obj)[(SUBJECT_DRIVER, grid.driver_at(0, 0).id)]
    assert winner.points == Decimal(8)


def test_provisional_matches_a_recomputation(scored_round):
    """`scoring_provisional` is a cache of something derivable, so it carries
    the same guard `transfer_cost` does."""
    score_round(scored_round)
    assert scored_round.scoring_provisional == completeness(scored_round).provisional


# -----------------------------------------------------------------------------
# Pick scores
# -----------------------------------------------------------------------------


def test_five_pick_scores_per_round_matching_their_round_scores(
    db, season, grid, make_user, make_meeting, ingest
):
    user = make_user()
    meeting = make_meeting(1)
    round_obj = meeting.rounds[0]
    _commit_lineup(db, user, season, meeting, grid.lineup())
    ingest(round_obj)

    score_round(round_obj)
    picks = _picks(user)
    assert len(picks) == 5

    rows = _scores(round_obj)
    for pick in picks:
        source = rows[(pick.kind, pick.driver_id or pick.team_id)]
        assert pick.points == source.points
        assert pick.round_score_id == source.id


def test_a_sparse_snapshot_still_scores_later_meetings(
    db, season, grid, make_user, make_meeting, ingest
):
    """A player who last picked at meeting 1 still has a lineup at meeting 2,
    and it is meeting 1's. This is what makes the game degrade gracefully over
    an eight-month season."""
    user = make_user()
    first = make_meeting(1)
    later = make_meeting(2)
    snapshot = _commit_lineup(db, user, season, first, grid.lineup())

    ingest(later.rounds[0])
    score_round(later.rounds[0])

    picks = _picks(user)
    assert len(picks) == 5
    assert {p.snapshot_id for p in picks} == {snapshot.id}
    assert {p.meeting_id for p in picks} == {later.id}


def test_a_player_who_has_never_picked_scores_nothing(
    db, season, grid, make_user, make_meeting, ingest
):
    user = make_user()
    round_obj = make_meeting(1).rounds[0]
    ingest(round_obj)
    score_round(round_obj)
    assert _picks(user) == []


def test_a_double_header_scores_the_same_lineup_twice(
    db, season, grid, make_user, make_meeting, ingest
):
    """The meeting is the transfer unit and the round is the scoring unit, and
    this is where those two facts meet."""
    user = make_user()
    meeting = make_meeting(1, rounds=2)
    _commit_lineup(db, user, season, meeting, grid.lineup())
    for round_obj in meeting.rounds:
        ingest(round_obj)
        score_round(round_obj)

    picks = _picks(user)
    assert len(picks) == 10
    assert len({p.round_id for p in picks}) == 2
    assert len({p.snapshot_id for p in picks}) == 1


def test_rescoring_does_not_duplicate_pick_scores(
    db, season, grid, make_user, make_meeting, ingest
):
    user = make_user()
    meeting = make_meeting(1)
    round_obj = meeting.rounds[0]
    _commit_lineup(db, user, season, meeting, grid.lineup())
    ingest(round_obj)

    score_round(round_obj)
    score_round(round_obj)
    assert len(_picks(user)) == 5


def test_two_players_sharing_a_pick_share_one_round_score(
    db, season, grid, make_user, make_meeting, ingest
):
    """The reason the breakdown lives on `RoundScore` rather than on each
    player's row: it is the same sentence about the same driver."""
    one = make_user(email="a@example.com", username="one")
    two = make_user(email="b@example.com", username="two")
    meeting = make_meeting(1)
    round_obj = meeting.rounds[0]
    _commit_lineup(db, one, season, meeting, grid.lineup())
    _commit_lineup(db, two, season, meeting, grid.lineup(driver_teams=(0, 5, 6, 7)))
    ingest(round_obj)

    score_round(round_obj)
    shared = grid.driver_at(0, 0).id
    rows = {
        p.user_id: p
        for p in _db.session.scalars(
            select(PickScore).where(PickScore.driver_id == shared)
        )
    }
    assert len(rows) == 2
    assert rows[one.id].round_score_id == rows[two.id].round_score_id


def test_a_driver_absent_from_the_classification_scores_a_real_zero(
    db, season, grid, make_user, make_meeting, ingest
):
    """No substitution, no compensation (SPEC.md §2) — but a stored zero with
    an empty breakdown, not a missing row. "Picked and scored nothing" and "no
    pick at all" have to be able to read differently."""
    user = make_user()
    meeting = make_meeting(1)
    round_obj = meeting.rounds[0]
    _commit_lineup(db, user, season, meeting, grid.lineup())
    ingest(round_obj)

    absent = grid.driver_at(0, 0).id
    _db.session.execute(delete(Result).where(Result.driver_id == absent))
    _db.session.commit()

    score_round(round_obj)
    row = _scores(round_obj)[(SUBJECT_DRIVER, absent)]
    assert row.points == Decimal(0)
    assert row.components() == ()
    assert next(p for p in _picks(user) if p.driver_id == absent).points == Decimal(0)


# -----------------------------------------------------------------------------
# The season pass
# -----------------------------------------------------------------------------


def test_score_season_walks_every_round_that_has_results(
    db, season, grid, make_meeting, ingest
):
    for meeting in (make_meeting(1, rounds=2), make_meeting(2)):
        for round_obj in meeting.rounds:
            ingest(round_obj)

    report = score_season(season)
    assert report.rounds_considered == 3
    assert report.rounds_scored == 3
    assert report.rounds_provisional == 0
    assert report.round_scores == 90
    assert report.ok


def test_force_rescores_an_unchanged_season(db, season, grid, make_meeting, ingest):
    ingest(make_meeting(1).rounds[0])
    score_season(season)

    assert score_season(season).rounds_scored == 0
    assert score_season(season, force=True).rounds_scored == 1
