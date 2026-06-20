"""Tests for the Realtime Trains coordinators (board + service tracker).

Requires Home Assistant to be importable (CI environment or local HA
core checkout). Skips entirely otherwise.
"""

from datetime import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.realtime_trains.api import (
    RttAuthError,
    RttConnectionError,
    RttNotFoundError,
)
from custom_components.realtime_trains.const import (
    SUBENTRY_TYPE_DEPARTURE_BOARD,
    SUBENTRY_TYPE_SERVICE_TRACKER,
)
from custom_components.realtime_trains.coordinator import (
    BoardData,
    DepartureSlot,
    RealtimeTrainsAccountCoordinator,
    RealtimeTrainsBoardCoordinator,
    RealtimeTrainsServiceTrackerCoordinator,
    ServiceTrackerData,
    _slot_from_lineup,
    board_display_name,
)
from custom_components.realtime_trains.models import (
    NetworkRailLocationLineUp,
    NetworkRailLocationLineUpResponse,
    NetworkRailServiceDetail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    envelope = json.loads((FIXTURES / name).read_text())
    return envelope["response"]["body"]


# --- Fixtures ---------------------------------------------------------------


def _make_config_entry(hass: HomeAssistant) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"token": "test_token"}  # noqa: S106
    entry.subentries = {}
    entry.runtime_data = None
    return entry


def _make_subentry(subentry_type: str, data: dict) -> MagicMock:
    sub = MagicMock()
    sub.subentry_type = subentry_type
    sub.data = data
    return sub


def test_board_display_name_folds_in_direction() -> None:
    """The direction filter differentiates boards for the same station."""
    assert board_display_name("Station A") == "Station A"
    assert (
        board_display_name("Station A", filter_to="Station B")
        == "Station A → Station B"
    )
    assert (
        board_display_name("Station A", filter_from="Station C")
        == "Station A ← Station C"
    )
    assert (
        board_display_name("Station A", "Station C", "Station B")
        == "Station A: Station C → Station B"
    )
    assert board_display_name(None) == "Board"


# --- _slot_from_lineup ------------------------------------------------------


def test_slot_from_lineup_extracts_key_fields(hass: HomeAssistant) -> None:
    """_slot_from_lineup reduces a NetworkRailLocationLineUp to DepartureSlot."""
    body = _load_fixture("location_clphmjn.json")
    response = NetworkRailLocationLineUpResponse.from_dict(body)
    assert response.services
    svc = response.services[0]
    assert isinstance(svc, NetworkRailLocationLineUp)

    slot = _slot_from_lineup(svc)

    assert isinstance(slot, DepartureSlot)
    assert slot.headcode == "1L40"
    assert slot.platform_planned == "3"
    assert slot.operator_code == "SW"
    assert slot.operator_name == "South Western Railway"


def test_slot_from_lineup_handles_missing_fields(hass: HomeAssistant) -> None:
    """Missing optional fields produce None, not exceptions."""
    svc = NetworkRailLocationLineUp.from_dict({})
    slot = _slot_from_lineup(svc)
    assert slot.headcode is None
    assert slot.platform_planned is None
    assert slot.delay is None


# --- Board coordinator ------------------------------------------------------


async def test_board_coordinator_returns_board_data(hass: HomeAssistant) -> None:
    """Board coordinator produces BoardData with departure slots from API response."""
    body = _load_fixture("location_clphmjn.json")
    mock_response = NetworkRailLocationLineUpResponse.from_dict(body)

    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.api = MagicMock()
    account.serialise = AsyncMock(return_value=mock_response)

    subentry = _make_subentry(
        SUBENTRY_TYPE_DEPARTURE_BOARD,
        {
            "station": "CLPHMJN",
            "station_description": "Clapham Junction",
            "slot_count": 3,
            "time_window": 60,
            "polling_interval": 90,
            "namespace": "gb-nr",
        },
    )

    coordinator = RealtimeTrainsBoardCoordinator(hass, entry, "sub1", subentry, account)
    data = await coordinator._async_update_data()

    assert isinstance(data, BoardData)
    assert data.station_code == "CLPHMJN"
    assert data.station_description == "Clapham Junction"
    assert len(data.departures) <= 3
    if data.departures:
        assert data.departures[0].headcode == "1L40"
        assert data.next_delay == data.departures[0].delay


async def test_board_coordinator_truncates_to_slot_count(
    hass: HomeAssistant,
) -> None:
    """Board coordinator honours the configured slot_count."""
    body = _load_fixture("location_clphmjn.json")
    mock_response = NetworkRailLocationLineUpResponse.from_dict(body)

    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.api = MagicMock()
    account.serialise = AsyncMock(return_value=mock_response)

    subentry = _make_subentry(
        SUBENTRY_TYPE_DEPARTURE_BOARD,
        {
            "station": "CLPHMJN",
            "slot_count": 1,
            "time_window": 60,
            "polling_interval": 90,
            "namespace": "gb-nr",
        },
    )

    coordinator = RealtimeTrainsBoardCoordinator(hass, entry, "sub1", subentry, account)
    data = await coordinator._async_update_data()
    assert len(data.departures) <= 1


