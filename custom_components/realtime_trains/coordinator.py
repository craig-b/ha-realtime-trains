"""DataUpdateCoordinator for the Realtime Trains integration.

The account coordinator owns the :class:`RealtimeTrainsApi` client,
polls ``/api/info`` on a slow cadence to refresh entitlements and API
version metadata, and caches the ``/data/stops`` passenger-stop list
for a week at a time so subentry config flows can offer the
searchable station picker without going to the API.

Subentry coordinators (departure boards, service trackers — added in
later milestones) access the API through this coordinator's
:py:attr:`api` property and share its serialisation mutex so that
outbound requests across all monitored items are spaced out rather
than bursting against the account's rate limit.

Errors raised by the API client are mapped to HA exceptions:

* :class:`~homeassistant.exceptions.ConfigEntryError` for auth
  failures (the integration needs user intervention via the reauth
  repair flow).
* :class:`~homeassistant.exceptions.ConfigEntryNotReady` for
  transient setup-time failures (network unreachable).
* :class:`~homeassistant.helpers.update_coordinator.UpdateFailed`
  for transient runtime failures (rate-limited, network blip).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    RealtimeTrainsApi,
    RttAuthError,
    RttConnectionError,
    RttError,
    RttRateLimitError,
)
from .const import ACCOUNT_INFO_REFRESH_SECONDS, DOMAIN, STOPS_CACHE_TTL_DAYS
from .models import ApiInfo, Stop

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# How long to keep the stops cache before re-fetching from /data/stops.
STOPS_CACHE_TTL = timedelta(days=STOPS_CACHE_TTL_DAYS)


type RealtimeTrainsConfigEntry = ConfigEntry[RealtimeTrainsAccountCoordinator]


@dataclass(frozen=True, slots=True)
class AccountData:
    """Snapshot presented by the account coordinator on each refresh.

    ``api_info`` reflects the latest ``/api/info`` response.
    ``stops`` is the cached passenger-stop list (refreshed weekly).
    """

    api_info: ApiInfo | None
    stops: list[Stop]


def _translate(err: RttError) -> UpdateFailed:
    """Map an RttError to a translated UpdateFailed.

    Returns :class:`UpdateFailed` for transient errors. Auth failures
    are surfaced separately by the caller (as :class:`ConfigEntryError`)
    so that a repair issue is raised.
    """
    if isinstance(err, RttRateLimitError):
        return UpdateFailed(translation_domain=DOMAIN, translation_key="rate_limited")
    if isinstance(err, RttConnectionError):
        return UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect")
    return UpdateFailed(translation_domain=DOMAIN, translation_key="unknown")


class RealtimeTrainsAccountCoordinator(DataUpdateCoordinator[AccountData]):
    """Account-level coordinator.

    Created once per account config entry. Holds the API client and the
    cached stop list. Subentry coordinators are constructed in
    :py:func:`custom_components.realtime_trains.__init__.async_setup_entry`
    and request data through this coordinator's serialisation method
    so concurrent polls are spaced out across the account.
    """

    config_entry: RealtimeTrainsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RealtimeTrainsConfigEntry,
        api: RealtimeTrainsApi,
    ) -> None:
        """Initialise the account coordinator with the supplied API client."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=ACCOUNT_INFO_REFRESH_SECONDS),
            config_entry=config_entry,
        )
        self._api = api
        self._stops_cache: list[Stop] | None = None
        self._stops_cache_at: datetime | None = None
        # Mutex serialising every outbound API call made through this
        # coordinator. Subentry coordinators use ``serialise`` so that
        # boards under one account never burst against the rate limit.
        self._request_lock = asyncio.Lock()

    @property
    def api(self) -> RealtimeTrainsApi:
        """Return the underlying API client."""
        return self._api

    async def serialise(
        self, fn: Callable[..., Awaitable[_T]], *args: Any, **kwargs: Any
    ) -> _T:
        """Run an API call inside the per-account request mutex."""
        async with self._request_lock:
            return await fn(*args, **kwargs)

    async def refresh_stops(self) -> list[Stop]:
        """Fetch the passenger stop list if the cache is empty or stale.

        Used by subentry config flows when they need to populate the
        searchable station picker. A return of empty list means the
        fetch failed; the caller may choose to retry or fall back to
        asking the user for a plain-text code.
        """
        now = datetime.now(UTC)
        if (
            self._stops_cache is None
            or self._stops_cache_at is None
            or now - self._stops_cache_at > STOPS_CACHE_TTL
        ):
            try:
                self._stops_cache = await self.serialise(self._api.async_get_stops)
                self._stops_cache_at = now
            except RttAuthError as err:
                raise ConfigEntryError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                ) from err
            except RttError as err:
                raise _translate(err) from err
        return self._stops_cache or []

    async def fetch_stops(self, query: str, limit: int = 10) -> list[Stop]:
        """Search the cached stops by substring of description or code."""
        if not self._stops_cache:
            await self.refresh_stops()
        if not self._stops_cache:
            return []
        q = query.lower()
        return [
            stop
            for stop in self._stops_cache
            if (
                (stop.description is not None and q in stop.description.lower())
                or (stop.short_code is not None and q in stop.short_code.lower())
                or (
                    stop.unique_identity is not None
                    and q in stop.unique_identity.lower()
                )
            )
        ][:limit]

    async def _async_update_data(self) -> AccountData:
        try:
            api_info = await self.serialise(self._api.async_get_info)
            stops = self._stops_cache
        except RttAuthError as err:
            # Surface to HA as a hard error so a repair issue is raised
            # and the user is prompted to enter the token again.
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            ) from err
        except RttError as err:
            raise _translate(err) from err
        return AccountData(api_info=api_info, stops=stops or [])
