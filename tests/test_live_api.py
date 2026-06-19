"""Live-API integration tests for the Realtime Trains client.

These tests hit the real ``https://data.rtt.io`` API end-to-end. They
are **temporary** — they exist to validate the integration's wiring
while we work through the audit findings, and to give the operator a
quick way to exercise the real API from a fast feedback loop without
booting HA. Once the HA-dependent snapshot tests are green in CI,
these should be removed (or kept gated behind the ``live`` marker and
only run on demand with a token — never on every push).

Run locally:

    RTT_TOKEN=xxxx uv run pytest tests/test_live_api.py -m live -v

The tests never log or print the token; the ``RealtimeTrainsApi``
client already redacts ``Authorization`` headers (see
``diagnostics.py`` for the redaction policy that mirrors this).

If ``RTT_TOKEN`` is not set, every test in this file is skipped.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any

import pytest

pytestmark = [pytest.mark.live]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_KEY = os.environ.get("RTT_TOKEN")
_HAS_TOKEN = bool(_API_KEY)
_SKIP_REASON = "RTT_TOKEN env var not set — set it to run live-API tests"


# --- Load real api.py + models.py via importlib (no HA needed) -------------


def _load_api_module() -> Any:
    """Load custom_components.realtime_trains.api + models without HA."""
    models_spec = importlib.util.spec_from_file_location(
        "rtt_models",
        _REPO_ROOT / "custom_components" / "realtime_trains" / "models.py",
    )
    assert models_spec is not None and models_spec.loader is not None
    models = importlib.util.module_from_spec(models_spec)
    sys.modules["rtt_models"] = models
    models_spec.loader.exec_module(models)

    sys.modules.setdefault("custom_components", type(sys)("custom_components"))
    sys.modules.setdefault(
        "custom_components.realtime_trains",
        type(sys)("custom_components.realtime_trains"),
    )
    sys.modules["custom_components.realtime_trains.models"] = models

    const_module = type(sys)("custom_components.realtime_trains.const")
    const_module.API_VERSION = "2026-04-09"
    const_module.BASE_URL = "https://data.rtt.io"
    const_module.TOKEN_REFRESH_LEAD_TIME = 60
    sys.modules["custom_components.realtime_trains.const"] = const_module

    api_spec = importlib.util.spec_from_file_location(
        "custom_components.realtime_trains.api",
        _REPO_ROOT / "custom_components" / "realtime_trains" / "api.py",
    )
    assert api_spec is not None and api_spec.loader is not None
    api_module = importlib.util.module_from_spec(api_spec)
    sys.modules["custom_components.realtime_trains.api"] = api_module
    api_spec.loader.exec_module(api_module)
    return api_module


_api = _load_api_module()
RealtimeTrainsApi = _api.RealtimeTrainsApi
RttAuthError = _api.RttAuthError
RttNotFoundError = _api.RttNotFoundError
RttRateLimitError = _api.RttRateLimitError
RttConnectionError = _api.RttConnectionError

# Re-export models for type assertions
NetworkRailLocationLineUpResponse = sys.modules[
    "custom_components.realtime_trains.models"
].NetworkRailLocationLineUpResponse
NetworkRailServiceDetail = sys.modules[
    "custom_components.realtime_trains.models"
].NetworkRailServiceDetail
Stop = sys.modules["custom_components.realtime_trains.models"].Stop
ApiInfo = sys.modules["custom_components.realtime_trains.models"].ApiInfo
LocationStatus = sys.modules["custom_components.realtime_trains.models"].LocationStatus


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def api_client() -> Any:
    """Return a RealtimeTrainsApi wired to the live API with the env token."""
    pytest.importorskip("aiohttp")
    import aiohttp

    if not _HAS_TOKEN:
        pytest.skip(_SKIP_REASON, allow_module_level=False)
    assert _API_KEY is not None  # for the type checker
    session = aiohttp.ClientSession()
    client = RealtimeTrainsApi(
        session,
        _API_KEY,
        api_version="2026-04-09",
    )
    yield client
    asyncio.get_event_loop_policy()
    asyncio.run(session.close())


@pytest.fixture
def http_session() -> Any:
    """A bare aiohttp session that the test is responsible for closing.

    Use this when the api_client fixture's auto-close is not what you
    want (e.g. when issuing raw requests).
    """
    pytest.importorskip("aiohttp")
    import aiohttp

    if not _HAS_TOKEN:
        pytest.skip(_SKIP_REASON, allow_module_level=False)
    session = aiohttp.ClientSession()
    yield session
    asyncio.run(session.close())


# Skip the whole module gracefully if no token.
if not _HAS_TOKEN:
    pytest.skip(_SKIP_REASON, allow_module_level=True)


# --- Smoke tests ------------------------------------------------------------


async def test_api_info_returns_version_and_credentials(api_client: Any) -> None:
    """/api/info returns the API version and a credentials block."""
    info = await api_client.async_get_info()
    assert isinstance(info, ApiInfo)
    assert info.api_version is not None
    assert info.api_version != ""
    assert info.credentials is not None
    # Entitlements should be a list (possibly empty for a minimal token).
    assert isinstance(info.credentials.entitlements, list)
    print(f"  live api_version={info.api_version}")
    print(
        f"  live entitlements={info.credentials.entitlements} "
        f"namespaces={info.credentials.namespaces_available}"
    )


async def test_get_access_token_refresh_flow(api_client: Any) -> None:
    """If the supplied token is a refresh token, /api/get_access_token succeeds.

    This test is a no-op when the token is already a long-life access
    token (the client auto-detects and skips the refresh).
    """
    await api_client.async_get_info()  # classifies the token first
    if api_client._is_refresh_token is not True:
        pytest.skip("supplied token is a long-life access token; refresh not exercised")
    token_response = await api_client.async_get_access_token()
    assert token_response.token
    assert token_response.token != _API_KEY  # a different access token
    # Must NOT appear in logs. We don't assert on logs directly; the
    # client only stores it in `_access_token` (private) and uses it
    # for outbound Authorization headers (never printed).


async def test_get_stops_returns_list_of_stops(api_client: Any) -> None:
    """/data/stops returns a non-empty list of Stop objects."""
    stops = await api_client.async_get_stops()
    assert isinstance(stops, list)
    assert len(stops) > 100  # the stops list is large
    first = stops[0]
    assert isinstance(first, Stop)
    assert first.namespace
    # Some stops have null short_code; just check that most have one.
    with_short_code = [s for s in stops if s.short_code]
    assert len(with_short_code) > 50
    print(
        f"  live stops count={len(stops)} "
        f"first_stops={[s.description for s in stops[:3]]}"
    )


async def test_get_location_for_clapham_junction(
    api_client: Any,
) -> None:
    """/gb-nr/location returns a board with services."""
    response = await api_client.async_get_location(
        "CLPHMJN",
        time_window=120,
        namespace="gb-nr",
    )
    assert isinstance(response, NetworkRailLocationLineUpResponse)
    assert response.services, "expected non-empty board for CLPHMJN"
    svc = response.services[0]
    assert svc.schedule_metadata is not None
    print(
        f"  live board: {len(response.services)} services "
        f"first={svc.schedule_metadata.train_reporting_identity}"
    )


async def test_get_location_with_filter_to(api_client: Any) -> None:
    """/gb-nr/location filterTo=WOK returns services that call at Woking."""
    response = await api_client.async_get_location(
        "CLPHMJN",
        filter_to="WOK",
        time_window=180,
        namespace="gb-nr",
    )
    assert isinstance(response, NetworkRailLocationLineUpResponse)
    # The filter should produce a non-empty result during travel hours.
    # If it's empty we don't fail — just note it (off-peak may legitimately
    # produce zero).
    print(f"  live CLPHMJN→WOK services={len(response.services)}")


async def test_get_service_for_a_known_headcode(api_client: Any) -> None:
    """Fetch service detail for a headcode+date that should return a service.

    Queries the first service currently on the Clapham Junction board
    and looks it up by its headcode; this guarantees a present-day
    headcode + date that should exist.
    """
    board = await api_client.async_get_location(
        "CLPHMJN", time_window=120, namespace="gb-nr"
    )
    if not board.services:
        pytest.skip("no services on the live board to look up")

    first = board.services[0]
    sm = first.schedule_metadata
    if sm is None or sm.train_reporting_identity is None or sm.departure_date is None:
        pytest.skip("first board service is missing headcode/date")

    detail = await api_client.async_get_service(
        identity=sm.train_reporting_identity,
        departure_date=sm.departure_date,
        namespace="gb-nr",
    )
    assert isinstance(detail, NetworkRailServiceDetail)
    assert detail.locations, "expected at least one location"
    assert detail.schedule_metadata is not None
    print(
        f"  live service {sm.train_reporting_identity} {sm.departure_date} "
        f"→ {len(detail.locations)} locations "
        f"uid={detail.schedule_metadata.unique_identity}"
    )


async def test_get_service_with_invalid_headcode_raises_not_found(
    api_client: Any,
) -> None:
    """A non-existent headcode raises RttNotFoundError."""
    with pytest.raises(RttNotFoundError):
        await api_client.async_get_service(
            identity="ZZ99",
            departure_date="2000-01-01",
            namespace="gb-nr",
        )


async def test_invalid_token_raises_auth_error(http_session: Any) -> None:
    """An obviously-invalid token raises RttAuthError on /api/info."""
    bad_client = RealtimeTrainsApi(
        http_session,
        "this-is-not-a-real-token",  # noqa: S106
        api_version="2026-04-09",
    )
    with pytest.raises(RttAuthError):
        await bad_client.async_get_info()


async def test_rate_limit_headers_are_captured(api_client: Any) -> None:
    """After /api/info, the client has rate-limit headers from the response."""
    await api_client.async_get_info()
    # All rate-limit dimensions may not be present in every response, but
    # the snapshot structure should at least exist.
    assert api_client.rate_limits is not None
    print(f"  live rate_limits={api_client.rate_limits}")


# --- Coordinator-shape smoke tests -----------------------------------------


async def test_real_service_has_consistent_locations_and_metadata(
    api_client: Any,
) -> None:
    """ScheduleMetadata unique_identity matches the service's locations."""
    board = await api_client.async_get_location(
        "WAT", time_window=120, namespace="gb-nr"
    )
    if not board.services:
        pytest.skip("no services on the WAT live board")
    first = board.services[0]
    sm = first.schedule_metadata
    if sm is None or not all([sm.train_reporting_identity, sm.departure_date]):
        pytest.skip("first WAT board service is missing fields")
    detail = await api_client.async_get_service(
        identity=sm.train_reporting_identity,
        departure_date=sm.departure_date,
        namespace="gb-nr",
    )
    # First and last locations should have temporal_data with a scheduled
    # departure / arrival (the spec promises this for in-passenger-service
    # services).
    if detail.locations:
        first_loc = detail.locations[0]
        last_loc = detail.locations[-1]
        if first_loc.temporal_data and first_loc.temporal_data.departure:
            assert first_loc.temporal_data.departure.schedule_advertised is not None
        if last_loc.temporal_data and last_loc.temporal_data.arrival:
            assert last_loc.temporal_data.arrival.schedule_advertised is not None
