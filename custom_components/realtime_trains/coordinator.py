"""DataUpdateCoordinators for the Realtime Trains integration.

Three coordinators are housed here:

* :class:`RealtimeTrainsAccountCoordinator` — owns the API client and
  the cached stops list; polls ``/api/info`` every hour to refresh
  entitlements.
* :class:`RealtimeTrainsBoardCoordinator` — one per departure-board
  subentry; polls ``/gb-nr/location`` for a station + window.
* :class:`RealtimeTrainsServiceTrackerCoordinator` — one per
  service-tracker subentry; polls ``/gb-nr/service`` for a single train.

All three share a single :class:`RealtimeTrainsApi` client (owned by
the account coordinator) so that all outbound requests across the
account are serialised through the account coordinator's mutex. This
prevents a multi-board setup from bursting against the API rate limit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
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
from .const import (
    ACCOUNT_INFO_REFRESH_SECONDS,
    CONF_DATE,
    CONF_DETAILED,
    CONF_FILTER_FROM,
    CONF_FILTER_TO,
    CONF_HEADCODE,
    CONF_NAMESPACE,
    CONF_POLLING_INTERVAL,
    CONF_SLOT_COUNT,
    CONF_STATION,
    CONF_STATION_DESCRIPTION,
    CONF_TIME_WINDOW,
    CONF_UNIQUE_IDENTITY,
    DEFAULT_NAMESPACE,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_SLOT_COUNT,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
    STOPS_CACHE_TTL_DAYS,
)
from .models import (
    ApiInfo,
    LocationDisplayAs,
    LocationLineUp,
    LocationLineUpResponse,
    LocationStatus,
    NetworkRailAllocation,
    NetworkRailKnowYourTrainData,
    NetworkRailLocationLineUp,
    NetworkRailLocationLineUpResponse,
    NetworkRailServiceDetail,
    ReasonBlock,
    ReasonType,
    Stop,
)

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

STOPS_CACHE_TTL = timedelta(days=STOPS_CACHE_TTL_DAYS)

# How long the service-tracker coordinator waits between polls when the
# service is in different states. Tunable; overridden by subentry config
# in a future milestone.
SERVICE_POLL_SCHEDULED = timedelta(minutes=15)
SERVICE_POLL_IN_RUN = timedelta(seconds=30)
SERVICE_POLL_TERMINAL = timedelta(hours=1)


# --- Account-level runtime data -------------------------------------------


@dataclass
class RealtimeTrainsRuntimeData:
    """Per-config-entry runtime state.

    ``account`` owns the API client + stops cache. ``subentry_coordinators``
    maps every monitored-item subentry id to its board or service-tracker
    coordinator.
    """

    account: RealtimeTrainsAccountCoordinator
    subentry_coordinators: dict[str, Any] = field(default_factory=dict)


type RealtimeTrainsConfigEntry = ConfigEntry[RealtimeTrainsRuntimeData]


# --- Shared exception mapping ----------------------------------------------


def board_display_name(
    station: str | None,
    filter_from: str | None = None,
    filter_to: str | None = None,
) -> str:
    """Compose a board's display name, folding in the direction filter.

    Two boards for the same station differ only by their from/to filter,
    so include it to keep the devices distinguishable.
    """
    base = station or "Board"
    if filter_from and filter_to:
        return f"{base}: {filter_from} → {filter_to}"
    if filter_to:
        return f"{base} → {filter_to}"
    if filter_from:
        return f"{base} ← {filter_from}"
    return base


def _translate(err: RttError) -> UpdateFailed:
    """Map an RttError to a translated UpdateFailed (transient-cadence)."""
    if isinstance(err, RttRateLimitError):
        return UpdateFailed(translation_domain=DOMAIN, translation_key="rate_limited")
    if isinstance(err, RttConnectionError):
        return UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect")
    return UpdateFailed(translation_domain=DOMAIN, translation_key="unknown")


def _raise_auth() -> ConfigEntryError:
    """Build a translated ConfigEntryError for an auth failure.

    Returns the exception (rather than raising) so callers can raise it
    with the originating error chained via ``raise ... from err``.
    """
    return ConfigEntryError(
        translation_domain=DOMAIN,
        translation_key="invalid_auth",
    )


# --- Account coordinator --------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountData:
    """Snapshot presented by the account coordinator on each refresh."""

    api_info: ApiInfo | None
    stops: list[Stop]


class RealtimeTrainsAccountCoordinator(DataUpdateCoordinator[AccountData]):
    """Account-level coordinator.

    Polls ``/api/info`` on a slow cadence. Caches the /data/stops list
    for a week at a time. Exposes the API client and a serialisation
    mutex so subentry coordinators share a single outbound request lane.
    """

    config_entry: RealtimeTrainsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RealtimeTrainsConfigEntry,
        api: RealtimeTrainsApi,
    ) -> None:
        """Initialise with the account's API client."""
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
        # coordinator. Subentry coordinators use ``serialise`` so
        # concurrent polls across multiple boards under one account never
        # burst against the rate limit.
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
        """Refetch the passenger-stop list if the cache is stale or empty."""
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
                raise _raise_auth() from err
            except RttError as err:
                raise _translate(err) from err
        return self._stops_cache or []

    async def fetch_stops(self, query: str, limit: int = 10) -> list[Stop]:
        """Substring search across the cached stop list."""
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
            raise _raise_auth() from err
        except RttError as err:
            raise _translate(err) from err
        return AccountData(api_info=api_info, stops=stops or [])


