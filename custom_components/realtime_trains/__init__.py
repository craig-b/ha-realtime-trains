"""The Realtime Trains integration.

Connects Home Assistant to the Realtime Trains next-generation API
(`https://data.rtt.io`) for live UK train departures, platform
information, service tracking and rolling-stock formation data.

This module is the entry point for HA's config entry lifecycle. The
runtime_data pattern is used: ``entry.runtime_data`` carries the
:class:`RealtimeTrainsAccountCoordinator` once setup completes. The
coordinator owns the API client and the cached stop list.

Subentry coordinators (departure boards, service trackers) are set up
per subentry in M5 and onward; this module currently only establishes
the account entry so the coordinator is live and a future ``Add
departure board`` action on the device page will work.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RealtimeTrainsApi
from .const import API_VERSION, CONF_TOKEN, DOMAIN, PLATFORMS
from .coordinator import RealtimeTrainsAccountCoordinator, RealtimeTrainsConfigEntry

_LOGGER = logging.getLogger(__name__)

type RealtimeTrainsAccountEntry = RealtimeTrainsConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: RealtimeTrainsAccountEntry
) -> bool:
    """Set up Realtime Trains from a config entry.

    Builds the API client, runs the first ``/api/info`` to validate
    the token, and surface specific errors via translated ConfigEntry
    exceptions so the user sees a sensible repair flow when needed.
    """
    token: str = entry.data[CONF_TOKEN]
    client = RealtimeTrainsApi(
        async_get_clientsession(hass),
        token,
        api_version=API_VERSION,
    )

    coordinator = RealtimeTrainsAccountCoordinator(hass, entry, client)
    # First refresh does the /api/info validation and primes the
    # coordinator's cached state. Transient failures raise
    # ConfigEntryNotReady so HA will retry; auth failures raise
    # ConfigEntryError so a repair issue is created.
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryError:
        raise
    except Exception as err:  # noqa: BLE001
        # Any other failure during first refresh is treated as transient.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RealtimeTrainsAccountEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: RealtimeTrainsAccountEntry
) -> None:
    """Reload the integration when the entry is updated (reconfigure / reauth)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, entry: RealtimeTrainsAccountEntry
) -> bool:
    """Migrate the config entry between versions.

    Future schema changes are handled here. The first version (1.1)
    has no migration needs yet.
    """
    _LOGGER.debug(
        "Migrating config entry from version %s.%s",
        entry.version,
        entry.minor_version,
    )
    # Reject downgrades from future versions (we never release beyond v1
    # yet, but keeping the guard means we don't silently re-run setup).
    return entry.version <= 1
