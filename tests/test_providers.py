"""Provider client tests.

Every test runs against the committed probe fixtures with `responses`
intercepting the network. Nothing here touches the internet, so the suite works
offline and cannot be broken by the vendor changing their data.

Most of these encode a specific quirk discovered during the August 2026 probe.
When the vendor's shape drifts, the intent is that these fail rather than
production.
"""
from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest
import requests
import responses

from app.providers.base import (
    SESSION_TYPE_OTHER,
    SESSION_TYPE_QUALIFYING,
    ResultsProvider,
)
from app.providers.errors import (
    ProviderAuthError,
    ProviderBlockedError,
    ProviderPayloadError,
    ProviderRequestError,
    ProviderTransientError,
)
from app.providers.ocblacktop import OCBlacktopProvider, parse_result_row

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
BASE = "https://api.ocblacktop.com/v1/formula-e"
UA = "KitsniffFEFantasy/test (+https://fe.kitsniff.com)"


def fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture()
def provider():
    return OCBlacktopProvider(
        api_key="test-key",
        base_url=BASE,
        user_agent=UA,
        min_request_interval=0,
        max_retries=2,
    )


# -----------------------------------------------------------------------------
# Construction and headers
# -----------------------------------------------------------------------------


def test_provider_satisfies_the_protocol(provider):
    assert isinstance(provider, ResultsProvider)


def test_construction_refuses_a_default_python_user_agent():
    """Fail at construction, not on the first 403 buried in a worker log."""
    with pytest.raises(ValueError, match="User-Agent"):
        OCBlacktopProvider(api_key="k", user_agent="Python-urllib/3.11")
    with pytest.raises(ValueError, match="User-Agent"):
        OCBlacktopProvider(api_key="k", user_agent="")


@responses.activate
def test_every_request_carries_the_key_and_user_agent(provider):
    responses.add(responses.GET, f"{BASE}/seasons", json=fixture("seasons_list"), status=200)
    provider.list_seasons()
    sent = responses.calls[0].request
    assert sent.headers["x-api-key"] == "test-key"
    assert sent.headers["User-Agent"] == UA


# -----------------------------------------------------------------------------
# Error classification
# -----------------------------------------------------------------------------


@responses.activate
def test_cloudflare_403_is_a_block_not_an_auth_failure(provider):
    """Error 1010 never reaches the API. Misreading it as bad credentials sends
    you looking for a key problem that does not exist."""
    responses.add(
        responses.GET, f"{BASE}/seasons",
        body="<html><head><title>Access denied</title></head>"
             "<body>error code: 1010</body></html>",
        status=403, content_type="text/html",
    )
    with pytest.raises(ProviderBlockedError, match="CDN"):
        provider.list_seasons()


@responses.activate
def test_api_403_is_an_auth_failure(provider):
    responses.add(responses.GET, f"{BASE}/seasons",
                  json={"message": "Forbidden", "statusCode": 403}, status=403)
    with pytest.raises(ProviderAuthError):
        provider.list_seasons()


@responses.activate
def test_numeric_season_id_raises_a_request_error(provider):
    """`/seasons/2026` returns 400 'uuid is expected'."""
    responses.add(responses.GET, f"{BASE}/seasons/2026",
                  json=fixture("season_numeric_400"), status=400)
    with pytest.raises(ProviderRequestError, match="uuid is expected"):
        provider.get_season_detail("2026")


@responses.activate
def test_server_errors_are_retried_then_raise_transient(provider):
    for _ in range(2):
        responses.add(responses.GET, f"{BASE}/seasons", json={"m": "boom"}, status=503)
    with pytest.raises(ProviderTransientError):
        provider.list_seasons()
    assert len(responses.calls) == 2


@responses.activate
def test_a_retry_that_succeeds_returns_normally(provider):
    payload = fixture("seasons_list")
    responses.add(responses.GET, f"{BASE}/seasons", json={}, status=502)
    responses.add(responses.GET, f"{BASE}/seasons", json=payload, status=200)
    assert len(provider.list_seasons()) == len(payload["data"])


@responses.activate
def test_non_json_success_raises_a_payload_error(provider):
    responses.add(responses.GET, f"{BASE}/seasons", body="not json at all", status=200)
    with pytest.raises(ProviderPayloadError):
        provider.list_seasons()