# --- Departure board coordinator + data shape -----------------------------


@dataclass(frozen=True, slots=True)
class DepartureSlot:
    """Typed per-slot projection of a single departure board entry.

    This is what entity-level code consumes — the original
    :class:`NetworkRailLocationLineUp` schema is reduced to the
    fields actually surfaced on entities listed in docs/entities.md.
    """

    headcode: str | None
    operator_code: str | None
    operator_name: str | None
    origin: str | None
    destination: str | None
    platform_planned: str | None
    platform_actual: str | None
    delay: int | None
    scheduled_departure: datetime | None
    realtime_departure: datetime | None
    live_status: LocationStatus | None
    display_as: LocationDisplayAs | None
    is_cancelled: bool | None
    cancellation_reason: str | None
    delay_reason: str | None
    stp_indicator: str | None
    unique_identity: str | None
    namespace: str | None
    mode: str | None
    in_passenger_service: bool | None
    stock_branding: str | None


@dataclass(frozen=True, slots=True)
class BoardData:
    """Aggregate view consumed by every entity on a board device."""

    departures: list[DepartureSlot]
    next_delay: int | None
    any_cancellations: bool
    platform_changed: bool
    live_status: LocationStatus | None
    station_description: str | None
    station_code: str | None
    namespace: str | None


def _resolve_reason(
    reasons: list[ReasonBlock],
    reason_type: ReasonType,
    fallback_code: str | None,
) -> str | None:
    """Resolve a reason code to its human-readable short_text.

    The ``reasons`` list on a line-up entry carries both delay and
    cancellation reasons. Each has a ``code`` and a ``short_text``;
    we prefer the short_text but fall back to the raw code (from the
    temporal-data ``cancellation_reason_code`` field) if no matching
    reason block exists.
    """
    for reason in reasons:
        if reason.type == reason_type:
            return reason.short_text or reason.code or fallback_code
    return fallback_code


