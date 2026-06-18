"""Smoke tests for fixture files.

Each committed fixture is loaded and pushed through the matching
model parser, so we catch any drift between the recorded API shape
and the typed models before tests that depend on them run.

Models are loaded via ``importlib`` rather than through the package's
``__init__.py`` (which imports Home Assistant and so cannot be
imported in local dev without HA core installed). The same shim is
used by ``tests/test_api.py``.
"""

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures"

_models_spec = importlib.util.spec_from_file_location(
    "rtt_models", _REPO_ROOT / "custom_components" / "realtime_trains" / "models.py"
)
assert _models_spec is not None and _models_spec.loader is not None
m = importlib.util.module_from_spec(_models_spec)
sys.modules["rtt_models"] = m
_models_spec.loader.exec_module(m)


def _load_fixture(name: str) -> dict[str, Any]:
    path = _FIXTURE_DIR / name
    envelope = json.loads(path.read_text())
    assert isinstance(envelope, dict)
    assert "response" in envelope
    return envelope


def test_fixture_api_info_parses() -> None:
    env = _load_fixture("api_info.json")
    parsed = m.ApiInfo.from_dict(env["response"]["body"])
    assert parsed.api_version == "2026-01-18"
    assert "allowDetailed" in parsed.credentials.entitlements
    assert parsed.credentials.history_restriction is True


def test_fixture_api_info_401_envelope_shape() -> None:
    env = _load_fixture("api_info_401_invalid_token.json")
    assert env["response"]["status"] == 401
    body = env["response"]["body"]
    assert body["message"] == "unauthorised"
    # Redaction happens at capture time. We don't model the error body
    # as a dataclass because raised exceptions carry the message string.


def test_fixture_access_token_parses() -> None:
    env = _load_fixture("get_access_token.json")
    parsed = m.AccessTokenResponse.from_dict(env["response"]["body"])
    assert parsed.token.startswith("eyJ")
    assert parsed.valid_until is not None
    assert parsed.valid_until.year == 2026


def test_fixture_stops_parses() -> None:
    env = _load_fixture("stops.json")
    parsed = m.StopsResponse.from_dict(env["response"]["body"])
    assert len(parsed.stops) >= 5
    descriptions = {stop.description for stop in parsed.stops}
    assert "Clapham Junction" in descriptions
    assert "London Waterloo" in descriptions


def test_fixture_location_lineup_parses() -> None:
    env = _load_fixture("location_clphmjn.json")
    parsed = m.NetworkRailLocationLineUpResponse.from_dict(env["response"]["body"])
    assert parsed.system_status is not None
    assert parsed.system_status.realtime_network_rail == m.RealtimeNetworkRailStatus.OK
    assert len(parsed.services) == 3
    first = parsed.services[0]
    assert first.schedule_metadata is not None
    assert first.schedule_metadata.train_reporting_identity == "1L40"
    assert first.temporal_data is not None
    assert first.temporal_data.status == m.LocationStatus.AT_PLATFORM
    assert first.location_metadata is not None
    assert first.location_metadata.platform is not None
    assert first.location_metadata.platform.actual == "5"
    # The third service is cancelled.
    third = parsed.services[2]
    assert third.temporal_data is not None
    assert third.temporal_data.arrival is not None
    assert third.temporal_data.arrival.is_cancelled is True


def test_fixture_service_detail_parses() -> None:
    env = _load_fixture("service_1L40_2026-06-18.json")
    parsed = m.NetworkRailServiceDetail.from_dict(env["response"]["body"])
    assert parsed.schedule_metadata is not None
    assert parsed.schedule_metadata.train_reporting_identity == "1L40"
    assert parsed.schedule_metadata.stp_indicator == m.StpIndicator.WTT
    assert len(parsed.locations) == 3
    # Middle location is Clapham Junction with status AT_PLATFORM.
    clapham = parsed.locations[1]
    assert clapham.location is not None
    assert clapham.location.description == "Clapham Junction"
    assert clapham.temporal_data is not None
    assert clapham.temporal_data.status == m.LocationStatus.AT_PLATFORM
    # Allocations + KYT populated.
    assert len(parsed.allocation_data) == 1
    alloc = parsed.allocation_data[0]
    assert alloc.leading_class == "444"
    assert alloc.passenger_vehicles == 10
    assert alloc.know_your_train_data is not None
    common = alloc.know_your_train_data.common_facilities
    assert common is not None
    assert "wifi" in common.facilities


def test_fixture_service_not_found_shape() -> None:
    env = _load_fixture("service_not_found.json")
    assert env["response"]["status"] == 404


def test_fixture_429_shape() -> None:
    env = _load_fixture("api_info_429_rate_limited.json")
    assert env["response"]["status"] == 429
    headers = env["response"]["headers"]
    assert headers["retry-after"] == "30"


@pytest.mark.parametrize("fixture_name", list(_FIXTURE_DIR.glob("*.json")))
def test_all_fixtures_are_valid_envelopes(fixture_name: Path) -> None:
    """Every fixture file is a valid envelope with request + response."""
    env = json.loads(fixture_name.read_text())
    assert "request" in env
    assert "method" in env["request"]
    assert "path" in env["request"]
    assert "response" in env
    assert "status" in env["response"]
    assert "headers" in env["response"]
    assert "body" in env["response"]
    # Authorisation headers must never appear unredacted in a fixture.
    for key in env["response"]["headers"]:
        assert key.lower() not in {"authorization", "cookie", "set-cookie"}