# -----------------------------------------------------------------------------
# Seasons
# -----------------------------------------------------------------------------


@responses.activate
def test_seasons_are_keyed_on_the_ending_year(provider):
    """Season 12 ran Dec 2025 to Aug 2026 and is keyed 2026. Reading it as the
    starting year silently returns the wrong season."""
    responses.add(responses.GET, f"{BASE}/seasons", json=fixture("seasons_list"), status=200)
    season = provider.resolve_season(2026)
    assert season is not None
    assert season.id == "3552d83c-1896-4909-a8c8-31b07917f151"


@responses.activate
def test_an_unpublished_season_resolves_to_none(provider):
    """Season 13 is not in the index yet. That is a normal answer, not an error
    — the sync must tolerate it and try again later."""
    responses.add(responses.GET, f"{BASE}/seasons", json=fixture("seasons_list"), status=200)
    assert provider.resolve_season(2027) is None


# -----------------------------------------------------------------------------
# Season detail
# -----------------------------------------------------------------------------


@responses.activate
def test_season_detail_parses_the_bare_object_envelope(provider):
    responses.add(responses.GET, f"{BASE}/seasons/abc",
                  json=fixture("season_detail"), status=200)
    detail = provider.get_season_detail("abc")
    assert detail.season.year == 2026
    assert len(detail.drivers) >= 1
    assert len(detail.schedule) >= 1


@responses.activate
def test_participation_rounds_are_nested_per_team(provider):
    """Not a flat count at driver level — an array of round numbers inside each
    entry of driver.teams, so a mid-season switch is represented correctly."""
    responses.add(responses.GET, f"{BASE}/seasons/abc",
                  json=fixture("season_detail"), status=200)
    detail = provider.get_season_detail("abc")

    leader = detail.drivers[0]
    assert leader.teams, "a standings driver should carry at least one team"
    rounds = leader.teams[0].participation_rounds
    assert rounds and all(isinstance(r, int) for r in rounds)
    assert rounds == tuple(sorted(rounds))
    assert leader.rounds_participated == sum(
        len(t.participation_rounds) for t in leader.teams
    )


def test_a_mid_season_team_switch_totals_across_both_teams():
    """Built inline rather than hunted for in the corpus: Season 12 happens to
    have no switchers, but the parser must handle one when it comes."""
    from app.providers.ocblacktop import parse_driver_standing

    driver = parse_driver_standing({
        "id": "d1", "firstName": "A", "lastName": "B", "code": None, "number": 7,
        "position": 3, "points": 120,
        "teams": [
            {"id": "t-b", "name": "TEAM B", "shortName": "TB", "color": "000000",
             "participationRounds": list(range(5, 18))},
            {"id": "t-a", "name": "TEAM A", "shortName": "TA", "color": "000000",
             "participationRounds": [1, 2, 3, 4]},
        ],
    })

    assert driver.rounds_participated == 17
    # Current team is whichever holds the most recent round, not list order.
    assert driver.current_team.team_id == "t-b"


def test_a_driver_who_has_not_raced_yet_has_no_rounds():
    """Empty at the start of a season, which is exactly why this field is
    display data for the picker and never roster truth (SPEC.md §6)."""
    from app.providers.ocblacktop import parse_driver_standing

    driver = parse_driver_standing({
        "id": "d2", "firstName": "R", "lastName": "Eserve", "number": 55,
        "teams": [{"id": "t-a", "name": "TEAM A", "participationRounds": []}],
    })
    assert driver.rounds_participated == 0
    assert driver.current_team is not None


def test_a_one_off_reserve_reads_as_a_single_appearance():
    from app.providers.ocblacktop import parse_driver_standing

    driver = parse_driver_standing({
        "id": "d3", "firstName": "R", "lastName": "Eserve", "number": 55,
        "teams": [{"id": "t-a", "name": "TEAM A", "participationRounds": [9]}],
    })
    assert driver.rounds_participated == 1


@responses.activate
def test_season_detail_schedule_has_no_session_times(provider):
    """Which is why session times need the events endpoint as a second call."""
    responses.add(responses.GET, f"{BASE}/seasons/abc",
                  json=fixture("season_detail"), status=200)
    detail = provider.get_season_detail("abc")
    assert all(event.sessions == () for event in detail.schedule)


