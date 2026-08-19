"""Ingestion: turning provider payloads into rows.

The provider layer normalises vendor JSON into dataclasses; this layer decides
what those dataclasses mean for the domain — which events form a meeting, what
round number a race carries, when a lineup locks — and writes it down.

Everything here is idempotent. Running a sync twice must produce the same
database as running it once.
"""