def _slot_from_lineup(
    svc: NetworkRailLocationLineUp | LocationLineUp,
) -> DepartureSlot:
    """Reduce a NetworkRail or generic-namespace line-up entry to a DepartureSlot.

    The two ``*LocationLineUp`` classes share the same shape for every
    field read here, so duck-typing handles both namespaces.
    """
    td = svc.temporal_data
    md = svc.location_metadata
    sm = svc.schedule_metadata
    planned_dept: datetime | None = None
    realtime_dept: datetime | None = None
    delay: int | None = None
    live_status: LocationStatus | None = None
    display_as: LocationDisplayAs | None = None
    is_cancelled: bool | None = None
    cancellation_reason: str | None = None
    delay_reason: str | None = None
    if td is not None:
        if td.departure is not None:
            planned_dept = td.departure.schedule_advertised
            realtime_dept = (
                td.departure.realtime_actual or td.departure.realtime_forecast
            )
            if td.departure.realtime_advertised_lateness is not None:
                delay = td.departure.realtime_advertised_lateness
            if td.departure.is_cancelled is not None:
                is_cancelled = td.departure.is_cancelled
            if td.departure.cancellation_reason_code is not None:
                cancellation_reason = td.departure.cancellation_reason_code
        live_status = td.status
        display_as = td.display_as
    # Resolve reason codes to human-readable short_text via the reasons
    # block on the line-up entry (svc.reasons is list[ReasonBlock]).
    cancellation_reason = _resolve_reason(
        svc.reasons, ReasonType.CANCEL, cancellation_reason
    )
    delay_reason = _resolve_reason(svc.reasons, ReasonType.DELAY, None)
    platform_planned: str | None = None
    platform_actual: str | None = None
    stock_branding: str | None = None
    if md is not None:
        if md.platform is not None:
            platform_planned = md.platform.planned
            platform_actual = md.platform.actual
        stock_branding = getattr(md, "stock_branding", None)
    operator_code: str | None = None
    operator_name: str | None = None
    if sm is not None and sm.operator is not None:
        operator_code = sm.operator.code
        operator_name = sm.operator.name
    stp: str | None = None
    headcode: str | None = None
    uid: str | None = None
    ns: str | None = None
    mode: str | None = None
    in_service: bool | None = None
    if sm is not None:
        headcode = getattr(sm, "train_reporting_identity", None)
        stp_indicator = getattr(sm, "stp_indicator", None)
        stp = str(stp_indicator) if stp_indicator is not None else None
        uid = sm.unique_identity
        ns = sm.namespace
        mode = str(sm.mode_type) if sm.mode_type is not None else None
        in_service = sm.in_passenger_service
    origin_desc = (
        svc.origin[0].location.description
        if svc.origin and svc.origin[0].location is not None
        else None
    )
    dest_desc = (
        svc.destination[0].location.description
        if svc.destination and svc.destination[0].location is not None
        else None
    )
    return DepartureSlot(
        headcode=headcode,
        operator_code=operator_code,
        operator_name=operator_name,
        origin=origin_desc,
        destination=dest_desc,
        platform_planned=platform_planned,
        platform_actual=platform_actual,
        delay=delay,
        scheduled_departure=planned_dept,
        realtime_departure=realtime_dept,
        live_status=live_status,
        display_as=display_as,
        is_cancelled=is_cancelled,
        cancellation_reason=cancellation_reason,
        delay_reason=delay_reason,
        stp_indicator=stp,
        unique_identity=uid,
        namespace=ns,
        mode=mode,
        in_passenger_service=in_service,
        stock_branding=stock_branding,
    )


