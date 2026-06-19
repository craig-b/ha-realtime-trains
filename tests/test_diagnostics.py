"""Tests for the Realtime Trains diagnostics platform.

Requires Home Assistant (CI environment). Skips entirely otherwise.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.const import CONF_TOKEN

from custom_components.realtime_trains.const import DOMAIN
from custom_components.realtime_trains.diagnostics import (
    TO_REDACT,
    _redact,
    _stringify_exception,
    _subentry_id_from_device,
)

# --- _redact -----------------------------------------------------------------


def test_redact_replaces_token_value() -> None:
    payload = {"token": "secret", "other": "visible"}
    result = _redact(payload)
    assert result["token"] == "**REDACTED**"
    assert result["other"] == "visible"


def test_redact_nested_dict() -> None:
    payload = {"outer": {"inner": {"Authorization": "Bearer abc"}}}
    result = _redact(payload)
    assert result["outer"]["inner"]["Authorization"] == "**REDACTED**"


def test_redact_list_of_dicts() -> None:
    payload = [{"Cookie": "session=123"}, {"data": "ok"}]
    result = _redact(payload)
    assert result[0]["Cookie"] == "**REDACTED**"
    assert result[1]["data"] == "ok"


def test_redact_passes_through_scalars() -> None:
    assert _redact(42) == 42
    assert _redact("hello") == "hello"
    assert _redact(None) is None


def test_redact_all_known_keys() -> None:
    payload = dict.fromkeys(TO_REDACT, "value")
    result = _redact(payload)
    for key in TO_REDACT:
        assert result[key] == "**REDACTED**"


def test_redact_preserves_unrelated_keys() -> None:
    payload = {"rate_limit": 100, "token": "abc", "remaining": 80}
    result = _redact(payload)
    assert result["rate_limit"] == 100
    assert result["remaining"] == 80
    assert result["token"] == "**REDACTED**"


# --- _stringify_exception ----------------------------------------------------


def test_stringify_exception_none() -> None:
    assert _stringify_exception(None) is None


def test_stringify_exception_with_message() -> None:
    exc = ValueError("something broke")
    result = _stringify_exception(exc)
    assert result is not None
    assert "ValueError" in result
    assert "something broke" in result


def test_stringify_exception_without_message() -> None:
    exc = RuntimeError()
    result = _stringify_exception(exc)
    assert result is not None
    assert "RuntimeError" in result


# --- _subentry_id_from_device ------------------------------------------------


def test_subentry_id_board() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "board:sub123")}
    assert _subentry_id_from_device(device) == "sub123"


def test_subentry_id_service() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "service:track456")}
    assert _subentry_id_from_device(device) == "track456"


def test_subentry_id_no_match() -> None:
    device = MagicMock()
    device.identifiers = {(DOMAIN, "unknown:789")}
    assert _subentry_id_from_device(device) is None


# --- TO_REDACT set -----------------------------------------------------------


def test_token_is_in_redact_set() -> None:
    """Ensure CONF_TOKEN is covered."""
    assert CONF_TOKEN in TO_REDACT
    assert "Authorization" in TO_REDACT
    assert "Cookie" in TO_REDACT
    assert "Set-Cookie" in TO_REDACT
    assert "accessToken" in TO_REDACT
    assert "refreshToken" in TO_REDACT
