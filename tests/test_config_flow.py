"""Tests for the Realtime Trains config flow and subentry flows.

Requires Home Assistant (CI environment). Skips entirely otherwise.
"""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.realtime_trains.const import CONF_TOKEN, DOMAIN
from custom_components.realtime_trains.models import ApiInfo

# --- Config account flow ----------------------------------------------------


async def test_user_flow_creates_entry_with_token(hass: HomeAssistant) -> None:
    """The user step creates a config entry when the token is valid."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(
            "custom_components.realtime_trains.api.RealtimeTrainsApi.async_get_info",
            new_callable=AsyncMock,
            return_value=ApiInfo(api_version="2026-04-09"),
        ),
        patch(
            "custom_components.realtime_trains.api.RealtimeTrainsApi.async_get_stops",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_TOKEN: "valid_token"},  # noqa: S106
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Realtime Trains"
    assert result["data"][CONF_TOKEN] == "valid_token"


async def test_user_flow_empty_token_shows_error(hass: HomeAssistant) -> None:
    """An empty token shows a form error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_TOKEN: ""},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "errors" in result


async def test_user_flow_invalid_token_shows_auth_error(
    hass: HomeAssistant,
) -> None:
    """An invalid token shows the invalid_auth error."""
    from custom_components.realtime_trains.api import RttAuthError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with patch(
        "custom_components.realtime_trains.api.RealtimeTrainsApi.async_get_info",
        new_callable=AsyncMock,
        side_effect=RttAuthError("bad token"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_TOKEN: "bad_token"},  # noqa: S106
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] is not None
    assert "invalid_auth" in result["errors"]


async def test_user_flow_connection_error_shows_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """A connection error shows the cannot_connect error."""
    from custom_components.realtime_trains.api import RttConnectionError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with patch(
        "custom_components.realtime_trains.api.RealtimeTrainsApi.async_get_info",
        new_callable=AsyncMock,
        side_effect=RttConnectionError("timeout"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_TOKEN: "some_token"},  # noqa: S106
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] is not None
    assert "cannot_connect" in result["errors"]