class RealtimeTrainsBoardCoordinator(DataUpdateCoordinator[BoardData]):
    """Per-subentry coordinator for a departure board."""

    config_entry: RealtimeTrainsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RealtimeTrainsConfigEntry,
        subentry_id: str,
        subentry: ConfigSubentry,
        account: RealtimeTrainsAccountCoordinator,
    ) -> None:
        """Initialise from the subentry's configured board options."""
        self._subentry_id = subentry_id
        self._subentry = subentry
        self._account = account
        data = subentry.data
        self.station_code: str = data.get(CONF_STATION, "")
        self.station_description: str | None = data.get(CONF_STATION_DESCRIPTION)
        self.filter_from: str | None = data.get(CONF_FILTER_FROM)
        self.filter_to: str | None = data.get(CONF_FILTER_TO)
        self.time_window: int = int(data.get(CONF_TIME_WINDOW, DEFAULT_TIME_WINDOW))
        self.slot_count: int = int(data.get(CONF_SLOT_COUNT, DEFAULT_SLOT_COUNT))
        self.detailed: bool = bool(data.get(CONF_DETAILED, False))
        self.namespace: str = data.get(CONF_NAMESPACE, DEFAULT_NAMESPACE)
        polling_seconds = int(data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_board_{subentry_id}",
            update_interval=timedelta(seconds=polling_seconds),
            config_entry=config_entry,
        )
        # Build the empty-state BoardData so entities never read None.
        self._empty = BoardData(
            departures=[],
            next_delay=None,
            any_cancellations=False,
            platform_changed=False,
            live_status=None,
            station_description=self.station_description,
            station_code=self.station_code,
            namespace=self.namespace,
        )

    @property
    def subentry_id(self) -> str:
        """Return the subentry id this coordinator backs."""
        return self._subentry_id

    async def _async_update_data(self) -> BoardData:
        try:
            response = await self._account.serialise(
                self._account.api.async_get_location,
                self.station_code,
                filter_from=self.filter_from,
                filter_to=self.filter_to,
                time_window=self.time_window,
                detailed=self.detailed,
                namespace=self.namespace,
            )
        except RttAuthError as err:
            raise _raise_auth() from err
        except RttError as err:
            raise _translate(err) from err
        if isinstance(
            response,
            (NetworkRailLocationLineUpResponse, LocationLineUpResponse),
        ):
            services = response.services
        else:
            services = []
        slots = [_slot_from_lineup(svc) for svc in services]
        slots = slots[: self.slot_count]
        next_slot = slots[0] if slots else None
        next_delay = next_slot.delay if next_slot is not None else None
        any_cancellations = any((slot.is_cancelled is True) for slot in slots)
        platform_changed = bool(
            next_slot is not None
            and next_slot.platform_planned is not None
            and next_slot.platform_actual is not None
            and next_slot.platform_actual != next_slot.platform_planned
        )
        live_status = next_slot.live_status if next_slot else None
        return BoardData(
            departures=slots,
            next_delay=next_delay,
            any_cancellations=any_cancellations,
            platform_changed=platform_changed,
            live_status=live_status,
            station_description=self.station_description,
            station_code=self.station_code,
            namespace=self.namespace,
        )

    @property
    def empty_data(self) -> BoardData:
        """Return the empty-state BoardData used when no services exist."""
        return self._empty


# --- Service tracker coordinator + data shape -----------------------------


@dataclass(frozen=True, slots=True)
class ServiceTrackerData:
    """Snapshot for one tracked service."""

    unique_identity: str | None
    headcode: str | None
    departure: datetime | None
    arrival: datetime | None
    live_status: LocationStatus | None
    delay: int | None
    is_cancelled: bool | None
    display_as: LocationDisplayAs | None
    formation: list[NetworkRailAllocation] | None
    know_your_train: NetworkRailKnowYourTrainData | None


