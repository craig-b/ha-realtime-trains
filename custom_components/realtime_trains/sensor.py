"""Sensor entities for the Realtime Trains integration.

Each departure-board subentry produces a per-slot sensor tuple
(``next_departure``, ``departure_2``..``departure_N``, ``delay``,
``cancellations``, ``platform_changes``, ``live_status``) following
the entity-description model used by the Swiss public-transport
integration. Each service-tracker subentry produces ``departure``,
``arrival``, ``delay`` and ``live_status`` entities.

Unique IDs are derived from immutable API data — for boards,
``{namespace}:{station_code}:{key}``; for service trackers,
``{namespace}:{headcode_or_identity}:{key}`` — so reloading or
re-adding the same station re-attaches to the same entity history.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    BoardData,
    RealtimeTrainsAccountCoordinator,
    RealtimeTrainsBoardCoordinator,
    RealtimeTrainsConfigEntry,
    RealtimeTrainsRuntimeData,
    RealtimeTrainsServiceTrackerCoordinator,
    ServiceTrackerData,
)
from .models import RateLimitEntry, RateLimitSnapshot

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

MANUFACTURER = "Realtime Trains"


# --- Entity descriptions for departure boards -----------------------------


@dataclass(kw_only=True, frozen=True)
class BoardSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor on a departure board device."""

    value_fn: Callable[[BoardData, int], StateType | datetime]
    slot: int = 0


@dataclass(kw_only=True, frozen=True)
class BoardBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a binary sensor on a departure board device."""

    value_fn: Callable[[BoardData], bool]


# Per-slot sensors: next_departure, departure_2 .. departure_N.
def _slot_value(data: BoardData, slot: int) -> StateType | datetime:
    if slot >= len(data.departures):
        return None
    dept = data.departures[slot]
    # Prefer realtime actual, then forecast, then advertised.
    return dept.realtime_departure or dept.scheduled_departure or None


def _make_slot_description(slot: int) -> BoardSensorEntityDescription:
    return BoardSensorEntityDescription(
        key=f"departure_{slot}" if slot > 0 else "next_departure",
        translation_key="next_departure" if slot == 0 else f"departure_{slot}",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_slot_value,
        slot=slot,
    )


def _board_delay(data: BoardData, slot: int = 0) -> StateType | datetime:
    if slot >= len(data.departures):
        return None
    return data.departures[slot].delay


def _board_live_status(data: BoardData, slot: int = 0) -> StateType | datetime:
    if slot >= len(data.departures):
        return None
    status = data.departures[slot].live_status
    # ``LocationStatus`` is a StrEnum whose values are UPPERCASE (e.g.
    # ``"DEPART_READY"``); HA's ENUM device class stores the state verbatim,
    # so we lowercase it to keep the documented options consistent.
    return str(status).lower() if status is not None else None


# Tuple of board-entity descriptions. The slot count is dynamically
# derived per-board; entities are created per (board, slot) at setup.
# The non-slot sensors (delay, cancellations, platform_changes,
# live_status) are sourced from slot 0.
BOARD_BASE_SENSOR_DESCRIPTIONS: tuple[BoardSensorEntityDescription, ...] = (
    # slot 0 (next_departure) is always created dynamically per board
    # so the slot count matches what the user configured.
    BoardSensorEntityDescription(
        key="delay",
        translation_key="delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_board_delay,
    ),
    BoardSensorEntityDescription(
        key="live_status",
        translation_key="live_status",
        device_class=SensorDeviceClass.ENUM,
        # Mirrors the values of LocationStatus (lower-cased by
        # ``_board_live_status``). ``scheduled`` is the implicit empty-state
        # produced by the coordinator when no realtime status exists.
        options=[
            "approaching",
            "arriving",
            "at_platform",
            "depart_preparing",
            "depart_ready",
            "departing",
        ],
        value_fn=_board_live_status,
    ),
)

BOARD_BINARY_DESCRIPTIONS: tuple[BoardBinarySensorEntityDescription, ...] = (
    BoardBinarySensorEntityDescription(
        key="cancellations",
        translation_key="cancellations",
        value_fn=lambda data: data.any_cancellations,
    ),
    BoardBinarySensorEntityDescription(
        key="platform_changes",
        translation_key="platform_changes",
        value_fn=lambda data: data.platform_changed,
    ),
)


# --- Entity descriptions for service trackers -----------------------------


def _service_state_enum(data: ServiceTrackerData) -> StateType:
    if data.is_cancelled is True:
        return "cancelled"
    if data.display_as is not None and str(data.display_as).upper() == "CANCELLED":
        return "cancelled"
    status = data.live_status
    if status is None:
        if data.departure is None and data.arrival is None:
            return "scheduled"
        if data.arrival is not None and data.arrival < datetime.now(
            data.arrival.tzinfo
        ):
            return "completed"
        return "unknown"
    # Platform-departure states imply the train is in run.
    return "in_run"


@dataclass(kw_only=True, frozen=True)
class ServiceSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor on a service-tracker device."""

    value_fn: Callable[[ServiceTrackerData], StateType | datetime]


