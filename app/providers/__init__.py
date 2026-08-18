"""Data provider layer.

Exists from the first commit on purpose (SPEC.md §6, §12). Orange Cat Blacktop
is a small vendor whose CDN already blocks a plain server-side client on a tier
documented as server-side-only, so a swap is a live possibility. With this
package in place from the start, a swap is a new module rather than a refactor.

Phase 0 ships the exception types only. Nothing here makes a network call.
"""