def test_season_detail_without_a_season_object_is_a_payload_error():
    from app.providers.ocblacktop import parse_season_detail

    with pytest.raises(ProviderPayloadError):
        parse_season_detail({"drivers": [], "teams": []})


# -----------------------------------------------------------------------------
# Events and pagination
# -----------------------------------------------------------------------------


@responses.activate
def test_events_parse_the_data_meta_envelope_and_paginate(provider):
    page1 = fixture("events_bare")
    page2 = fixture("events_page2")
    total = len(page1["data"]) + len(page2["data"])
    page1["meta"] = {"page": 1, "limit": 20, "total": total, "totalPages": 2}
    page2["meta"] = {"page": 2, "limit": 20, "total": total, "totalPages": 2}
    responses.add(responses.GET, f"{BASE}/events", json=page1, status=200)
    responses.add(responses.GET, f"{BASE}/events", json=page2, status=200)

    expected = len(page1["data"]) + len(page2["data"])
    events = list(provider.iter_events(page_size=20))
    assert len(events) == expected
    assert len(responses.calls) == 2


@responses.activate
def test_pagination_stops_at_the_last_page_rather_than_looping(provider):
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)
    assert len(list(provider.iter_events(page_size=20))) == len(payload["data"])
    assert len(responses.calls) == 1


@responses.activate
def test_events_carry_sessions_with_start_and_end_times(provider):
    """Sessions use startTime/endTime while the parent event uses
    dateStart/dateEnd. Reading the event's names at session level yields a null
    deadline."""
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)

    event = next(e for e in provider.iter_events(page_size=20) if e.sessions)
    session = event.sessions[0]
    assert session.start_time is not None
    assert session.start_time.tzinfo is not None
    assert session.end_time is not None


@responses.activate
def test_event_dates_are_a_single_day(provider):
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)
    for event in provider.iter_events(page_size=20):
        assert event.date_start == event.date_end


@responses.activate
def test_the_qualifying_bracket_is_nine_sessions(provider):
    """All nine share type 'qualifying', so the bracket must come from names.
    Duel sessions return only two participants, hence all nine are needed."""
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)

    brackets = [
        e.qualifying_sessions
        for e in provider.iter_events(page_size=20)
        if e.qualifying_sessions
    ]
    assert brackets, "the events fixture should contain at least one bracket"
    full = [b for b in brackets if len(b) == 9]
    assert full, f"expected a nine-session bracket, saw {sorted({len(b) for b in brackets})}"

    quali = full[0]
    assert all(s.type == SESSION_TYPE_QUALIFYING for s in quali)
    names = [s.name.lower() for s in quali]
    assert sum("group" in n for n in names) == 2
    assert sum("quarter" in n for n in names) == 4
    assert sum("semi" in n for n in names) == 2
    assert names[-1].endswith("final")


def test_session_type_other_is_tolerated():
    """Appendix A claims three session types. Live payloads carry four, and
    Season 13's shakedown day will most likely arrive as 'other'. An unknown
    type must parse, not raise — only unrecognised *qualifying* names fail
    loudly, because a silent skip there would corrupt scoring."""
    from app.providers.ocblacktop import parse_session

    session = parse_session({
        "id": "s-shakedown", "name": "Shakedown", "type": SESSION_TYPE_OTHER,
        "startTime": "2026-12-18T05:00:00.000Z",
        "endTime": "2026-12-18T06:00:00.000Z", "status": "completed",
    })
    assert session.type == SESSION_TYPE_OTHER
    assert session.is_qualifying is False
    assert session.is_race is False
    assert session.is_complete is True


def test_an_entirely_unknown_session_type_still_parses():
    from app.providers.ocblacktop import parse_session

    session = parse_session({"id": "x", "name": "Something New", "type": "unheard-of"})
    assert session.type == "unheard-of"
    assert session.start_time is None


@responses.activate
def test_every_session_type_in_the_corpus_parses(provider):
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)

    types = {s.type for e in provider.iter_events(page_size=20) for s in e.sessions}
    assert types, "the events fixture should carry sessions"
    assert all(isinstance(t, str) and t for t in types)