SERVICE_SENSOR_DESCRIPTIONS: tuple[ServiceSensorEntityDescription, ...] = (
    ServiceSensorEntityDescription(
        key="departure",
        translation_key="service_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.departure,
    ),
    ServiceSensorEntityDescription(
        key="arrival",
        translation_key="service_arrival",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.arrival,
    ),
    ServiceSensorEntityDescription(
        key="live_status",
        translation_key="service_live_status",
        device_class=SensorDeviceClass.ENUM,
        options=["scheduled", "in_run", "completed", "cancelled", "unknown"],
        value_fn=_service_state_enum,
    ),
    ServiceSensorEntityDescription(
        key="delay",
        translation_key="service_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda data: data.delay,
    ),
)


# --- Device info --------------------------------------------------------------


def _board_device_info(
    coordinator: RealtimeTrainsBoardCoordinator, data: BoardData
) -> DeviceInfo:
    """Build device info for a per-board device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"board:{coordinator.subentry_id}")},
        name=data.station_description or "Board",
        manufacturer=MANUFACTURER,
        model="Departure board",
        entry_type=DeviceEntryType.SERVICE,
    )


def _service_device_info(
    coordinator: RealtimeTrainsServiceTrackerCoordinator, data: ServiceTrackerData
) -> DeviceInfo:
    """Build device info for a per-service-tracker device."""
    name = (
        f"{coordinator.headcode} {coordinator.departure_date}"
        if coordinator.headcode and coordinator.departure_date
        else coordinator.headcode or coordinator.unique_identity or "Service"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"service:{coordinator.subentry_id}")},
        name=name,
        manufacturer=MANUFACTURER,
        model="Service tracker",
        entry_type=DeviceEntryType.SERVICE,
    )


# --- Entity descriptions for account device --------------------------------


@dataclass(kw_only=True, frozen=True)
class AccountSensorEntityDescription(SensorEntityDescription):
    """Describes a diagnostic sensor on the account device."""

    value_fn: Callable[[RealtimeTrainsAccountCoordinator], StateType]


@dataclass(kw_only=True, frozen=True)
class AccountBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a diagnostic binary sensor on the account device."""

    value_fn: Callable[[RealtimeTrainsAccountCoordinator], bool | None]


def _rate_limit_entry(snapshot: RateLimitSnapshot, dim: str, field: str) -> int | None:
    """Pick ``limit`` or ``remaining`` from one rate-limit dimension."""
    entry: RateLimitEntry | None = getattr(snapshot, dim, None)
    if entry is None:
        return None
    return getattr(entry, field, None)


def _account_api_version(coordinator: RealtimeTrainsAccountCoordinator) -> StateType:
    if coordinator.data is None or coordinator.data.api_info is None:
        return None
    return coordinator.data.api_info.api_version


def _account_history_restricted(
    coordinator: RealtimeTrainsAccountCoordinator,
) -> bool | None:
    if coordinator.data is None or coordinator.data.api_info is None:
        return None
    return coordinator.data.api_info.credentials.history_restriction


