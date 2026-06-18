"""Smoke tests for the RealtimeTrainsApi client.

Uses a hand-rolled fake ``aiohttp`` session that records requests and
replays canned responses per URL. This avoids pulling in the full
``aioresponses`` dependency; for the more complete coverage the live
fixture capture (M3) feeds a similar mock from recorded JSON files.
"""

from collections.abc import Mapping
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest

# Load api.py and models.py directly via importlib so the test does not
# need the full Home Assistant installed. ``api.py`` only imports
# ``aiohttp`` and ``models.py``; ``models.py`` only imports stdlib.
_REPO_ROOT = Path(__file__).resolve().parents[1]

_models_spec = importlib.util.spec_from_file_location(
    "rtt_models", _REPO_ROOT / "custom_components" / "realtime_trains" / "models.py"
)
assert _models_spec is not None and _models_spec.loader is not None
models = importlib.util.module_from_spec(_models_spec)
sys.modules["rtt_models"] = models
_models_spec.loader.exec_module(models)

# Inject models under the name api.py imports it as (a relative import
# ``from .models import …``). Because api.py uses a relative import it
# needs to be loaded as part of a package — emulate that by registering
# a minimal parent package.
sys.modules.setdefault("custom_components", type(sys)("custom_components"))
sys.modules.setdefault(
    "custom_components.realtime_trains",
    type(sys)("custom_components.realtime_trains"),
)
sys.modules["custom_components.realtime_trains.models"] = models
# And expose a tiny const module so ``from .const import API_VERSION...``
# works without the HA-aware ``_init__.py``.
_const_module = type(sys)("custom_components.realtime_trains.const")
_const_module.API_VERSION = "2026-04-09"  # noqa: SIM105  - simple attr
_const_module.BASE_URL = "https://data.rtt.io"
_const_module.TOKEN_REFRESH_LEAD_TIME = 60
sys.modules["custom_components.realtime_trains.const"] = _const_module

_api_spec = importlib.util.spec_from_file_location(
    "custom_components.realtime_trains.api",
    _REPO_ROOT / "custom_components" / "realtime_trains" / "api.py",
)
assert _api_spec is not None and _api_spec.loader is not None
api_module = importlib.util.module_from_spec(_api_spec)
sys.modules["custom_components.realtime_trains.api"] = api_module
_api_spec.loader.exec_module(api_module)

RealtimeTrainsApi = api_module.RealtimeTrainsApi
RttAuthError = api_module.RttAuthError
RttRateLimitError = api_module.RttRateLimitError
RttNotFoundError = api_module.RttNotFoundError
RttConnectionError = api_module.RttConnectionError
RttBadRequestError = api_module.RttBadRequestError
RttError = api_module.RttError


class _FakeResponse:
    """Mimic the parts of aiohttp ClientResponse our client uses."""

    def __init__(
        self,
        status: int,
        body: Any | None = None,
        headers: Mapping[str, str] | None = None,
        url: str = "",
    ) -> None:
        self.status = status
        self._body = body
        self.headers = dict(headers or {})
        self.url = url
        self._text = "" if body is None else json.dumps(body)

    async def json(self, content_type: str | None = None) -> Any:
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Records each request and replays a queued response."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
            }
        )
        if not self._responses:
            raise AssertionError("no queued response for request")
        return self._responses.pop(0)


@pytest.fixture
def fake_session() -> _FakeSession:
    return _FakeSession([])


async def test_get_info_caches_supplied_token_as_long_life() -> None:
    """A successful /api/info with the supplied token marks it as long-life."""
    body = {
        "api_version": "2026-01-18",
        "credentials": {"entitlements": ["allowDetailed"]},
    }
    session = _FakeSession([_FakeResponse(200, body)])
    client = RealtimeTrainsApi(
        session, token="long-life-token", api_version="2026-04-09"
    )
    info = await client.async_get_info()
    assert info.api_version == "2026-01-18"
    assert info.credentials.entitlements == ["allowDetailed"]
    # The supplied token should be cached so subsequent requests reuse it
    # (avoiding a needless refresh round-trip).
    assert client._access_token == "long-life-token"  # noqa: SLF001
    assert client._is_refresh_token is False  # noqa: SLF001


