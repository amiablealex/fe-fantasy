"""The lineup editor's draft state.

Moved out of `app/styleguide/scoring_bridge.py` in Phase 4, for the same reason
the roster was: this is production code and that is a debug-only package.

Nothing here scores anything or reads a result. It answers the three questions
the editor asks on every keystroke of a draft — what is broken, what would it
cost, and what would each option do — and it answers them by calling
`app/scoring/lineups.py`, the same module the server enforces on commit. The
wording is done here because `lineups.py` phrases a problem for a developer
reading a traceback and someone mid-transfer needs the team named and the fix
stated.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.lineups.roster import Roster
from app.models.grid import Team
from app.scoring import lineups


@dataclass
class SlotView:
    """What a filled slot needs to render. Shared by every lineup state."""

    label: str
    team: Team | None
    id: Any
    total: Decimal | None = None
    in_dream_team: bool = False
    number: int | None = None


def slot_view(roster: Roster, driver_id: Any) -> SlotView | None:
    driver = roster.drivers.get(driver_id)
    if driver is None:
        return None
    return SlotView(
        label=driver.short_label,
        team=roster.team_for(driver_id),
        id=driver_id,
        number=driver.number,
    )


def team_slot_view(roster: Roster, team_id: Any) -> SlotView | None:
    team = roster.teams.get(team_id) if team_id is not None else None
    if team is None:
        return None
    return SlotView(label=team.name, team=team, id=team_id)


@dataclass
class Option:
    """One row in the picker."""

    id: Any
    label: str
    team: Team | None
    number: int | None
    rounds: int
    selected: bool
    # What taking this option would mean. Never a reason it is forbidden —
    # nothing in the picker is forbidden.
    note: str | None = None


def _and_list(names: list[str]) -> str:
    """"Drugovich", "Drugovich and Di Grassi", "A, B and C"."""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _in_lineup(names: list[str]) -> str:
    verb = "is" if len(names) == 1 else "are"
    return f"{_and_list(names)} {verb} in your lineup"


def picker_options(
    roster: Roster, draft_drivers: list, draft_team: Any
) -> dict[str, list[Option]]:
    """Every driver and every team, with the consequences of each noted.

    Nothing is disabled. An earlier version greyed out options that would break
    a constraint, which taught the rule but created a trap: a player holding a
    Citroën driver could not select Citroën in the team slot, even though the
    reverse order — team first, then driver — was allowed. Same destination,
    same two-slot cost, arbitrary forced order. It also contradicted SPEC.md
    §4.1, which permits a draft to sit invalid precisely because a forced
    relocation has no legal intermediate.

    So the note replaces the block. The consequence is visible before you
    commit to it, and the two-slot change can be approached from either end.
    One rule across the whole editor: **the interface never prevents, it
    explains.**
    """
    taken_teams = {roster.team_of_driver.get(d) for d in draft_drivers}

    # A list, not a single name: a draft can legitimately hold both of a
    # team's cars while it is invalid, and naming only one of them would
    # under-report the problem the player has to fix.
    holders: dict[Any, list[str]] = {}
    for driver_id in draft_drivers:
        driver = roster.drivers.get(driver_id)
        if driver:
            holders.setdefault(
                roster.team_of_driver.get(driver_id), []
            ).append(driver.short_label)

    drivers: list[Option] = []
    for driver_id, team_id in roster.team_of_driver.items():
        driver = roster.drivers.get(driver_id)
        if driver is None:
            continue
        selected = driver_id in draft_drivers
        note = None
        if not selected and team_id in taken_teams:
            note = _in_lineup(holders[team_id])
        elif not selected and team_id == draft_team:
            note = "Your team pick"
        drivers.append(Option(
            id=driver_id,
            label=driver.short_label,
            team=roster.teams.get(team_id),
            number=driver.number,
            rounds=roster.rounds_participated.get(driver_id, 0),
            selected=selected,
            note=note,
        ))
    drivers.sort(key=lambda o: o.label or "")

    teams: list[Option] = []
    for team_id in roster.drivers_by_team:
        team = roster.teams.get(team_id)
        if team is None:
            continue
        selected = team_id == draft_team
        note = None
        if not selected and team_id in taken_teams:
            note = _in_lineup(holders[team_id])
        teams.append(Option(
            id=team_id, label=team.name, team=team, number=None, rounds=0,
            selected=selected, note=note,
        ))
    teams.sort(key=lambda o: o.label or "")

    return {"drivers": drivers, "teams": teams}


def draft_status(
    roster: Roster,
    draft_drivers: list,
    draft_team: Any,
    committed: lineups.Lineup | None,
) -> tuple[list[str], int, int]:
    """(problems, transfer cost, transfers available) for a draft.

    The rules come from `app/scoring/lineups.py` — the same module the server
    enforces on commit — so what the interface says and what the server allows
    cannot disagree. Only the wording is done here: `lineups.py` phrases a
    problem for a developer reading a traceback, and someone mid-transfer needs
    the team named and the fix stated.

    An incomplete draft is not an error. Only a broken rule is; "you have not
    finished picking" is a state the slot counter already shows.
    """
    by_team: dict = {}
    for driver_id in draft_drivers:
        by_team.setdefault(roster.team_of_driver.get(driver_id), []).append(driver_id)

    problems: list[str] = []
    for team_id, members in by_team.items():
        if len(members) > 1:
            problems.append(
                f"Too many drivers from {_team_name(roster, team_id)} — pick one."
            )
    if draft_team is not None and draft_team in by_team:
        problems.append(
            f"{_team_name(roster, draft_team)} is already represented by one of "
            f"your drivers."
        )

    cost = 0
    if len(draft_drivers) == lineups.DRIVER_SLOTS and draft_team is not None:
        draft = lineups.Lineup.of(draft_drivers, draft_team)
        cost = lineups.transfer_cost(committed, draft)
        # Cross-check: the wording above is ours, but the verdict must be the
        # engine's. A disagreement here is a bug in this module, not in the UI.
        engine_says = bool(lineups.validate_lineup(draft, roster.team_of_driver))
        if engine_says and not problems:
            problems.append("This lineup breaks a rule.")

    available = lineups.MAX_BANKED_TRANSFERS if committed else 0
    return problems, cost, available


def _team_name(roster: Roster, team_id: Any) -> str:
    team = roster.teams.get(team_id)
    return (team.name if team else str(team_id)) or str(team_id)


# -----------------------------------------------------------------------------
# Transfers
# -----------------------------------------------------------------------------


@dataclass
class TransferDiff:
    """What a draft would change, and what it would cost.

    The cost is `lineups.transfer_cost` — the count of changed slots, nothing
    cleverer. This exists to *name* the changes so the confirmation can list
    them, not to compute anything the engine already computes.
    """

    drivers_out: list[SlotView]
    drivers_in: list[SlotView]
    team_out: SlotView | None
    team_in: SlotView | None
    cost: int
    changed_ids: set

    @property
    def has_changes(self) -> bool:
        return bool(self.drivers_in or self.drivers_out or self.team_in or self.team_out)


def transfer_diff(
    roster: Roster,
    committed: lineups.Lineup | None,
    draft_drivers: list,
    draft_team: Any,
) -> TransferDiff:
    if committed is None:
        return TransferDiff([], [], None, None, 0, set())

    was = set(committed.drivers)
    now = set(draft_drivers)

    outgoing = [slot_view(roster, d) for d in sorted(was - now)]
    incoming = [slot_view(roster, d) for d in sorted(now - was)]

    team_out = team_in = None
    if draft_team != committed.team_id:
        team_out = team_slot_view(roster, committed.team_id)
        team_in = team_slot_view(roster, draft_team)

    changed = set(now - was)
    if team_in is not None:
        changed.add(draft_team)

    cost = len(now - was) + (1 if draft_team != committed.team_id else 0)

    return TransferDiff(
        drivers_out=[v for v in outgoing if v],
        drivers_in=[v for v in incoming if v],
        team_out=team_out,
        team_in=team_in,
        cost=cost,
        changed_ids=changed,
    )