async def test_board_coordinator_auth_error_raises_config_entry_error(
    hass: HomeAssistant,
) -> None:
    """RttAuthError propagates as ConfigEntryError."""
    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.serialise = AsyncMock(side_effect=RttAuthError("bad token"))

    subentry = _make_subentry(
        SUBENTRY_TYPE_DEPARTURE_BOARD,
        {"station": "CLPHMJN", "slot_count": 3, "namespace": "gb-nr"},
    )
    coordinator = RealtimeTrainsBoardCoordinator(hass, entry, "sub1", subentry, account)
    with pytest.raises(ConfigEntryError):
        await coordinator._async_update_data()


async def test_board_coordinator_connection_error_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """RttConnectionError surfaces as UpdateFailed (retryable)."""
    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.serialise = AsyncMock(side_effect=RttConnectionError("timeout"))

    subentry = _make_subentry(
        SUBENTRY_TYPE_DEPARTURE_BOARD,
        {"station": "CLPHMJN", "slot_count": 3, "namespace": "gb-nr"},
    )
    coordinator = RealtimeTrainsBoardCoordinator(hass, entry, "sub1", subentry, account)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --- Service tracker coordinator -------------------------------------------


async def test_service_tracker_coordinator_returns_service_data(
    hass: HomeAssistant,
) -> None:
    """Service tracker coordinator extracts data from service detail."""
    body = _load_fixture("service_1L40_2026-06-18.json")
    mock_service = NetworkRailServiceDetail.from_dict(body)

    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.api = MagicMock()
    account.serialise = AsyncMock(return_value=mock_service)

    subentry = _make_subentry(
        SUBENTRY_TYPE_SERVICE_TRACKER,
        {
            "headcode": "1L40",
            "date": "2026-06-18",
            "unique_identity": None,
            "namespace": "gb-nr",
        },
    )

    coordinator = RealtimeTrainsServiceTrackerCoordinator(
        hass, entry, "sub2", subentry, account
    )
    data = await coordinator._async_update_data()

    assert isinstance(data, ServiceTrackerData)
    assert data.headcode == "1L40"
    assert data.unique_identity == "gb-nr:W00001:2026-06-18"
    assert data.departure is not None
    assert isinstance(data.departure, datetime)
    assert data.formation is not None
    assert len(data.formation) == 1
    assert data.formation[0].leading_class is not None


async def test_service_tracker_coordinator_not_found_returns_empty(
    hass: HomeAssistant,
) -> None:
    """RttNotFoundError surfaces as UpdateFailed."""
    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.serialise = AsyncMock(side_effect=RttNotFoundError("not found"))

    subentry = _make_subentry(
        SUBENTRY_TYPE_SERVICE_TRACKER,
        {"headcode": "XXXX", "date": "2026-01-01", "namespace": "gb-nr"},
    )
    coordinator = RealtimeTrainsServiceTrackerCoordinator(
        hass, entry, "sub2", subentry, account
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_service_tracker_cadence_adapts_to_state(
    hass: HomeAssistant,
) -> None:
    """Polling cadence switches between scheduled/in_run/terminal."""
    entry = _make_config_entry(hass)
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)

    subentry = _make_subentry(
        SUBENTRY_TYPE_SERVICE_TRACKER,
        {"headcode": "1L40", "date": "2026-06-18", "namespace": "gb-nr"},
    )
    coordinator = RealtimeTrainsServiceTrackerCoordinator(
        hass, entry, "sub2", subentry, account
    )

    scheduled = coordinator.update_interval

    coordinator._update_interval_for_state(status=None, is_cancelled=None)
    assert coordinator.update_interval == scheduled

    coordinator._update_interval_for_state(status=None, is_cancelled=False)
    assert coordinator.update_interval == scheduled

    from custom_components.realtime_trains.models import LocationStatus

    coordinator._update_interval_for_state(
        status=LocationStatus.DEPART_READY, is_cancelled=False
    )
    in_run = coordinator.update_interval
    assert in_run < scheduled

    coordinator._update_interval_for_state(status=None, is_cancelled=True)
    assert coordinator.update_interval > in_run


# --- Account coordinator ----------------------------------------------------


async def test_account_coordinator_refreshes_api_info(hass: HomeAssistant) -> None:
    """Account coordinator fetches /api/info; stops come from the cache."""
    from custom_components.realtime_trains.models import ApiInfo, Stop

    entry = _make_config_entry(hass)
    mock_api = MagicMock()
    mock_api.async_get_info = AsyncMock(return_value=ApiInfo(api_version="2026-04-09"))
    stops_body = _load_fixture("stops.json")
    mock_api.async_get_stops = AsyncMock(
        return_value=[Stop.from_dict(s) for s in stops_body.get("stops", [])]
    )

    coordinator = RealtimeTrainsAccountCoordinator(hass, entry, mock_api)

    # ``_async_update_data`` only polls /api/info and reads the stops cache;
    # the stops list is populated lazily via ``refresh_stops``.
    stops = await coordinator.refresh_stops()
    assert len(stops) > 0

    data = await coordinator._async_update_data()
    assert data.api_info is not None
    assert data.api_info.api_version == "2026-04-09"
    assert len(data.stops) > 0


async def test_account_coordinator_auth_error_raises(
    hass: HomeAssistant,
) -> None:
    """Auth failure during account refresh raises ConfigEntryError."""
    entry = _make_config_entry(hass)
    mock_api = MagicMock()
    mock_api.async_get_info = AsyncMock(side_effect=RttAuthError("bad"))
    mock_api.async_get_stops = AsyncMock(return_value=[])

    coordinator = RealtimeTrainsAccountCoordinator(hass, entry, mock_api)
    with pytest.raises(ConfigEntryError):
        await coordinator._async_update_data()