async def test_get_info_sends_authorization_and_version_headers() -> None:
    """Each request carries Bearer auth and the pinned Version header."""
    body = {"api_version": "2026-01-18", "credentials": {}}
    session = _FakeSession([_FakeResponse(200, body)])
    client = RealtimeTrainsApi(session, token="t1", api_version="2026-04-09")
    await client.async_get_info()
    assert session.calls[0]["headers"]["Authorization"] == "Bearer t1"
    assert session.calls[0]["headers"]["Version"] == "2026-04-09"


async def test_get_info_401_triggers_access_token_refresh_and_retry() -> None:
    """A 401 on /api/info falls back to /api/get_access_token then retries.

    The retry uses the freshly-minted access token for Authorization.
    """
    refresh_token = "refresh-token-input"
    access_token = "minted-access-token"

    info_body = {
        "api_version": "2026-01-18",
        "credentials": {"entitlements": ["allowDetailed"]},
    }
    token_body = {
        "token": access_token,
        "entitlements": ["allowDetailed"],
        "validUntil": "2026-12-31T23:59:59Z",
    }
    # Sequence: /api/info → 401. The client should detect the refresh
    # token, exchange it, mark itself as refresh-mode, then re-issue
    # /api/info with the access token.
    session = _FakeSession(
        [
            _FakeResponse(401, {"message": "unauthorised"}),
            _FakeResponse(200, token_body),
            _FakeResponse(200, info_body),
        ]
    )
    client = RealtimeTrainsApi(session, token=refresh_token, api_version="2026-04-09")
    info = await client.async_get_info()
    assert info.api_version == "2026-01-18"
    assert client._access_token == access_token  # noqa: SLF001
    assert client._is_refresh_token is True  # noqa: SLF001
    # The first call used the supplied refresh token; the third call
    # used the minted access token.
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {refresh_token}"
    assert session.calls[2]["headers"]["Authorization"] == f"Bearer {access_token}"


async def test_rate_limit_headers_are_captured() -> None:
    """X-RateLimit-* headers populate `client.rate_limits`."""
    body = {"api_version": "2026-01-18", "credentials": {}}
    headers = {
        "X-RateLimit-Limit-Hour": "1000",
        "X-RateLimit-Remaining-Hour": "950",
        "X-RateLimit-Limit-Minute": "60",
        "X-RateLimit-Remaining-Minute": "42",
    }
    session = _FakeSession([_FakeResponse(200, body, headers=headers)])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    await client.async_get_info()
    snap = client.rate_limits
    assert snap.hour is not None
    assert snap.hour.limit == 1000
    assert snap.hour.remaining == 950
    assert snap.minute is not None
    assert snap.minute.remaining == 42


async def test_429_raises_rate_limit_error_with_retry_after() -> None:
    """A 429 response raises RttRateLimitError carrying Retry-After."""
    headers = {"Retry-After": "30"}
    session = _FakeSession(
        [_FakeResponse(429, {"message": "too many requests"}, headers=headers)]
    )
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    with pytest.raises(RttRateLimitError) as exc:
        await client.async_get_info()
    assert exc.value.retry_after == 30


async def test_404_on_service_raises_not_found() -> None:
    """A 404 from /gb-nr/service raises RttNotFoundError (not the bare error)."""
    session = _FakeSession([_FakeResponse(404, {"message": "service not found"})])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    with pytest.raises(RttNotFoundError):
        await client.async_get_service("gb-nr:1L40:2026-06-18", namespace="gb-nr")


async def test_get_stops_parses_response() -> None:
    """/data/stops response is parsed into typed Stop items."""
    body = {
        "stops": [
            {
                "namespace": "gb-nr",
                "description": "Clapham Junction",
                "shortCode": "CLJ",
                "uniqueIdentity": "gb-nr:CLJ",
            }
        ]
    }
    session = _FakeSession([_FakeResponse(200, body)])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    stops = await client.async_get_stops()
    assert len(stops) == 1
    assert stops[0].description == "Clapham Junction"
    assert stops[0].short_code == "CLJ"


