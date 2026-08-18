"""Tests for shared helpers.

`client_ip` is security-relevant — it is the rate limiter's bucket key — and it
is derived from a header, so it deserves coverage even though it is six lines.
"""
from __future__ import annotations

from app.utils import client_ip


def test_client_ip_prefers_the_configured_header(app):
    with app.test_request_context(headers={"CF-Connecting-IP": "203.0.113.7"}):
        assert client_ip() == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr_when_the_header_is_absent(app):
    """Local development and the test client send no proxy headers."""
    with app.test_request_context(environ_base={"REMOTE_ADDR": "198.51.100.4"}):
        assert client_ip() == "198.51.100.4"


def test_client_ip_takes_the_first_entry_of_a_comma_separated_value(app):
    with app.test_request_context(headers={"CF-Connecting-IP": "203.0.113.7, 70.41.3.18"}):
        assert client_ip() == "203.0.113.7"


def test_client_ip_ignores_an_empty_header(app):
    with app.test_request_context(
        headers={"CF-Connecting-IP": ""}, environ_base={"REMOTE_ADDR": "198.51.100.4"}
    ):
        assert client_ip() == "198.51.100.4"
