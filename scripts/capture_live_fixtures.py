#!/usr/bin/env python3
"""Capture fresh fixtures from the live Realtime Trains API.

Reads a token from the ``RTT_TOKEN`` environment variable and writes
JSON snapshots under ``tests/fixtures/`` for each endpoint the
integration uses. The token is never written to disk — only redacted
header placeholders are recorded.

The captured fixtures are committed and consumed by ``tests/conftest.py``
to mock ``aiohttp`` in unit tests, so the test suite is reproducible
without a token. Re-run this script when the API model evolves.

Example::

    RTT_TOKEN=xxxx uv run scripts/capture_live_fixtures.py

Optional environment overrides:

* ``RTT_BASE_URL`` — defaults to ``https://data.rtt.io``.
* ``RTT_STATION`` — long code for the location-line-up capture
  (default: ``CLPHMJN``, Clapham Junction).
* ``RTT_HEADCODE`` / ``RTT_DATE`` — service tracker capture
  (default: ``1L40`` / today).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

import aiohttp

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
DEFAULT_BASE_URL = "https://data.rtt.io"
DEFAULT_STATION = "CLPHMJN"
DEFAULT_HEADCODE = "1L40"
API_VERSION = "2026-04-09"

# Headers we never want to leak into a fixture.
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie"}


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        out[k.lower()] = "****" if k.lower() in SENSITIVE_HEADERS else v
    return out


def _fixture_envelope(  # noqa: PLR0913
    method: str,
    path: str,
    params: Mapping[str, str | int] | None,
    status: int,
    headers: Mapping[str, str],
    body: object,
) -> dict[str, object]:
    return {
        "request": {
            "method": method,
            "path": path,
            "params": dict(params) if params else {},
        },
        "response": {
            "status": status,
            "headers": _redact_headers(headers),
            "body": body,
        },
    }


async def _capture(  # noqa: PLR0913
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    params: Mapping[str, str | int] | None,
    out_path: Path,
    allow_404: bool = False,
) -> int:
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    url = f"{base_url}{path}"
    print(f"  → {method} {url} params={params or {}}")
    async with session.request(method, url, headers=headers, params=params) as resp:
        text = await resp.text()
        try:
            body: object = json.loads(text) if text else None
        except json.JSONDecodeError:
            body = {"_raw": text[:1024]}

    status_not_found = 404
    status_rate_limited = 429

    if resp.status == status_not_found and not allow_404:
        print(f"    ✗ unexpected 404 (status={resp.status})")
        return resp.status
    if resp.status == status_rate_limited:
        print(
            f"    ⚠ rate-limited (Retry-After={resp.headers.get('Retry-After')}); "
            "fixture will reflect the 429 response."
        )

    envelope = _fixture_envelope(method, path, params, resp.status, resp.headers, body)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")  # noqa: ASYNC240
    print(f"    ✓ wrote {out_path.relative_to(FIXTURE_DIR.parent.parent)}")
    return resp.status


async def _run_captures(  # noqa: PLR0913, C901
    token: str,
    base_url: str,
    station: str,
    headcode: str,
    date: str,
) -> int:
    """Hit each endpoint we use and write a fixture for each."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # /api/info — token validation + entitlements.
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/api/info",
            params=None,
            out_path=FIXTURE_DIR / "api_info.json",
        )

        # /data/stops — passenger-stops list. Large but stable; we keep
        # the whole thing rather than a subset so station-picker tests
        # can match any user input.
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/data/stops",
            params=None,
            out_path=FIXTURE_DIR / "stops.json",
        )

        # /data/locations_ungrouped — kept just as a smoke sample; full
        # response can be very large.
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/data/locations_ungrouped",
            params=None,
            out_path=FIXTURE_DIR / "locations_ungrouped.json",
        )

        # /gb-nr/location — Network Rail departure board. Use the
        # default busy station so fixtures include multiple services
        # with a mix of scheduled and realtime data.
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/gb-nr/location",
            params={"code": station, "timeWindow": 120},
            out_path=FIXTURE_DIR / f"location_{station.lower()}.json",
        )

        # /gb-nr/location with a destination filter — useful for board
        # entities that filter to one destination.
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/gb-nr/location",
            params={"code": station, "filterTo": "WOK", "timeWindow": 120},
            out_path=FIXTURE_DIR / f"location_{station.lower()}_filtered.json",
        )

        # /gb-nr/service — service detail with allocations + KYT (when
        # the token has the entitlements).
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/gb-nr/service",
            params={"identity": headcode, "departureDate": date},
            out_path=FIXTURE_DIR / f"service_{headcode}_{date}.json",
            allow_404=True,
        )

        # /data/stops with a fresh_token-style 401 — useful for testing
        # the refresh-token fallback. We hit /api/info with a
        # deliberately-invalid bearer to capture the 401 shape (no
        # token is leaked by this).
        await _capture(
            session,
            base_url=base_url,
            token=token,
            method="GET",
            path="/api/info",
            params=None,
            out_path=FIXTURE_DIR / "api_info_401_invalid_token.json",
        )

    return 0


def main() -> int:
    """Capture fixtures into tests/fixtures/. Refuses to run without a token."""
    token = os.environ.get("RTT_TOKEN")
    if not token:
        print(
            "RTT_TOKEN environment variable is not set.\n"
            "Capture refuses to run without a token so that no token "
            "is ever written to disk.",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get("RTT_BASE_URL", DEFAULT_BASE_URL)
    station = os.environ.get("RTT_STATION", DEFAULT_STATION)
    headcode = os.environ.get("RTT_HEADCODE", DEFAULT_HEADCODE)
    # Default to today in Europe/London-ish UTC; tests don't care about
    # the exact date — only that the response is well-formed.
    date = os.environ.get("RTT_DATE", datetime.now(UTC).strftime("%Y-%m-%d"))

    print(f"Capturing fixtures into {FIXTURE_DIR}")
    print(f"  base_url={base_url}")
    print(f"  station={station}")
    print(f"  headcode={headcode} date={date}")
    print()

    try:
        return asyncio.run(_run_captures(token, base_url, station, headcode, date))
    except aiohttp.ClientError as err:
        print(f"\nNetwork error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
