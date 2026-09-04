"""Small bounded HTTP primitives shared by integration adapters."""
from __future__ import annotations

import math
from collections.abc import Mapping
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_HEADERS = {
    "Range": "bytes=0-0",
    "User-Agent": "ipad-agent-url-validator/1",
}


class RedirectResolutionError(ValueError):
    """One bounded HTTP request did not yield one usable redirect."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_one_redirect(
    url: str,
    *,
    timeout: float = 3.0,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Return one redirect Location without following it or reading a body."""
    if not isinstance(url, str) or not url:
        raise TypeError("redirect URL must be a non-empty string")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or timeout <= 0
    ):
        raise ValueError("redirect timeout must be a positive finite number")
    request_headers = dict(_DEFAULT_HEADERS if headers is None else headers)
    if not all(
        isinstance(key, str) and key and isinstance(value, str)
        for key, value in request_headers.items()
    ):
        raise TypeError("redirect headers must map non-empty strings to strings")
    request = Request(url, method="GET", headers=request_headers)
    try:
        response = build_opener(_RejectRedirects()).open(request, timeout=float(timeout))
    except HTTPError as error:
        try:
            if error.code not in _REDIRECT_CODES:
                raise RedirectResolutionError(f"returned HTTP {error.code}") from error
            location = error.headers.get("Location")
            if not isinstance(location, str) or not location:
                raise RedirectResolutionError("returned no redirect target") from error
            return location
        finally:
            error.close()
    except OSError as error:
        raise RedirectResolutionError(f"could not be resolved: {error}") from error
    else:
        response.close()
        raise RedirectResolutionError("did not return a redirect")


__all__ = ["RedirectResolutionError", "resolve_one_redirect"]