def _account_namespace_restricted(
    coordinator: RealtimeTrainsAccountCoordinator,
) -> bool | None:
    if coordinator.data is None or coordinator.data.api_info is None:
        return None
    return coordinator.data.api_info.credentials.namespace_restriction


# Dimensions: minute / hour / day / week — each yields a limit + remaining sensor.
ACCOUNT_SENSOR_DESCRIPTIONS: tuple[AccountSensorEntityDescription, ...] = (
    tuple(
        AccountSensorEntityDescription(
            key=f"rate_limit_{dim}",
            translation_key=f"rate_limit_{dim}",
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=(
                lambda coord, dim=dim: _rate_limit_entry(
                    coord.api.rate_limits, dim, "limit"
                )
            ),
        )
        for dim in ("minute", "hour", "day", "week")
    )
    + tuple(
        AccountSensorEntityDescription(
            key=f"rate_limit_remaining_{dim}",
            translation_key=f"rate_limit_remaining_{dim}",
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=(
                lambda coord, dim=dim: _rate_limit_entry(
                    coord.api.rate_limits, dim, "remaining"
                )
            ),
        )
        for dim in ("minute", "hour", "day", "week")
    )
    + (
        AccountSensorEntityDescription(
            key="api_version",
            translation_key="api_version",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_account_api_version,
        ),
    )
)


ACCOUNT_BINARY_DESCRIPTIONS: tuple[AccountBinarySensorEntityDescription, ...] = (
    AccountBinarySensorEntityDescription(
        key="history_restricted",
        translation_key="history_restricted",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_account_history_restricted,
    ),
    AccountBinarySensorEntityDescription(
        key="namespace_restricted",
        translation_key="namespace_restricted",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_account_namespace_restricted,
    ),
)


def _account_device_info(entry: RealtimeTrainsConfigEntry) -> DeviceInfo:
    """Build device info tying account-diagnostic entities to one logical device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"account:{entry.entry_id}")},
        name="Realtime Trains",
        manufacturer=MANUFACTURER,
        model="Account",
        entry_type=DeviceEntryType.SERVICE,
    )


# --- Setup --------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RealtimeTrainsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities for the account and every subentry.

    Binary-sensor entities are registered via ``binary_sensor.py`` (so
    they get ``binary_sensor.*`` entity IDs and live on the correct
    platform). Only ``SensorEntity`` subclasses are produced here.
    """
    runtime_data: RealtimeTrainsRuntimeData = config_entry.runtime_data
    account_entities = _build_account_entities(runtime_data.account, config_entry)
    async_add_entities(account_entities)
    for subentry_id in config_entry.subentries:
        coordinator = runtime_data.subentry_coordinators.get(subentry_id)
        if coordinator is None:
            continue
        if isinstance(coordinator, RealtimeTrainsBoardCoordinator):
            entities = _build_board_entities(coordinator, subentry_id)
            async_add_entities(entities, config_subentry_id=subentry_id)
        elif isinstance(coordinator, RealtimeTrainsServiceTrackerCoordinator):
            entities = _build_service_entities(coordinator, subentry_id)
            async_add_entities(entities, config_subentry_id=subentry_id)


def _build_account_entities(
    coordinator: RealtimeTrainsAccountCoordinator,
    config_entry: RealtimeTrainsConfigEntry,
) -> list[SensorEntity]:
    """Build all diagnostic SENSOR entities attached to the account device.

    Binary sensors are set up separately in ``binary_sensor.py``.
    """
    return [
        RealtimeTrainsAccountSensor(coordinator, config_entry, desc)
        for desc in ACCOUNT_SENSOR_DESCRIPTIONS
    ]


def _build_board_entities(
    coordinator: RealtimeTrainsBoardCoordinator, subentry_id: str
) -> list[SensorEntity]:
    """Build all sensor entities for one departure-board subentry."""
    slot_count = coordinator.slot_count
    slot_descriptions = tuple(_make_slot_description(i) for i in range(slot_count))
    entities: list[SensorEntity] = [
        RealtimeTrainsBoardSensor(coordinator, subentry_id, desc)
        for desc in slot_descriptions
    ]
    entities.extend(
        RealtimeTrainsBoardSensor(coordinator, subentry_id, desc)
        for desc in BOARD_BASE_SENSOR_DESCRIPTIONS
    )
    return entities


