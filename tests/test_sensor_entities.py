"""Tests for the Realtime Trains sensor entities.

Requires Home Assistant (CI environment). Skips entirely otherwise.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")
from homeassistant.core import HomeAssistant

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
)
from custom_components.realtime_trains.models import (
    LocationStatus,
    NetworkRailLocationLineUpResponse,
)
from custom_components.realtime_trains.sensor import (
    RealtimeTrainsAccountBinarySensor,
    RealtimeTrainsAccountSensor,
    RealtimeTrainsBoardBinarySensor,
    RealtimeTrainsBoardSensor,
    RealtimeTrainsServiceSensor,
    _service_state_enum,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    envelope = json.loads((FIXTURES / name).read_text())
    return envelope["response"]["body"]


# --- _service_state_enum ----------------------------------------------------


def test_service_state_enum_cancelled() -> None:
    data = ServiceTrackerData(
        unique_identity=None,
        headcode=None,
        departure=None,
        arrival=None,
        live_status=None,
        delay=None,
        is_cancelled=True,
        display_as=None,
        formation=None,
        know_your_train=None,
    )
    assert _service_state_enum(data) == "cancelled"


def test_service_state_enum_scheduled() -> None:
    data = ServiceTrackerData(
        unique_identity=None,
        headcode=None,
        departure=None,
        arrival=None,
        live_status=None,
        delay=None,
        is_cancelled=None,
        display_as=None,
        formation=None,
        know_your_train=None,
    )
    assert _service_state_enum(data) == "scheduled"


def test_service_state_enum_in_run() -> None:
    data = ServiceTrackerData(
        unique_identity=None,
        headcode=None,
        departure=None,
        arrival=None,
        live_status=LocationStatus.DEPART_READY,
        delay=None,
        is_cancelled=False,
        display_as=None,
        formation=None,
        know_your_train=None,
    )
    assert _service_state_enum(data) == "in_run"


def test_service_state_enum_completed_past_arrival() -> None:
    past = datetime(2020, 1, 1, tzinfo=UTC)
    data = ServiceTrackerData(
        unique_identity=None,
        headcode=None,
        departure=past,
        arrival=past,
        live_status=None,
        delay=None,
        is_cancelled=False,
        display_as=None,
        formation=None,
        know_your_train=None,
    )
    assert _service_state_enum(data) == "completed"


# --- Board sensor entities --------------------------------------------------


def _make_board_coordinator(
    hass: HomeAssistant, fixture_name: str = "location_clphmjn.json"
) -> RealtimeTrainsBoardCoordinator:
    body = _load_fixture(fixture_name)
    response = NetworkRailLocationLineUpResponse.from_dict(body)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_DEPARTURE_BOARD
    subentry.data = {
        "station": "CLPHMJN",
        "station_description": "Clapham Junction",
        "slot_count": 3,
        "time_window": 60,
        "polling_interval": 90,
        "namespace": "gb-nr",
    }
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.api = MagicMock()
    account.serialise = AsyncMock(return_value=response)
    coordinator = RealtimeTrainsBoardCoordinator(hass, entry, "sub1", subentry, account)
    coordinator.data = BoardData(
        departures=[
            DepartureSlot(
                headcode="1L40",
                operator_code="SW",
                operator_name="South Western Railway",
                origin="London Waterloo",
                destination="Woking",
                platform_planned="3",
                platform_actual="3",
                delay=3,
                scheduled_departure=datetime(2026, 6, 18, 8, 17, tzinfo=UTC),
                realtime_departure=datetime(2026, 6, 18, 8, 20, tzinfo=UTC),
                live_status=LocationStatus.DEPART_READY,
                display_as=None,
                is_cancelled=False,
                cancellation_reason=None,
                delay_reason=None,
                stp_indicator="WTT",
                unique_identity="gb-nr:W00001:2026-06-18",
                namespace="gb-nr",
                mode="TRAIN",
                in_passenger_service=True,
                onboard_facilities=None,
                stock_branding="South Western Railway",
            )
        ],
        next_delay=3,
        any_cancellations=False,
        platform_changed=False,
        live_status=LocationStatus.DEPART_READY,
        station_description="Clapham Junction",
        station_code="CLPHMJN",
        namespace="gb-nr",
    )
    return coordinator


def test_board_sensor_next_departure_native_value(hass: HomeAssistant) -> None:
    """The next_departure sensor (slot 0) returns the realtime departure time."""
    coordinator = _make_board_coordinator(hass)
    from custom_components.realtime_trains.sensor import _make_slot_description

    desc = _make_slot_description(0)
    entity = RealtimeTrainsBoardSensor(coordinator, "sub1", desc)
    value = entity.native_value
    assert value == datetime(2026, 6, 18, 8, 20, tzinfo=UTC)


def test_board_sensor_delay(hass: HomeAssistant) -> None:
    """The delay sensor reads next_delay from BoardData."""
    coordinator = _make_board_coordinator(hass)
    from custom_components.realtime_trains.sensor import BOARD_BASE_SENSOR_DESCRIPTIONS

    delay_desc = next(d for d in BOARD_BASE_SENSOR_DESCRIPTIONS if d.key == "delay")
    entity = RealtimeTrainsBoardSensor(coordinator, "sub1", delay_desc)
    assert entity.native_value == 3


def test_board_sensor_next_departure_attributes(hass: HomeAssistant) -> None:
    """The next_departure entity exposes headcode/operator/platform in attrs."""
    coordinator = _make_board_coordinator(hass)
    from custom_components.realtime_trains.sensor import _make_slot_description

    desc = _make_slot_description(0)
    entity = RealtimeTrainsBoardSensor(coordinator, "sub1", desc)
    attrs = entity.extra_state_attributes
    assert attrs is not None
    assert attrs["headcode"] == "1L40"
    assert "London Waterloo" in str(attrs.get("origin", ""))
    assert attrs["platform_planned"] == "3"
    assert "SW" in str(attrs.get("operator", ""))


def test_board_binary_sensor_cancellations(hass: HomeAssistant) -> None:
    """The cancellations binary sensor reads any_cancellations."""
    coordinator = _make_board_coordinator(hass)
    from custom_components.realtime_trains.sensor import BOARD_BINARY_DESCRIPTIONS

    cancel_desc = next(d for d in BOARD_BINARY_DESCRIPTIONS if d.key == "cancellations")
    entity = RealtimeTrainsBoardBinarySensor(coordinator, "sub1", cancel_desc)
    assert entity.is_on is False

    coordinator.data = BoardData(
        departures=[],
        next_delay=None,
        any_cancellations=True,
        platform_changed=False,
        live_status=None,
        station_description="Test",
        station_code="TST",
        namespace="gb-nr",
    )
    assert entity.is_on is True


def test_board_sensor_unique_id(hass: HomeAssistant) -> None:
    """Board sensor unique_id encodes subentry:namespace:station:key[:slot]."""
    coordinator = _make_board_coordinator(hass)
    from custom_components.realtime_trains.sensor import _make_slot_description

    desc_slot0 = _make_slot_description(0)
    desc_slot1 = _make_slot_description(1)
    entity0 = RealtimeTrainsBoardSensor(coordinator, "sub1", desc_slot0)
    entity1 = RealtimeTrainsBoardSensor(coordinator, "sub1", desc_slot1)
    # Subentry-scoped so two boards for the same station don't collide.
    assert entity0.unique_id == "sub1:gb-nr:CLPHMJN:departure"
    assert entity1.unique_id == "sub1:gb-nr:CLPHMJN:departure:1"


# --- Service sensor entities -----------------------------------------------


def _make_service_coordinator(
    hass: HomeAssistant,
) -> RealtimeTrainsServiceTrackerCoordinator:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SERVICE_TRACKER
    subentry.data = {
        "headcode": "1L40",
        "date": "2026-06-18",
        "unique_identity": None,
        "namespace": "gb-nr",
    }
    account = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    account.api = MagicMock()
    coordinator = RealtimeTrainsServiceTrackerCoordinator(
        hass, entry, "sub2", subentry, account
    )
    coordinator.data = ServiceTrackerData(
        unique_identity="gb-nr:W00001:2026-06-18",
        headcode="1L40",
        departure=datetime(2026, 6, 18, 8, 17, tzinfo=UTC),
        arrival=datetime(2026, 6, 18, 9, 0, tzinfo=UTC),
        live_status=LocationStatus.DEPART_READY,
        delay=3,
        is_cancelled=False,
        display_as=None,
        formation=None,
        know_your_train=None,
    )
    return coordinator


def test_service_sensor_unique_id(hass: HomeAssistant) -> None:
    """Service sensor unique_id encodes namespace:service:headcode:key."""
    coordinator = _make_service_coordinator(hass)
    from custom_components.realtime_trains.sensor import SERVICE_SENSOR_DESCRIPTIONS

    departure_desc = next(
        d for d in SERVICE_SENSOR_DESCRIPTIONS if d.key == "departure"
    )
    entity = RealtimeTrainsServiceSensor(coordinator, "sub2", departure_desc)
    assert entity.unique_id == "sub2:gb-nr:service:1L40:departure"


def test_migrate_subentry_unique_id() -> None:
    """Old unscoped IDs gain a subentry prefix; others are left alone."""
    from types import SimpleNamespace

    from custom_components.realtime_trains import _migrate_subentry_unique_id

    # Board entity under a subentry -> prefixed with the subentry id.
    board = SimpleNamespace(config_subentry_id="sub1", unique_id="gb-nr:ABC:departure")
    assert _migrate_subentry_unique_id(board) == {
        "new_unique_id": "sub1:gb-nr:ABC:departure"
    }

    # Already migrated -> no change (idempotent).
    migrated = SimpleNamespace(
        config_subentry_id="sub1", unique_id="sub1:gb-nr:ABC:departure"
    )
    assert _migrate_subentry_unique_id(migrated) is None

    # Account-level entity (no subentry) -> already unique, untouched.
    account = SimpleNamespace(
        config_subentry_id=None, unique_id="account:entry:api_version"
    )
    assert _migrate_subentry_unique_id(account) is None


def test_service_sensor_live_status(hass: HomeAssistant) -> None:
    """Live status sensor returns 'in_run' when DEPART_READY."""
    coordinator = _make_service_coordinator(hass)
    from custom_components.realtime_trains.sensor import SERVICE_SENSOR_DESCRIPTIONS

    status_desc = next(d for d in SERVICE_SENSOR_DESCRIPTIONS if d.key == "live_status")
    entity = RealtimeTrainsServiceSensor(coordinator, "sub2", status_desc)
    assert entity.native_value == "in_run"


def test_service_sensor_delay(hass: HomeAssistant) -> None:
    """Delay sensor returns the delay minutes."""
    coordinator = _make_service_coordinator(hass)
    from custom_components.realtime_trains.sensor import SERVICE_SENSOR_DESCRIPTIONS

    delay_desc = next(d for d in SERVICE_SENSOR_DESCRIPTIONS if d.key == "delay")
    entity = RealtimeTrainsServiceSensor(coordinator, "sub2", delay_desc)
    assert entity.native_value == 3


# --- Account sensor entities ------------------------------------------------


def _make_account_coordinator(
    hass: HomeAssistant,
) -> RealtimeTrainsAccountCoordinator:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"token": "t"}  # noqa: S106
    from custom_components.realtime_trains.models import (
        ApiInfo,
        Credentials,
        RateLimitEntry,
        RateLimitSnapshot,
    )

    api = MagicMock()
    api.rate_limits = RateLimitSnapshot(
        minute=RateLimitEntry(limit=100, remaining=80),
        hour=RateLimitEntry(limit=1000, remaining=900),
        day=RateLimitEntry(limit=10000, remaining=9000),
        week=RateLimitEntry(limit=100000, remaining=90000),
        retry_after=None,
    )
    coordinator = MagicMock(spec=RealtimeTrainsAccountCoordinator)
    coordinator.data = MagicMock()
    coordinator.data.api_info = ApiInfo(
        api_version="2026-04-09",
        credentials=Credentials(
            entitlements=["allowDetailed"],
            history_restriction=False,
            history_restrict_to_days=None,
            namespace_restriction=False,
            namespaces_available=["gb-nr"],
        ),
    )
    coordinator.api = api
    return coordinator


def test_account_sensor_rate_limit_minute(hass: HomeAssistant) -> None:
    """Rate limit minute sensor reads from the coordinator's rate_limits."""
    coordinator = _make_account_coordinator(hass)
    from custom_components.realtime_trains.sensor import ACCOUNT_SENSOR_DESCRIPTIONS

    desc = next(d for d in ACCOUNT_SENSOR_DESCRIPTIONS if d.key == "rate_limit_minute")
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    entity = RealtimeTrainsAccountSensor(coordinator, config_entry, desc)
    assert entity.native_value == 100


def test_account_sensor_api_version(hass: HomeAssistant) -> None:
    """API version sensor returns the version string from /api/info."""
    coordinator = _make_account_coordinator(hass)
    from custom_components.realtime_trains.sensor import ACCOUNT_SENSOR_DESCRIPTIONS

    desc = next(d for d in ACCOUNT_SENSOR_DESCRIPTIONS if d.key == "api_version")
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    entity = RealtimeTrainsAccountSensor(coordinator, config_entry, desc)
    assert entity.native_value == "2026-04-09"


def test_account_binary_sensor_history_restricted(hass: HomeAssistant) -> None:
    """History-restricted binary sensor reflects credentials flag."""
    coordinator = _make_account_coordinator(hass)
    from custom_components.realtime_trains.sensor import ACCOUNT_BINARY_DESCRIPTIONS

    desc = next(d for d in ACCOUNT_BINARY_DESCRIPTIONS if d.key == "history_restricted")
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    entity = RealtimeTrainsAccountBinarySensor(coordinator, config_entry, desc)
    assert entity.is_on is False
