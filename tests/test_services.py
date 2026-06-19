"""Tests for the Realtime Trains service handlers.

Requires Home Assistant (CI environment). Skips entirely otherwise.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import ServiceValidationError

from custom_components.realtime_trains.api import (
    RttAuthError,
    RttConnectionError,
    RttNotFoundError,
    RttRateLimitError,
)
from custom_components.realtime_trains.const import DOMAIN
from custom_components.realtime_trains.models import (
    NetworkRailLocationLineUpResponse,
    Stop,
)
from custom_components.realtime_trains.services import (
    _coerce_dt,
    _iso,
    _lineup_to_dict,
    _raise_for,
    _stop_matches,
    _stop_to_dict,
    _strip_none,
    _subentry_id_from_device,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    envelope = json.loads((FIXTURES / name).read_text())
    return envelope["response"]["body"]


# --- _coerce_dt -------------------------------------------------------------


def test_coerce_dt_none_passthrough() -> None:
    assert _coerce_dt(None) is None
    assert _coerce_dt("") is None


def test_coerce_dt_datetime_passthrough() -> None:
    dt = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    assert _coerce_dt(dt) is dt


def test_coerce_dt_iso_string() -> None:
    result = _coerce_dt("2026-06-18T12:00:00+00:00")
    assert result == datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


def test_coerce_dt_bad_string_raises() -> None:
    with pytest.raises(ServiceValidationError):
        _coerce_dt("not-a-date")


# --- _iso / _strip_none -----------------------------------------------------


def test_iso_formats_with_timezone() -> None:
    dt = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    assert _iso(dt) == "2026-06-18T12:00:00+00:00"


def test_iso_naive_assumes_utc() -> None:
    dt = datetime(2026, 6, 18, 12, 0)
    result = _iso(dt)
    assert result is not None
    assert "+00:00" in result


def test_iso_none_returns_none() -> None:
    assert _iso(None) is None


def test_strip_none_removes_falsy_values() -> None:
    assert _strip_none({"a": 1, "b": None, "c": 0, "d": ""}) == {
        "a": 1,
        "c": 0,
        "d": "",
    }


# --- _stop_matches -----------------------------------------------------------


def test_stop_matches_description() -> None:
    stop = Stop(
        namespace="gb-nr",
        description="Clapham Junction",
        short_code="CLP",
        unique_identity="gb-nr:CLPHMJN",
    )
    assert _stop_matches(stop, "clapham")
    assert _stop_matches(stop, "CLP")
    assert _stop_matches(stop, "clphmjn")
    assert not _stop_matches(stop, "wat")


def test_stop_to_dict() -> None:
    stop = Stop(
        namespace="gb-nr",
        description="Woking",
        short_code="WOK",
        unique_identity="gb-nr:WOK",
    )
    d = _stop_to_dict(stop)
    assert d == {
        "namespace": "gb-nr",
        "description": "Woking",
        "short_code": "WOK",
        "unique_identity": "gb-nr:WOK",
    }


# --- _lineup_to_dict ---------------------------------------------------------


def test_lineup_to_dict_extracts_fields() -> None:
    """_lineup_to_dict serialises a line-up service into the documented dict shape."""
    body = _load_fixture("location_clphmjn.json")
    response = NetworkRailLocationLineUpResponse.from_dict(body)
    assert response.services
    result = _lineup_to_dict(response.services[0])
    assert result["headcode"] == "1L40"
    assert result["platform_planned"] == "3"
    assert result["origin"] == "London Waterloo"
    assert result["destination"] == "Woking"
    assert result["operator_code"] == "SW"
    assert result["operator_name"] == "South Western Railway"
    assert "departure" in result


def test_lineup_to_dict_empty_service() -> None:
    """An empty line-up entry produces an empty (stripped) dict."""
    from custom_components.realtime_trains.models import NetworkRailLocationLineUp

    result = _lineup_to_dict(NetworkRailLocationLineUp.from_dict({}))
    assert result == {}


# --- _subentry_id_from_device -------------------------------------------------


def test_subentry_id_from_device_board() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "board:abc123")}
    assert _subentry_id_from_device(device) == "abc123"


def test_subentry_id_from_device_service() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "service:xyz789")}
    assert _subentry_id_from_device(device) == "xyz789"


def test_subentry_id_from_device_unknown() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "other:123")}
    assert _subentry_id_from_device(device) is None


def test_subentry_id_from_device_other_domain() -> None:
    device = MagicMock()
    device.identifiers = {("other_domain", "board:123")}
    assert _subentry_id_from_device(device) is None


# --- _raise_for ---------------------------------------------------------------


def test_raise_for_auth_error() -> None:
    with pytest.raises(ServiceValidationError) as exc_info:
        _raise_for(RttAuthError("bad token"))
    assert exc_info.value.translation_key == "invalid_auth"


def test_raise_for_rate_limit_error() -> None:
    with pytest.raises(ServiceValidationError) as exc_info:
        _raise_for(RttRateLimitError("slow down"))
    assert exc_info.value.translation_key == "rate_limited"


def test_raise_for_not_found_error() -> None:
    with pytest.raises(ServiceValidationError) as exc_info:
        _raise_for(RttNotFoundError("missing"))
    assert exc_info.value.translation_key == "not_found"


def test_raise_for_connection_error() -> None:
    with pytest.raises(ServiceValidationError) as exc_info:
        _raise_for(RttConnectionError("timeout"))
    assert exc_info.value.translation_key == "cannot_connect"


def test_raise_for_generic_exception() -> None:
    with pytest.raises(ServiceValidationError) as exc_info:
        _raise_for(ValueError("boom"))
    assert exc_info.value.translation_key == "unknown"