async def test_get_location_dispatches_to_gb_nr_endpoint() -> None:
    """namespace=gb-nr routes to /gb-nr/location; generic stays on /rtt/location."""
    body = {
        "systemStatus": {"realtimeNetworkRail": "OK", "rttCore": "OK"},
        "services": [],
    }
    session = _FakeSession([_FakeResponse(200, body)])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    await client.async_get_location("CLPHMJN", namespace="gb-nr")
    assert session.calls[0]["url"].endswith("/gb-nr/location")
    assert session.calls[0]["params"]["code"] == "CLPHMJN"


async def test_get_location_204_returns_empty_response() -> None:
    """A 204 (no services) returns an empty LocationLineUpResponse."""
    session = _FakeSession([_FakeResponse(204, None)])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    result = await client.async_get_location("CLJ")
    # Empty response parses to an object with no services.
    assert result.services == []


async def test_get_service_dispatches_to_gb_nr_endpoint() -> None:
    """/gb-nr/service returns a NetworkRailServiceDetail with allocations."""
    body = {
        "systemStatus": {"realtimeNetworkRail": "OK", "rttCore": "OK"},
        "query": {"uniqueIdentity": "gb-nr:1L40:2026-06-18"},
        "service": {
            "scheduleMetadata": {
                "uniqueIdentity": "gb-nr:1L40:2026-06-18",
                "namespace": "gb-nr",
                "identity": "1L40",
                "departureDate": "2026-06-18",
                "trainReportingIdentity": "1L40",
                "stpIndicator": "WTT",
            },
            "locations": [],
            "allocationData": [],
        },
    }
    session = _FakeSession([_FakeResponse(200, body)])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    result = await client.async_get_service("gb-nr:1L40:2026-06-18", namespace="gb-nr")
    assert result.schedule_metadata is not None
    assert result.schedule_metadata.train_reporting_identity == "1L40"
    # Allocation data list parses to empty (not None).
    assert result.allocation_data == []


async def test_connection_error_mapped() -> None:
    """An aiohttp.ClientError surfaces as RttConnectionError."""

    class _BoomSession:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            raise api_module.aiohttp.ClientError("DNS failure")

    client = RealtimeTrainsApi(_BoomSession(), token="t", api_version="2026-04-09")
    with pytest.raises(RttConnectionError):
        await client.async_get_info()


async def test_bad_request_400_raises_typed_error() -> None:
    """400 maps to RttBadRequestError."""
    session = _FakeSession([_FakeResponse(400, {"message": "bad code"})])
    client = RealtimeTrainsApi(session, token="t", api_version="2026-04-09")
    with pytest.raises(RttBadRequestError):
        await client.async_get_location("UNKNOWN_STATION", namespace="gb-nr")


def test_main_module_is_asyncio_compatible() -> None:
    """Sanity: the client methods are coroutines, not plain functions."""
    import inspect

    assert inspect.iscoroutinefunction(RealtimeTrainsApi.async_get_info)
    assert inspect.iscoroutinefunction(RealtimeTrainsApi.async_get_stops)


async def test_supplied_token_takes_precedence_when_long_life() -> None:
    """Once classified as long-life, no /api/get_access_token is attempted."""
    info_body = {"api_version": "2026-01-18", "credentials": {}}
    second_info_body = {
        "api_version": "2026-01-18",
        "credentials": {"entitlements": ["x"]},
    }
    session = _FakeSession(
        [
            _FakeResponse(200, info_body),
            _FakeResponse(200, second_info_body),
        ]
    )
    client = RealtimeTrainsApi(session, token="t1", api_version="2026-04-09")
    await client.async_get_info()
    await client.async_get_info()
    # Only two requests should have been made: no refresh-token call.
    assert len(session.calls) == 2
    assert all(call["url"].endswith("/api/info") for call in session.calls)
