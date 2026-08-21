"""Orange Cat Blacktop API client.

Handles four things the raw API makes awkward:

1. **User-Agent.** The default Python UA is refused by Cloudflare with Error
   1010 before the request reaches the API. A 403 is therefore ambiguous, so it
   is classified: a CDN refusal raises ProviderBlockedError, an API credential
   failure raises ProviderAuthError. Confusing the two costs an afternoon.

2. **Three envelope styles.** `/events` returns {data, meta}; `/seasons/{uuid}`
   returns a bare object; `/results` returns a bare array. Normalised here so
   nothing downstream branches on shape.

3. **Silently ignored parameters.** `?season=`, `?seasonId=` and `?perPage=`
   return byte-identical unfiltered responses with HTTP 200. A 200 is never
   proof a filter applied. Only `limit` and `page` actually work, so the events
   collection cannot be narrowed server-side and season filtering happens
   client-side against the season's event IDs.

4. **Type inconsistency.** `position` is a string, `gridPosition` an int, and
   `points` and `status` are absent rather than null on qualifying rows. All
   coerced into the dataclasses in base.py.

Nothing in this module imports Flask. Construction takes plain values so the
client is usable from a script, a worker, or a test.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

import requests

from app.providers.base import (
    Country,
    DriverRef,
    DriverStanding,
    EventSummary,
    Location,
    ResultRow,
    SeasonDetail,
    SeasonRef,
    SessionSummary,
    TeamParticipation,
    TeamRef,
    TeamStanding,
)
from app.providers.errors import (
    ProviderAuthError,
    ProviderBlockedError,
    ProviderPayloadError,
    ProviderRequestError,
    ProviderTransientError,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.ocblacktop.com/v1/formula-e"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RATE_LIMITED = 429
# A rate limit needs a longer wait than a transient 5xx: retrying in one second
# just spends another call against the same window.
_RATE_LIMIT_BACKOFF_SECONDS = 15.0


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Honour Retry-After when the server sends it."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# Coercion helpers
# -----------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    """Coerce to int, tolerating the string/int inconsistency across fields."""
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        log.warning("Could not read %r as an integer", value)
        return None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        log.warning("Could not read %r as a decimal", value)
        return None


def _as_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, normalising to aware UTC.

    Session times arrive as '2026-07-26T06:40:00.000Z'.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        log.warning("Could not read %r as a timestamp", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_date(value: Any) -> date | None:
    """Parse a plain date. Events carry '2025-12-06' with no time component."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        log.warning("Could not read %r as a date", value)
        return None