def _build_service_entities(
    coordinator: RealtimeTrainsServiceTrackerCoordinator, subentry_id: str
) -> list[SensorEntity]:
    """Build all sensor entities for one service-tracker subentry."""
    return [
        RealtimeTrainsServiceSensor(coordinator, subentry_id, desc)
        for desc in SERVICE_SENSOR_DESCRIPTIONS
    ]


# --- Entity classes -------------------------------------------------------


class _BaseBoardEntity(CoordinatorEntity[RealtimeTrainsBoardCoordinator]):
    """Shared device-info and unique-id plumbing for board entities."""

    _attr_attribution = "Data provided by Realtime Trains"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RealtimeTrainsBoardCoordinator,
        subentry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry_id
        self._attr_device_info = _board_device_info(coordinator, coordinator.empty_data)


class RealtimeTrainsBoardSensor(_BaseBoardEntity, SensorEntity):
    """Sensor entity for a board sensor (slot-based or aggregate)."""

    entity_description: BoardSensorEntityDescription

    def __init__(
        self,
        coordinator: RealtimeTrainsBoardCoordinator,
        subentry_id: str,
        description: BoardSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, subentry_id)
        self.entity_description = description
        slot = description.slot
        key_part = "departure" if "departure" in description.key else description.key
        suffix = f":{slot}" if slot > 0 else ""
        self._attr_unique_id = self._build_unique_id(coordinator, key_part, suffix)

    @staticmethod
    def _build_unique_id(
        coordinator: RealtimeTrainsBoardCoordinator,
        key_part: str,
        suffix: str,
    ) -> str:
        ns = coordinator.namespace
        code = coordinator.station_code
        return f"{ns}:{code}:{key_part}{suffix}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the slot-based or aggregate value."""
        data: BoardData | None = self.coordinator.data
        if data is None:
            data = self.coordinator.empty_data
        return self.entity_description.value_fn(data, self.entity_description.slot)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose rich attributes on the next departure (slot 0) only."""
        if (
            self.entity_description.slot != 0
            or self.entity_description.key != "next_departure"
        ):
            return None
        data: BoardData | None = self.coordinator.data
        if data is None or not data.departures:
            return None
        slot = data.departures[0]
        attrs: dict[str, Any] = {
            "headcode": slot.headcode,
            "operator": (
                f"{slot.operator_code} — {slot.operator_name}"
                if slot.operator_code and slot.operator_name
                else slot.operator_code or slot.operator_name
            ),
            "origin": slot.origin,
            "destination": slot.destination,
            "platform_planned": slot.platform_planned,
            "platform_actual": slot.platform_actual,
            "delay": slot.delay,
            "status": str(slot.live_status) if slot.live_status else None,
            "cancellation_reason": slot.cancellation_reason,
            "delay_reason": slot.delay_reason,
            "stp": slot.stp_indicator,
            "unique_identity": slot.unique_identity,
            "namespace": slot.namespace,
            "mode": slot.mode,
            "in_passenger_service": slot.in_passenger_service,
            "onboard_facilities": slot.onboard_facilities,
            "stock_branding": slot.stock_branding,
        }
        # Strip None values to keep the entity compact.
        return {k: v for k, v in attrs.items() if v is not None}


class RealtimeTrainsBoardBinarySensor(_BaseBoardEntity, BinarySensorEntity):
    """Binary sensor on a board (cancellations, platform changes)."""

    entity_description: BoardBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: RealtimeTrainsBoardCoordinator,
        subentry_id: str,
        description: BoardBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, subentry_id)
        self.entity_description = description
        self._attr_unique_id = RealtimeTrainsBoardSensor._build_unique_id(
            coordinator, description.key, ""
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is currently on."""
        data: BoardData | None = self.coordinator.data
        if data is None:
            data = self.coordinator.empty_data
        return self.entity_description.value_fn(data)


