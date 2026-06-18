"""The Realtime Trains integration.

Connects Home Assistant to the Realtime Trains next-generation API
(`https://data.rtt.io`) for live UK train departures, platform information,
service tracking and rolling-stock formation data.

This module is the entry point for HA's config entry lifecycle. The
runtime_data pattern is used: `entry.runtime_data` carries the account
coordinator once setup completes. Entities are set up by platform
modules (added in later milestones); this scaffold supports load/unload
without exposing any entities yet.
"""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS

type RealtimeTrainsConfigEntry = ConfigEntry[Any]


async def async_setup_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> bool:
    """Set up Realtime Trains from a config entry.

    The account coordinator and subentry setup arrive in M4. For this
    scaffold we only accept the entry so the integration loads and
    appears in the device list.
    """
    entry.runtime_data = None
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
