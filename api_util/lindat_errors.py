"""
api_util/lindat_errors.py  –  How a LINDAT client says why it stopped (atrium-nlp-enrich#41).

``call_udpipe.py`` and ``call_nametag.py`` exit with these codes, the stage scripts
(``api_2_udp.sh``, ``api_3_nt.sh``) pass them on, ``run_pipeline.py`` returns them unchanged, and
``service/enrichment.py`` maps them to the HTTP answer:

====  =======================================================  ===========================================
exit  cause                                                    HTTP
====  =======================================================  ===========================================
1     the input yielded nothing (an empty run)                 502, ``reason: null``
6     the service did not answer after the retries: HTTP 5xx   502 ``upstream_unavailable``
      or 429, a refused, reset or dropped connection
7     every attempt timed out (``LINDAT_TIMEOUT_S``)           504 ``limit_exceeded``, ``lindat_timeout_s``
8     the service answered and refused the request (HTTP 4xx  500: a deployment or request defect
      other than 429), e.g. an unknown model
====  =======================================================  ===========================================

The other codes of the pipeline are taken: 2 (a stage script missing), 3 (the flexiconv
preflight), 5 (the TEITOK output contract). Until #41 every failure of a client was exit 1, so an
outage, a timeout and an input that yields nothing all reached the caller as the same 502 "empty
run".

For 6, 7 and 8 the client's first line on stderr starts with :data:`LINE_PREFIX` and names the
service (``LINDAT UDPipe did not answer after 5 retries: …``); the service puts that line first in
the error's ``detail``.
"""

from __future__ import annotations

from typing import Optional

#: The input yielded nothing: a chunk file missing, or every chunk answered empty.
EXIT_EMPTY = 1
#: The service did not answer after the retries (5xx or 429, refused or dropped connection).
EXIT_UPSTREAM = 6
#: Every attempt timed out.
EXIT_UPSTREAM_TIMEOUT = 7
#: The service answered and refused the request (a 4xx other than 429).
EXIT_UPSTREAM_REFUSED = 8
#: The three codes a stage script passes on unchanged.
UPSTREAM_CODES = (EXIT_UPSTREAM, EXIT_UPSTREAM_TIMEOUT, EXIT_UPSTREAM_REFUSED)

#: How the line a client prints for 6, 7 or 8 starts; the service looks for it in the log tail.
LINE_PREFIX = "LINDAT "


def _status(exc: BaseException) -> Optional[int]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _chain(exc: BaseException):
    """``exc`` and every exception it wraps: ``__cause__``, ``__context__``, ``reason`` (urllib3's
    MaxRetryError) and exception ``args`` (requests wraps MaxRetryError that way)."""
    seen = set()
    stack = [exc]
    while stack:
        item = stack.pop()
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        stack.extend([item.__cause__, item.__context__, getattr(item, "reason", None)])
        stack.extend(arg for arg in getattr(item, "args", ()) if isinstance(arg, BaseException))


def is_timeout(exc: BaseException) -> bool:
    """True when the request failed because an attempt timed out.

    requests raises ``Timeout`` for a single attempt, but once urllib3's ``Retry`` has spent its
    attempts on read timeouts it raises ``ConnectionError`` around a ``MaxRetryError`` whose
    ``reason`` is the ``ReadTimeoutError``, so the chain is searched. urllib3's
    ``NewConnectionError`` derives from ``ConnectTimeoutError`` but is a refused or unresolvable
    connection, not a timeout.
    """
    try:
        import requests
        from urllib3.exceptions import NewConnectionError
        from urllib3.exceptions import TimeoutError as Urllib3Timeout
    except ImportError:  # pragma: no cover - the clients cannot run without them either
        return isinstance(exc, TimeoutError)
    for item in _chain(exc):
        if isinstance(item, NewConnectionError):
            continue
        if isinstance(item, (requests.exceptions.Timeout, Urllib3Timeout, TimeoutError)):
            return True
    return False


def classify(exc: BaseException) -> int:
    """The exit code for a request that failed with ``exc`` after the client's retries."""
    if is_timeout(exc):
        return EXIT_UPSTREAM_TIMEOUT
    status = _status(exc)
    if status is not None and 400 <= status < 500 and status != 429:
        return EXIT_UPSTREAM_REFUSED
    return EXIT_UPSTREAM


def describe(service: str, exc: BaseException, *, timeout: float, retries: int) -> str:
    """The first line a client prints before it exits with :func:`classify`'s code."""
    code = classify(exc)
    if code == EXIT_UPSTREAM_TIMEOUT:
        return (
            f"{LINE_PREFIX}{service} timed out: no answer within {timeout:g} s "
            f"on any of {retries + 1} attempt(s): {exc}"
        )
    if code == EXIT_UPSTREAM_REFUSED:
        return f"{LINE_PREFIX}{service} refused the request (HTTP {_status(exc)}): {exc}"
    return f"{LINE_PREFIX}{service} did not answer after {retries} retries: {exc}"
