"""Lineups: the roster, the game rules over stored snapshots, and the editor.

    roster.py    who is pickable, and which team they drove for, per round
    service.py   grace, the transfer bank, locking, and commit

The blueprint arrives with the editor routes; this package is importable
without it, which is what lets the service be tested without HTTP.
"""