def _rounds(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    out = [_as_int(v) for v in value]
    return tuple(sorted(v for v in out if v is not None))


# -----------------------------------------------------------------------------
# Parsers
# -----------------------------------------------------------------------------


def parse_country(payload: dict | None) -> Country | None:
    if not payload:
        return None
    return Country(
        name=payload.get("name"),
        two_code=payload.get("twoCode"),
        three_code=payload.get("threeCode"),
    )


def parse_location(payload: dict | None) -> Location | None:
    if not payload or not payload.get("id"):
        return None
    return Location(
        id=payload["id"],
        name=payload.get("name"),
        city=payload.get("city"),
        country=parse_country(payload.get("country")),
    )


def parse_session(payload: dict) -> SessionSummary:
    """Note startTime/endTime here against dateStart/dateEnd on the parent event.

    The two levels use opposite naming conventions. Reading the event's names at
    session level yields None, and a null deadline is the symptom.
    """
    return SessionSummary(
        id=payload["id"],
        name=payload.get("name") or "",
        type=payload.get("type") or "",
        start_time=_as_datetime(payload.get("startTime")),
        end_time=_as_datetime(payload.get("endTime")),
        status=payload.get("status"),
    )


def parse_event(payload: dict) -> EventSummary:
    sessions = tuple(
        parse_session(s) for s in (payload.get("schedule") or []) if s.get("id")
    )
    return EventSummary(
        id=payload["id"],
        # Sponsor-polluted: "2026 Hankook London E-Prix". Never parse or group
        # on this; group on location.id and date adjacency (SPEC.md §5).
        name=payload.get("name") or "",
        date_start=_as_date(payload.get("dateStart")),
        date_end=_as_date(payload.get("dateEnd")),
        status=payload.get("status"),
        location=parse_location(payload.get("location")),
        sessions=sessions,
    )


def parse_season_ref(payload: dict) -> SeasonRef:
    return SeasonRef(
        id=payload["id"],
        year=_as_int(payload.get("year")) or 0,
        status=payload.get("status"),
        round_count=_as_int(payload.get("roundCount")),
    )


def parse_team_participation(payload: dict) -> TeamParticipation:
    return TeamParticipation(
        team_id=payload["id"],
        name=payload.get("name"),
        short_name=payload.get("shortName"),
        # Unreliable as a palette: Andretti and Jaguar are both "000000".
        color=payload.get("color"),
        participation_rounds=_rounds(payload.get("participationRounds")),
    )


def parse_driver_standing(payload: dict) -> DriverStanding:
    return DriverStanding(
        id=payload["id"],
        first_name=payload.get("firstName"),
        last_name=payload.get("lastName"),
        code=payload.get("code"),
        number=_as_int(payload.get("number")),
        position=_as_int(payload.get("position")),
        points=_as_decimal(payload.get("points")),
        teams=tuple(
            parse_team_participation(t) for t in (payload.get("teams") or []) if t.get("id")
        ),
    )


def parse_team_standing(payload: dict) -> TeamStanding:
    return TeamStanding(
        id=payload["id"],
        name=payload.get("name"),
        short_name=payload.get("shortName"),
        color=payload.get("color"),
        position=_as_int(payload.get("position")),
        points=_as_decimal(payload.get("points")),
    )


def parse_season_detail(payload: dict) -> SeasonDetail:
    season = payload.get("season")
    if not season or not season.get("id"):
        raise ProviderPayloadError("Season detail payload has no season object.")
    return SeasonDetail(
        season=parse_season_ref(season),
        drivers=tuple(
            parse_driver_standing(d) for d in (payload.get("drivers") or []) if d.get("id")
        ),
        teams=tuple(
            parse_team_standing(t) for t in (payload.get("teams") or []) if t.get("id")
        ),
        schedule=tuple(parse_event(e) for e in (payload.get("schedule") or []) if e.get("id")),
    )


def parse_driver_ref(payload: dict | None) -> DriverRef | None:
    if not payload or not payload.get("id"):
        return None
    return DriverRef(
        id=payload["id"],
        first_name=payload.get("firstName"),
        last_name=payload.get("lastName"),
        # Null for 16 of 20 drivers. Key on id; code is decoration.
        code=payload.get("code"),
        number=_as_int(payload.get("number")),
    )


def parse_team_ref(payload: dict | None) -> TeamRef | None:
    if not payload or not payload.get("id"):
        return None
    return TeamRef(
        id=payload["id"],
        name=payload.get("name"),
        short_name=payload.get("shortName"),
        color=payload.get("color"),
    )


def parse_result_row(payload: dict) -> ResultRow:
    """Every field read with .get().

    Qualifying rows omit `points` and `status` entirely rather than nulling
    them, so subscripting raises KeyError on nine sessions out of eleven.
    """
    fastest = payload.get("fastestLap") or {}
    return ResultRow(
        id=payload.get("id") or "",
        position=_as_int(payload.get("position")),
        grid_position=_as_int(payload.get("gridPosition")),
        driver=parse_driver_ref(payload.get("driver")),
        team=parse_team_ref(payload.get("team")),
        status=payload.get("status"),
        points=_as_decimal(payload.get("points")),
        fastest_lap_rank=_as_int(fastest.get("rank")),
        car_number=_as_int(payload.get("carNumber")),
        lap_time=payload.get("lapTime"),
        display_time=payload.get("displayTime"),
    )


# -----------------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------------


class OCBlacktopProvider:
    """Implements the ResultsProvider protocol against Orange Cat Blacktop."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str,
        timeout: int = 15,
        min_request_interval: float = 1.0,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        if not user_agent or user_agent.lower().startswith("python-"):
            # Fail at construction rather than on the first 403 in a worker log.
            raise ValueError(
                "A descriptive User-Agent is required; the default Python UA is "
                "refused by Cloudflare with Error 1010."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self.max_retries = max_retries
        # HTTP attempts made by this instance, retries included — a retry spends
        # quota exactly like a first attempt, so counting successes would
        # understate usage in precisely the situation that matters. The worker
        # records this per run; the month's sum is what the ceiling checks.
        self.calls = 0
        self._last_request_at = 0.0
        self._session = session or requests.Session()
        self._session.headers.update({"x-api-key": api_key, "User-Agent": user_agent})

    @classmethod
    def from_config(cls, config, session: requests.Session | None = None) -> "OCBlacktopProvider":
        """Build from a Flask config mapping without importing Flask."""
        return cls(
            api_key=config["OCB_API_KEY"],
            base_url=config.get("OCB_BASE_URL", DEFAULT_BASE_URL),
            user_agent=config["OCB_USER_AGENT"],
            timeout=config.get("OCB_REQUEST_TIMEOUT_SECONDS", 15),
            min_request_interval=config.get("OCB_MIN_REQUEST_INTERVAL_SECONDS", 1.0),
            session=session,
        )

    # ----- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        if self.min_request_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

    def _classify_403(self, response: requests.Response) -> Exception:
        """Distinguish a CDN refusal from an API credential failure.

        Cloudflare returns an HTML interstitial naming error 1010; the API
        returns JSON. Treating a CDN block as bad credentials sends you looking
        for a key problem that does not exist.
        """
        body = (response.text or "")[:1000].lower()
        if "1010" in body or "cloudflare" in body or "<html" in body:
            return ProviderBlockedError(
                "Blocked before reaching the API (HTTP 403). This is a CDN "
                "refusal, usually the User-Agent, not a credentials problem."
            )
        return ProviderAuthError("The API rejected the credentials (HTTP 403).")

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            wait: float | None = None
            self._throttle()
            self.calls += 1
            try:
                response = self._session.get(url, params=params, timeout=self.timeout)
            except requests.Timeout as exc:
                last_error = ProviderTransientError(f"Timed out calling {path}: {exc}")
            except requests.RequestException as exc:
                last_error = ProviderTransientError(f"Network error calling {path}: {exc}")
            else:
                self._last_request_at = time.monotonic()

                if response.status_code == 403:
                    raise self._classify_403(response)
                if response.status_code == 401:
                    raise ProviderAuthError("The API rejected the credentials (HTTP 401).")
                if response.status_code == 400:
                    raise ProviderRequestError(
                        f"Bad request to {path}: {self._error_message(response)}"
                    )
                if response.status_code == 404:
                    raise ProviderRequestError(f"Not found: {path}")
                if response.status_code in _RETRY_STATUSES:
                    last_error = ProviderTransientError(
                        f"HTTP {response.status_code} from {path}"
                    )
                    wait = _retry_after_seconds(response)
                    if wait is None and response.status_code == _RATE_LIMITED:
                        wait = _RATE_LIMIT_BACKOFF_SECONDS * attempt
                elif not response.ok:
                    raise ProviderRequestError(f"HTTP {response.status_code} from {path}")
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise ProviderPayloadError(
                            f"Response from {path} was not JSON: {exc}"
                        ) from exc

            if attempt < self.max_retries:
                if wait is None:
                    wait = float(2 ** (attempt - 1))
                log.warning(
                    "Retrying %s in %ss (attempt %s/%s): %s",
                    path, wait, attempt, self.max_retries, last_error,
                )
                time.sleep(wait)

        raise last_error or ProviderTransientError(f"Failed to call {path}")

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return (response.text or "")[:200]
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or payload)
        return str(payload)[:200]

    # ----- envelopes ---------------------------------------------------------

    @staticmethod
    def _rows(payload: Any, path: str) -> list[dict]:
        """Normalise the three envelope styles down to a list of rows."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return data
        raise ProviderPayloadError(f"Unexpected envelope from {path}: {type(payload).__name__}")

    @staticmethod
    def _meta(payload: Any) -> dict:
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
            return payload["meta"]
        return {}

    # ----- API ---------------------------------------------------------------

    def list_seasons(self) -> list[SeasonRef]:
        payload = self._get("/seasons")
        return [parse_season_ref(r) for r in self._rows(payload, "/seasons") if r.get("id")]

    def resolve_season(self, ending_year: int) -> SeasonRef | None:
        """Find a season by the year it ends in.

        Season 12 ran Dec 2025 to Aug 2026 and is keyed 2026. Season 13 runs
        Dec 2026 to Jul 2027 and will be keyed 2027 — and does not exist in the
        index yet, so None is a normal answer, not a failure.
        """
        for season in self.list_seasons():
            if season.year == ending_year:
                return season
        log.info("No season published for ending year %s", ending_year)
        return None

    def get_season_detail(self, season_id: str) -> SeasonDetail:
        """Calendar plus driver and team standings in one call.

        Requires the UUID: a numeric year returns HTTP 400 "uuid is expected",
        which surfaces as ProviderRequestError.
        """
        payload = self._get(f"/seasons/{season_id}")
        if not isinstance(payload, dict):
            raise ProviderPayloadError("Season detail was not an object.")
        return parse_season_detail(payload)

    def iter_events(self, page_size: int = 50) -> Iterator[EventSummary]:
        """Walk every event across every season.

        There is no server-side season filter — `?season=` is accepted and
        ignored — so callers narrow client-side against SeasonDetail.event_ids.
        At 165 events and page_size 50 this is 4 calls.
        """
        page = 1
        seen = 0
        while True:
            payload = self._get("/events", {"limit": page_size, "page": page})
            rows = self._rows(payload, "/events")
            meta = self._meta(payload)

            if not rows:
                return
            for row in rows:
                if row.get("id"):
                    yield parse_event(row)
            seen += len(rows)

            total_pages = _as_int(meta.get("totalPages"))
            total = _as_int(meta.get("total"))
            if total_pages is not None and page >= total_pages:
                return
            if total_pages is None and (total is None or seen >= total):
                return
            page += 1

    def events_for_season(
        self, detail: SeasonDetail, page_size: int = 50
    ) -> list[EventSummary]:
        """The season's events, with session times attached.

        Season detail carries the calendar but no sessions; the events endpoint
        carries sessions but cannot be filtered. This is the join, and it is why
        season sync is inherently a two-step operation.
        """
        wanted = detail.event_ids
        found = {e.id: e for e in self.iter_events(page_size=page_size) if e.id in wanted}

        missing = wanted - set(found)
        if missing:
            log.warning(
                "%s of %s season events absent from the events collection: %s",
                len(missing), len(wanted), sorted(missing),
            )
        return [found[e.id] for e in detail.schedule if e.id in found]

    def get_results(self, event_id: str, session_id: str) -> list[ResultRow]:
        """Classification for one session.

        Duel sessions return only their two participants, so a full qualifying
        bracket needs all nine qualifying sessions fetched.
        """
        path = f"/events/{event_id}/sessions/{session_id}/results"
        payload = self._get(path)
        return [parse_result_row(r) for r in self._rows(payload, path)]