@responses.activate
def test_earliest_qualifying_start_is_the_deadline_basis(provider):
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)

    event = next(
        e for e in provider.iter_events(page_size=20)
        if any(s.start_time for s in e.qualifying_sessions)
    )
    earliest = event.earliest_qualifying_start()
    assert earliest is not None
    assert earliest == min(s.start_time for s in event.qualifying_sessions)


@responses.activate
def test_events_for_season_joins_the_two_endpoints(provider):
    """Season detail has the calendar but no sessions; the events collection has
    sessions but no season filter, so it cannot be narrowed server-side. This is
    the join, and it is why season sync is inherently two calls."""
    detail_payload = fixture("season_detail")
    borrowed = next(
        e["schedule"] for e in fixture("events_bare")["data"] if e.get("schedule")
    )
    # The same events as the calendar, now carrying sessions, plus noise from
    # another season that must be filtered out.
    collection = [dict(e, schedule=borrowed) for e in detail_payload["schedule"]]
    collection.append(
        {"id": "other-season-1", "name": "2019 Somewhere E-Prix",
         "dateStart": "2019-05-01", "dateEnd": "2019-05-01", "status": "completed",
         "location": {"id": "loc-x", "name": "X", "city": "X", "country": None},
         "schedule": borrowed}
    )
    responses.add(responses.GET, f"{BASE}/seasons/abc", json=detail_payload, status=200)
    responses.add(
        responses.GET, f"{BASE}/events",
        json={"data": collection,
              "meta": {"page": 1, "limit": 50, "total": len(collection), "totalPages": 1}},
        status=200,
    )

    detail = provider.get_season_detail("abc")
    events = provider.events_for_season(detail)

    assert len(events) == len(detail.schedule)
    assert all(e.id in detail.event_ids for e in events)
    assert all(e.sessions for e in events)
    # Calendar order is preserved.
    assert [e.id for e in events] == [e.id for e in detail.schedule]


@responses.activate
def test_events_missing_from_the_collection_are_reported_not_dropped(provider, caplog):
    detail_payload = fixture("season_detail")
    responses.add(responses.GET, f"{BASE}/seasons/abc", json=detail_payload, status=200)
    responses.add(
        responses.GET, f"{BASE}/events",
        json={"data": [], "meta": {"page": 1, "limit": 50, "total": 0, "totalPages": 1}},
        status=200,
    )

    detail = provider.get_season_detail("abc")
    with caplog.at_level("WARNING"):
        events = provider.events_for_season(detail)

    assert events == []
    assert "absent from the events collection" in caplog.text


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------


@responses.activate
def test_race_results_parse_the_bare_array_envelope(provider):
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_race"), status=200)
    rows = provider.get_results("e1", "s1")
    assert len(rows) == 20


@responses.activate
def test_position_string_and_grid_int_are_both_coerced(provider):
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_race"), status=200)
    rows = provider.get_results("e1", "s1")
    assert all(isinstance(r.position, int) for r in rows)
    assert all(isinstance(r.grid_position, int) for r in rows)
    assert [r.position for r in rows] == sorted(r.position for r in rows)


def test_qualifying_rows_omit_points_and_status_entirely():
    """Absent keys, not null ones. Subscripting raises KeyError on nine of the
    eleven sessions in a round."""
    raw = json.loads((FIXTURES / "results_qual_final.json").read_text())
    assert "points" not in raw[0]
    assert "status" not in raw[0]
    assert "gridPosition" in raw[0] and raw[0]["gridPosition"] is None

    row = parse_result_row(raw[0])
    assert row.points is None
    assert row.status is None
    assert row.grid_position is None


@responses.activate
def test_a_duel_session_returns_only_two_rows(provider):
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/qf/results",
                  json=fixture("results_qual_final"), status=200)
    assert len(provider.get_results("e1", "qf")) == 2


@responses.activate
def test_fastest_lap_comes_from_rank_not_points(provider):
    """The fantasy point is unconditional; Formula E's own is top-ten only. So
    the flag must come from fastestLap.rank, never from the points field."""
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_race"), status=200)
    rows = provider.get_results("e1", "s1")
    setters = [r for r in rows if r.set_fastest_lap]
    assert len(setters) == 1
    assert setters[0].fastest_lap_rank == 1


