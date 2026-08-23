"""The Phase 7.1 split: what each module owns, and what the shim still promises.

Three things are pinned here.

`display` must stay free of SQLAlchemy and Flask. That is checked statically
rather than by importing and looking at `sys.modules`, because importing
anything under `app.` runs `app/__init__.py`, which imports the models — so a
runtime check would fail for every module in the project and prove nothing. The
walk below reads the source instead, which is what the claim actually is: this
module's *dependencies* are clean, whatever else the process has loaded.

The shim must re-export exactly what it says it does, because it is the only
thing keeping a dozen unrewritten callers working until stage 7.5.

And a slot key must distinguish two drivers who share a surname, which the old
label-based key did not.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from flask import Flask

from app import localtime
from app.meetings import bridge, display, queries, scoring_bridge, view

REPO = Path(__file__).resolve().parents[1]

FORBIDDEN = ("sqlalchemy", "flask", "app.models", "app.extensions")


def _module_path(dotted: str) -> Path | None:
    candidate = REPO / Path(*dotted.split(".")).with_suffix(".py")
    if candidate.exists():
        return candidate
    package = REPO / Path(*dotted.split(".")) / "__init__.py"
    return package if package.exists() else None


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module)
                # `from app.scoring import engine` names a module, not a
                # symbol. Without this the walk stops at the package's
                # __init__ and never reads the file that was actually
                # imported — which would make this test pass by not looking.
                if node.module.startswith("app"):
                    found.update(
                        f"{node.module}.{alias.name}" for alias in node.names
                    )
    return found


def _transitive_imports(dotted: str) -> set[str]:
    """Every module reachable from `dotted`, following only `app.*` edges.

    Stopping at the package boundary is the point: we care that `display` does
    not reach SQLAlchemy through one of our own modules, not that the standard
    library is pure.
    """
    seen: set[str] = set()
    collected: set[str] = set()
    queue = [dotted]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        path = _module_path(current)
        if path is None:
            continue
        for name in _imports(path):
            collected.add(name)
            if name.startswith("app.") and name not in seen:
                queue.append(name)
    return collected


def test_display_imports_no_orm_and_no_flask():
    """Wording is the cheapest thing in the project to import, and stays so."""
    reached = _transitive_imports("app.meetings.display")
    offenders = sorted(
        name for name in reached
        if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
    )
    assert offenders == [], (
        f"app/meetings/display.py reaches {offenders}; it must import the "
        "engine and nothing else."
    )


def test_bridge_stays_small():
    """The worker's forty lines do not quietly grow back into nine hundred."""
    source = (REPO / "app" / "meetings" / "bridge.py").read_text()
    tree = ast.parse(source)
    functions = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert set(functions) == {"ruleset_for", "result_row", "round_payload"}


@pytest.mark.parametrize("name", scoring_bridge.__all__)
def test_shim_reexports_the_real_object(name):
    """Not merely importable: the same object the owning module defines.

    A shim that rebound a name to a copy would let the two drift, which is the
    single failure a compatibility layer exists to prevent.
    """
    exported = getattr(scoring_bridge, name)
    owners = [bridge, display, queries, view]
    assert any(getattr(owner, name, None) is exported for owner in owners), (
        f"{name} is exported by the shim but is not the object any of "
        "bridge/display/queries/view defines."
    )


def test_shim_adds_nothing_of_its_own():
    """Every public name on the shim is declared, so deleting it is safe."""
    public = {
        name for name in vars(scoring_bridge)
        if not name.startswith("__") and name != "annotations"
    }
    assert public == set(scoring_bridge.__all__)


# -----------------------------------------------------------------------------
# Slot identity
# -----------------------------------------------------------------------------


class _Subject:
    def __init__(self, id_, number=None):
        self.id = id_
        self.number = number


def _pick(kind, label, subject):
    return view.PickScore(
        kind=kind, label=label, subject=subject, team=None,
        total=Decimal(0), components=(),
    )


def test_slot_key_separates_two_drivers_sharing_a_label():
    """Two Schumachers are two slots.

    The old key was `(kind, label)`, and `short_label` is a surname. Folding
    them would double one figure and drop the other with no error anywhere.
    """
    one = _pick("driver", "SCHUMACHER", _Subject(4))
    two = _pick("driver", "SCHUMACHER", _Subject(9))
    assert view._slot_key(one) != view._slot_key(two)


def test_slot_key_falls_back_to_the_label_without_a_subject():
    orphan = _pick("driver", "1234", None)
    assert view._slot_key(orphan) == ("driver", "1234")


# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------


def test_split_components_puts_every_rule_on_one_side():
    from app.scoring.engine import ScoreComponent

    components = (
        ScoreComponent("group_progress", Decimal(2)),
        ScoreComponent("pole", Decimal(3)),
        ScoreComponent("race_win", Decimal(5)),
        ScoreComponent("places_lost", Decimal(-4)),
    )
    qualifying, race = display.split_components(components)
    assert len(qualifying) == 2
    assert len(race) == 2
    assert len(qualifying) + len(race) == len(components)


def test_fmt_keeps_a_half_and_drops_a_trailing_zero():
    assert display.fmt(Decimal("5.5")) == "5.5"
    assert display.fmt(Decimal("26.0")) == "26"
    assert display.fmt(Decimal("20")) == "20"
    assert display.fmt(None) == "—"


# -----------------------------------------------------------------------------
# Timezone
# -----------------------------------------------------------------------------

# Berlin, mid-season, British Summer Time.
SUMMER = datetime(2027, 5, 15, 13, 0, tzinfo=timezone.utc)
# Jeddah, the opener.
WINTER = datetime(2026, 12, 18, 13, 0, tzinfo=timezone.utc)


def _app(zone="Europe/London"):
    app = Flask(__name__)
    app.config["DISPLAY_TIMEZONE"] = zone
    localtime.register(app)
    return app


def test_summer_shifts_an_hour_and_says_bst():
    with _app().app_context():
        rendered = localtime.local(SUMMER)
    assert "14:00" in rendered
    assert "BST" in rendered


def test_winter_does_not_shift_and_says_gmt():
    with _app().app_context():
        rendered = localtime.local(WINTER)
    assert "13:00" in rendered
    assert "GMT" in rendered


def test_a_naive_datetime_is_read_as_utc_not_as_local():
    """The failure this module exists to prevent, pinned.

    Treating a naive value as already-local would shift it by an hour in summer
    with no error — a deadline shown early, which costs a lineup rather than
    merely looking untidy.
    """
    with _app().app_context():
        aware = localtime.local(SUMMER)
        naive = localtime.local(SUMMER.replace(tzinfo=None))
    assert aware == naive


def test_an_unknown_zone_degrades_to_utc_rather_than_raising():
    with _app("Mars/Olympus_Mons").app_context():
        assert "13:00" in localtime.local(SUMMER)


def test_none_renders_as_an_em_dash_not_an_exception():
    with _app().app_context():
        assert localtime.local(None) == "—"
