"""Provider exception types.

The distinction that matters: a CDN block and a data problem both surface as a
non-200, and confusing the two costs an afternoon. `ProviderBlockedError` exists
so a Cloudflare Error 1010 is never mistaken for a missing result.
"""
from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for all provider failures."""


class ProviderBlockedError(ProviderError):
    """The request never reached the API — CDN or WAF refusal (HTTP 403).

    Usually a User-Agent problem. The default Python UA is rejected by
    Cloudflare with Error 1010 before the API sees the request.
    """


class ProviderAuthError(ProviderError):
    """The API rejected the credentials (HTTP 401, or 403 from the API itself)."""


class ProviderTransientError(ProviderError):
    """A retryable failure: timeout, 5xx, or an incomplete payload.

    Distinct from a permanent failure so the worker can back off and retry
    rather than marking a round unscoreable.
    """


class ProviderPayloadError(ProviderError):
    """A 200 response whose shape or content is not what the parser expects."""


class ProviderRequestError(ProviderError):
    """The API rejected the request as malformed or unknown (HTTP 400 / 404).

    Permanent by nature: a numeric season id where a UUID is expected, or a
    session that does not exist. Retrying will not help.
    """