class RealtimeTrainsServiceTrackerCoordinator(
    DataUpdateCoordinator[ServiceTrackerData]
):
    """Per-subentry coordinator tracking a single service.

    Polls ``/gb-nr/service`` for the configured unique_identity /
    headcode+date. Cadence adapts to service liveness.

    Dynamic-cadence is currently a fixed base interval; the rate-limit
    + live-status driven cadence arrives in a later milestone (see the
    plan's M6 section).
    """

    config_entry: RealtimeTrainsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RealtimeTrainsConfigEntry,
        subentry_id: str,
        subentry: ConfigSubentry,
        account: RealtimeTrainsAccountCoordinator,
    ) -> None:
        """Initialise from the subentry's chosen headcode / unique_identity."""
        self._subentry_id = subentry_id
        self._subentry = subentry
        self._account = account
        data = subentry.data
        self.unique_identity: str | None = data.get(CONF_UNIQUE_IDENTITY)
        self.headcode: str | None = data.get(CONF_HEADCODE)
        self.departure_date: str | None = data.get(CONF_DATE)
        self.namespace: str = data.get(CONF_NAMESPACE, DEFAULT_NAMESPACE)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_service_{subentry_id}",
            update_interval=SERVICE_POLL_SCHEDULED,
            config_entry=config_entry,
        )
        self._empty = ServiceTrackerData(
            unique_identity=self.unique_identity,
            headcode=self.headcode,
            departure=None,
            arrival=None,
            live_status=None,
            delay=None,
            is_cancelled=None,
            display_as=None,
            formation=None,
            know_your_train=None,
        )

    @property
    def subentry_id(self) -> str:
        """Return the subentry id this coordinator backs."""
        return self._subentry_id

    async def _async_update_data(self) -> ServiceTrackerData:
        try:
            if self.unique_identity:
                service = await self._account.serialise(
                    self._account.api.async_get_service,
                    self.unique_identity,
                    namespace=self.namespace,
                )
            else:
                # No resolved unique_identity (e.g. the API couldn't supply
                # one at add-time). Fall back to the headcode + date the user
                # entered rather than sending an empty uniqueIdentity.
                service = await self._account.serialise(
                    self._account.api.async_get_service,
                    identity=self.headcode,
                    departure_date=self.departure_date,
                    namespace=self.namespace,
                )
        except RttAuthError as err:
            raise _raise_auth() from err
        except RttError as err:
            raise _translate(err) from err
        # The tracker only ever uses /gb-nr/service (allocator + KYT data).
        # If the namespace were ever changed to the generic endpoint, this
        # would be a ServiceDetail without ``allocation_data``; treat that
        # as an empty service for safety.
        nr_service = service if isinstance(service, NetworkRailServiceDetail) else None
        if nr_service is None:
            return self._empty
        sm = nr_service.schedule_metadata
        headcode = getattr(sm, "train_reporting_identity", None) if sm else None
        uid = sm.unique_identity if sm else self.unique_identity
        locations = nr_service.locations
        departure: datetime | None = None
        arrival: datetime | None = None
        if locations:
            first = locations[0]
            last = locations[-1]
            if (
                first.temporal_data is not None
                and first.temporal_data.departure is not None
            ):
                departure = (
                    first.temporal_data.departure.realtime_actual
                    or first.temporal_data.departure.schedule_advertised
                )
            if (
                last.temporal_data is not None
                and last.temporal_data.arrival is not None
            ):
                arrival = (
                    last.temporal_data.arrival.realtime_actual
                    or last.temporal_data.arrival.realtime_forecast
                    or last.temporal_data.arrival.schedule_advertised
                )
        live_status: LocationStatus | None = None
        delay: int | None = None
        is_cancelled: bool | None = None
        display_as: LocationDisplayAs | None = None
        for loc in locations:
            td = loc.temporal_data
            if td is None:
                continue
            if td.status is not None:
                live_status = td.status
            if td.arrival is not None:
                if td.arrival.realtime_advertised_lateness is not None:
                    delay = td.arrival.realtime_advertised_lateness
                if td.arrival.is_cancelled is not None:
                    is_cancelled = td.arrival.is_cancelled
            if td.display_as is not None and display_as is None:
                display_as = td.display_as
        formation = (
            list(nr_service.allocation_data) if nr_service.allocation_data else None
        )
        kyt = None
        if formation:
            for alloc in formation:
                if getattr(alloc, "know_your_train_data", None) is not None:
                    kyt = alloc.know_your_train_data
                    break
        # Adapt polling cadence to the service state.
        self._update_interval_for_state(live_status, is_cancelled)
        return ServiceTrackerData(
            unique_identity=uid,
            headcode=headcode,
            departure=departure,
            arrival=arrival,
            live_status=live_status,
            delay=delay,
            is_cancelled=is_cancelled,
            display_as=display_as,
            formation=formation,
            know_your_train=kyt,
        )

    def _update_interval_for_state(
        self, status: LocationStatus | None, is_cancelled: bool | None
    ) -> None:
        """Choose the next poll interval based on the service's live state."""
        if is_cancelled is True:
            self.update_interval = SERVICE_POLL_TERMINAL
            return
        if status is None:
            self.update_interval = SERVICE_POLL_SCHEDULED
            return
        self.update_interval = SERVICE_POLL_IN_RUN

    @property
    def empty_data(self) -> ServiceTrackerData:
        """Return the empty-state data used when no service detail exists."""
        return self._empty


# Re-exports for the sensor platform.
__all__ = [
    "AccountData",
    "BoardData",
    "DepartureSlot",
    "RealtimeTrainsAccountCoordinator",
    "RealtimeTrainsBoardCoordinator",
    "RealtimeTrainsConfigEntry",
    "RealtimeTrainsRuntimeData",
    "RealtimeTrainsServiceTrackerCoordinator",
    "ServiceTrackerData",
]