class RealtimeTrainsServiceSensor(
    CoordinatorEntity[RealtimeTrainsServiceTrackerCoordinator], SensorEntity
):
    """Sensor entity for a service tracker."""

    _attr_attribution = "Data provided by Realtime Trains"
    _attr_has_entity_name = True
    entity_description: ServiceSensorEntityDescription

    def __init__(
        self,
        coordinator: RealtimeTrainsServiceTrackerCoordinator,
        subentry_id: str,
        description: ServiceSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry_id
        self.entity_description = description
        self._attr_device_info = _service_device_info(
            coordinator, coordinator.empty_data
        )
        self._attr_unique_id = self._build_unique_id(coordinator, description.key)

    @staticmethod
    def _build_unique_id(
        coordinator: RealtimeTrainsServiceTrackerCoordinator, key: str
    ) -> str:
        ns = coordinator.namespace
        ident = coordinator.unique_identity or coordinator.headcode
        # Collapse any ``:`` in the identity to a ``_`` to keep the
        # entity-id shape flat (HA's entity-id rules don't allow colons).
        flat_ident = (ident or "").replace(":", "_")
        return f"{ns}:service:{flat_ident}:{key}"

    @property
    def native_value(self) -> StateType | datetime:
        data: ServiceTrackerData | None = self.coordinator.data
        if data is None:
            data = self.coordinator.empty_data
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose formation/KYT attributes on the departure entity."""
        if self.entity_description.key != "departure":
            return None
        data = self.coordinator.data
        coordinator = self.coordinator
        attrs: dict[str, Any] = {
            "headcode": coordinator.headcode,
            "departure_date": coordinator.departure_date,
            "unique_identity": coordinator.unique_identity,
            "stock_branding": None,
            "leading_class": None,
            "passenger_vehicles": None,
            "allocations": None,
            "know_your_train": None,
        }
        if data and data.formation:
            first = data.formation[0]
            attrs["leading_class"] = first.leading_class
            attrs["passenger_vehicles"] = first.passenger_vehicles
            if first.know_your_train_data is not None:
                attrs["stock_branding"] = first.know_your_train_data.stock_branding
                attrs["know_your_train"] = _kyt_to_dict(first.know_your_train_data)
            attrs["allocations"] = [
                _allocation_to_dict(alloc) for alloc in data.formation
            ]
        return {k: v for k, v in attrs.items() if v is not None}


def _allocation_to_dict(alloc: Any) -> dict[str, Any]:
    """Serialise a NetworkRailAllocation to a dict for entity attributes."""
    return asdict(alloc)


def _kyt_to_dict(kyt: Any) -> dict[str, Any]:
    """Serialise a NetworkRailKnowYourTrainData to a dict for entity attributes."""
    return asdict(kyt)


class RealtimeTrainsAccountSensor(
    CoordinatorEntity[RealtimeTrainsAccountCoordinator], SensorEntity
):
    """Diagnostic sensor on the account device (rate limits, api version)."""

    _attr_attribution = "Data provided by Realtime Trains"
    _attr_has_entity_name = True
    entity_description: AccountSensorEntityDescription

    def __init__(
        self,
        coordinator: RealtimeTrainsAccountCoordinator,
        config_entry: RealtimeTrainsConfigEntry,
        description: AccountSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = _account_device_info(config_entry)
        self._attr_unique_id = f"account:{config_entry.entry_id}:{description.key}"

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator)


class RealtimeTrainsAccountBinarySensor(
    CoordinatorEntity[RealtimeTrainsAccountCoordinator], BinarySensorEntity
):
    """Diagnostic binary sensor on the account device (restrictions)."""

    _attr_attribution = "Data provided by Realtime Trains"
    _attr_has_entity_name = True
    entity_description: AccountBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: RealtimeTrainsAccountCoordinator,
        config_entry: RealtimeTrainsConfigEntry,
        description: AccountBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = _account_device_info(config_entry)
        self._attr_unique_id = f"account:{config_entry.entry_id}:{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)
