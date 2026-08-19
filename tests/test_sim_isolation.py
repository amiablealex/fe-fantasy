"""The simulation must stay independent of the web application.

SPEC.md §12 puts `sim/` outside `app/` so there is no route by which the Flask
app can be imported into it. That is only true as long as nobody adds a
convenient import, so it is asserted rather than trusted.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SIM = pathlib.Path(__file__).resolve().parent.parent / "sim"

FORBIDDEN_ROOTS = {"flask", "flask_sqlalchemy", "flask_login", "sqlalchemy"}
FORBIDDEN_MODULES = {"app.extensions", "app.models", "app.ingest", "app.providers", "app.config"}

ALLOWED_APP_PREFIX = "app.scoring"


def _imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def sim_modules() -> list[pathlib.Path]:
    return sorted(SIM.glob("*.py"))


def test_the_sim_package_exists():
    assert sim_modules(), "sim/ should contain the simulation"


@pytest.mark.parametrize("path", sim_modules(), ids=lambda p: p.name)
def test_sim_never_imports_flask_or_sqlalchemy(path):
    for name in _imports(path):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_ROOTS, f"{path.name} imports {name}"


@pytest.mark.parametrize("path", sim_modules(), ids=lambda p: p.name)
def test_sim_touches_only_the_scoring_package(path):
    """Reading the database directly is fine; importing the models is not.

    The models pull in SQLAlchemy and the app factory, which would make the
    simulation depend on a working web application to answer questions about
    scoring.
    """
    for name in _imports(path):
        if not name.startswith("app"):
            continue
        assert name.startswith(ALLOWED_APP_PREFIX), (
            f"{path.name} imports {name}; sim/ may only import {ALLOWED_APP_PREFIX}"
        )
        assert name not in FORBIDDEN_MODULES
