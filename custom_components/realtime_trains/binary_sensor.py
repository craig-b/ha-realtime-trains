"""Binary sensor entities for the Realtime Trains integration.

The binary-sensor entity descriptions, value functions and entity classes
are defined in :mod:`custom_components.realtime_trains.sensor` because they
share state (``BoardData`` / ``ServiceTrackerData`` / ``AccountData``)
with the sensor platform and the same device-info plumbing. This module
only wires up the platform's ``async_setup_entry`` so HA creates the
``binary_sensor.*`` entities on the correct platform, with the correct
entity-id prefix and platform-aware registry bookkeeping.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import (
    RealtimeTrainsBoardCoordinator,
    RealtimeTrainsConfigEntry,
    RealtimeTrainsRuntimeData,
)
from .sensor import (
    ACCOUNT_BINARY_DESCRIPTIONS,
    BOARD_BINARY_DESCRIPTIONS,
    RealtimeTrainsAccountBinarySensor,
    RealtimeTrainsBoardBinarySensor,
)

# All binary-sensor entity classes are defined in ``sensor.py`` for
# state-sharing clarity. We import them here so HA's platform-dispatch
# finds them on a real ``binary_sensor`` platform entity. The actual
# data flow is identical to ``sensor.async_setup_entry`` — both walk
# ``runtime_data.subentry_coordinators`` and add their entities per
# subentry.


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RealtimeTrainsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary-sensor entities for the account and every subentry."""
    runtime_data: RealtimeTrainsRuntimeData = config_entry.runtime_data

    # Account-device binary sensors (history_restricted, namespace_restricted).
    account_entities = [
        RealtimeTrainsAccountBinarySensor(runtime_data.account, config_entry, desc)
        for desc in ACCOUNT_BINARY_DESCRIPTIONS
    ]
    if account_entities:
        async_add_entities(account_entities)

    for subentry_id in config_entry.subentries:
        coordinator = runtime_data.subentry_coordinators.get(subentry_id)
        if coordinator is None:
            continue
        if isinstance(coordinator, RealtimeTrainsBoardCoordinator):
            entities: list[BinarySensorEntity] = [
                RealtimeTrainsBoardBinarySensor(coordinator, subentry_id, desc)
                for desc in BOARD_BINARY_DESCRIPTIONS
            ]
            async_add_entities(entities, config_subentry_id=subentry_id)
        # Service trackers do not currently expose binary sensors.


# Keep the import-export markers in sync so ruff doesn't warn about
# unused imports (they're used by HA's platform-discovery).
_ = (Platform, DOMAIN)
