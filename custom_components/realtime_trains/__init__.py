"""The Realtime Trains integration.

Connects Home Assistant to the Realtime Trains next-generation API
(`https://data.rtt.io`) for live UK train departures, platform
information, service tracking and rolling-stock formation data.

The runtime_data pattern is used: each config entry's runtime_data
holds a :class:`RealtimeTrainsRuntimeData` wrapper that contains the
account coordinator (owning the API client and stops cache) plus a
mapping of subentry_id to per-subentry coordinators (one per
departure board or service tracker the user has added).

Platform setup iterates the subentries the entry owns and constructs
the appropriate coordinator per subentry, mirroring the Nederlandse
Spoorwegen pattern.
"""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RealtimeTrainsApi
from .const import (
    API_VERSION,
    CONF_TOKEN,
    DOMAIN,
    SUBENTRY_TYPE_DEPARTURE_BOARD,
    SUBENTRY_TYPE_SERVICE_TRACKER,
)
from .coordinator import (
    RealtimeTrainsAccountCoordinator,
    RealtimeTrainsBoardCoordinator,
    RealtimeTrainsConfigEntry,
    RealtimeTrainsRuntimeData,
    RealtimeTrainsServiceTrackerCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> bool:
    """Set up Realtime Trains from a config entry.

    Constructs the API client, runs the first ``/api/info`` via the
    account coordinator to validate the token, then constructs child
    coordinators for every monitored-item subentry the entry owns.
    Transient first-refresh failures surface as
    :class:`~homeassistant.exceptions.ConfigEntryNotReady` so HA
    retries; auth failures surface as
    :class:`~homeassistant.exceptions.ConfigEntryError` so a repair
    issue is raised and the user can reauthenticate.
    """
    token: str = entry.data[CONF_TOKEN]
    client = RealtimeTrainsApi(
        async_get_clientsession(hass),
        token,
        api_version=API_VERSION,
    )

    account_coordinator = RealtimeTrainsAccountCoordinator(hass, entry, client)
    try:
        await account_coordinator.async_config_entry_first_refresh()
    except ConfigEntryError:
        raise
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err

    runtime_data = RealtimeTrainsRuntimeData(account=account_coordinator)
    entry.runtime_data = runtime_data

    # Construct a per-subentry coordinator for every monitored item the
    # account entry already owns. New subentries added later trigger the
    # same construction via the per-subentry platform-setup callback.
    for subentry_id, subentry in entry.subentries.items():
        coordinator = await _build_subentry_coordinator(
            hass, entry, subentry_id, subentry
        )
        if coordinator is not None:
            runtime_data.subentry_coordinators[subentry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _build_subentry_coordinator(
    hass: HomeAssistant,
    entry: RealtimeTrainsConfigEntry,
    subentry_id: str,
    subentry: object,
) -> object | None:
    """Construct the right coordinator for a subentry based on its type."""
    runtime_data: RealtimeTrainsRuntimeData = entry.runtime_data
    account = runtime_data.account
    subentry_type = getattr(subentry, "subentry_type", None)
    if subentry_type == SUBENTRY_TYPE_DEPARTURE_BOARD:
        coordinator = RealtimeTrainsBoardCoordinator(
            hass,
            entry,
            subentry_id,
            subentry,
            account,  # type: ignore[arg-type]
        )
        await coordinator.async_config_entry_first_refresh()
        return coordinator
    if subentry_type == SUBENTRY_TYPE_SERVICE_TRACKER:
        coordinator = RealtimeTrainsServiceTrackerCoordinator(
            hass,
            entry,
            subentry_id,
            subentry,
            account,  # type: ignore[arg-type]
        )
        await coordinator.async_config_entry_first_refresh()
        return coordinator
    _LOGGER.warning(
        "Unknown subentry type %s for %s; ignoring",
        subentry_type,
        entry.entry_id,
    )
    return None


async def async_unload_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> None:
    """Reload the integration when the entry is updated (reconfigure / reauth)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> bool:
    """Migrate the config entry between versions.

    No migrations needed for v1.x yet.
    """
    _LOGGER.debug(
        "Migrating config entry from version %s.%s",
        entry.version,
        entry.minor_version,
    )
    return entry.version <= 1