@responses.activate
def test_retirements_keep_ranked_positions(provider):
    """Which is what makes places lost punish a DNF automatically, with no
    separate DNF rule (SPEC.md §3)."""
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_saopaulo"), status=200)
    rows = provider.get_results("e1", "s1")
    dnfs = [r for r in rows if r.is_retirement]
    assert dnfs
    assert all(r.position is not None for r in dnfs)
    # They occupy the tail of the classification.
    assert min(r.position for r in dnfs) > max(
        r.position for r in rows if not r.is_retirement
    )


@responses.activate
def test_points_parse_as_decimal(provider):
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_race"), status=200)
    rows = provider.get_results("e1", "s1")
    assert rows[0].points == Decimal("25.0")
    assert all(r.points is None or isinstance(r.points, Decimal) for r in rows)


@responses.activate
def test_null_driver_codes_do_not_break_parsing(provider):
    """Sixteen of twenty drivers have no code, so it can never be a key or a
    primary label."""
    responses.add(responses.GET, f"{BASE}/events/e1/sessions/s1/results",
                  json=fixture("results_race"), status=200)
    rows = provider.get_results("e1", "s1")
    assert any(r.driver.code is None for r in rows)
    assert all(r.driver.id for r in rows)


def test_display_time_shape_varies_between_races():
    """"1:01:13.217" over an hour, "59:23.013" under. Never split on ':'
    expecting three parts — the 30-minute Unleashed race is always sub-hour."""
    race = json.loads((FIXTURES / "results_race.json").read_text())
    sp = json.loads((FIXTURES / "results_saopaulo.json").read_text())
    assert race[0]["displayTime"].count(":") == 2
    assert sp[0]["displayTime"].count(":") == 1


def test_lap_time_and_display_time_swap_meaning_by_session_type():
    """In a race, lapTime is a lap and displayTime the total. In a duel, lapTime
    is null and displayTime carries the lap."""
    race = parse_result_row(json.loads((FIXTURES / "results_race.json").read_text())[0])
    duel = parse_result_row(json.loads((FIXTURES / "results_qual_final.json").read_text())[0])
    assert race.lap_time is not None and race.display_time is not None
    assert duel.lap_time is None and duel.display_time is not None


def test_missing_grid_position_is_reported_not_guessed():
    """A pit-lane start or data gap scores places gained/lost as 0. Never
    invent a grid slot."""
    row = parse_result_row({"id": "x", "position": "5", "gridPosition": None})
    assert row.grid_position is None
    assert row.has_grid_position is False

    zeroed = parse_result_row({"id": "x", "position": "5", "gridPosition": 0})
    assert zeroed.has_grid_position is False


def test_unreadable_values_degrade_to_none_rather_than_raising():
    row = parse_result_row(
        {"id": "x", "position": "NC", "gridPosition": "??", "points": "n/a"}
    )
    assert row.position is None
    assert row.grid_position is None
    assert row.points is None


# -----------------------------------------------------------------------------
# The quirk that most easily produces a silently broken ingest
# -----------------------------------------------------------------------------


def test_unknown_query_parameters_are_ignored_by_the_api():
    """`?season=`, `?seasonId=` and `?perPage=` return byte-identical unfiltered
    responses with HTTP 200. A 200 is never proof a filter applied, so the
    client does not offer a season parameter at all."""
    base = (FIXTURES / "events_bare.json").read_bytes()
    for name in ("events_param_season", "events_param_seasonid", "events_param_perpage"):
        assert (FIXTURES / f"{name}.json").read_bytes() == base, name


@responses.activate
def test_the_client_only_ever_sends_limit_and_page(provider):
    payload = fixture("events_bare")
    payload["meta"] = {"page": 1, "limit": 20, "total": len(payload["data"]),
                       "totalPages": 1}
    responses.add(responses.GET, f"{BASE}/events", json=payload, status=200)

    list(provider.iter_events(page_size=20))
    sent = requests.utils.urlparse(responses.calls[0].request.url).query
    assert set(k for k, _ in (p.split("=") for p in sent.split("&"))) == {"limit", "page"}
