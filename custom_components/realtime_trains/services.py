"""Service registration for the Realtime Trains integration.

Four services are exposed, all returning a
:class:`~homeassistant.core.ServiceResponse`:

* ``get_departures`` — fetch a board on demand for an account
* ``get_service``    — fetch full service detail (with formation/KYT if
  the account is entitled)
* ``find_station``   — search the cached RTT stops list offline
* ``refresh_now``    — force an immediate refresh of one board/service
  tracker device

API errors raised by the client are translated to
:class:`~homeassistant.exceptions.ServiceValidationError` so the user
sees a localised message via the action's translation key.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.const import ATTR_CONFIG_ENTRY_ID, ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, service
from homeassistant.helpers.selector import (
    ConfigEntrySelector,
    DateSelector,
    DateSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol

from .api import (
    RealtimeTrainsApi,
    RttAuthError,
    RttBadRequestError,
    RttConnectionError,
    RttError,
    RttNotFoundError,
    RttRateLimitError,
)
from .const import (
    DEFAULT_NAMESPACE,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
    MAX_QUERY_WINDOW_MINUTES,
    MAX_TIME_WINDOW,
    MIN_TIME_WINDOW,
)
from .coordinator import (
    RealtimeTrainsAccountCoordinator,
    RealtimeTrainsConfigEntry,
    RealtimeTrainsRuntimeData,
)
from .models import (
    GeographicLocation,
    LocationLineUp,
    LocationPair,
    NetworkRailLocationLineUp,
    Stop,
)

_LOGGER = logging.getLogger(__name__)

FIELD_UNIQUE_IDENTITY = "unique_identity"
FIELD_DATE = "date"
FIELD_HEADCODE = "headcode"
FIELD_NAMESPACE = "namespace"
FIELD_STATION = "station"
FIELD_TIME_FROM = "time_from"
FIELD_TIME_TO = "time_to"
FIELD_TIME_WINDOW = "time_window"
FIELD_FILTER_FROM = "filter_from"
FIELD_FILTER_TO = "filter_to"
FIELD_DETAILED = "detailed"
FIELD_LIMIT = "limit"
FIELD_QUERY = "query"
DEFAULT_LIMIT = 10
DEFAULT_FIND_LIMIT = 10
MAX_LIMIT = 50


SERVICE_GET_DEPARTURES = "get_departures"
SERVICE_GET_SERVICE = "get_service"
SERVICE_FIND_STATION = "find_station"
SERVICE_REFRESH_NOW = "refresh_now"


# --- Schemas ----------------------------------------------------------------


def _datetime_selector() -> TextSelector:
    """A datetime selector using text entry (ISO 8601)."""
    return TextSelector(TextSelectorConfig(multiple=False))


_GET_DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector(),
        vol.Required(FIELD_STATION): TextSelector(TextSelectorConfig(multiple=False)),
        vol.Optional(FIELD_TIME_FROM): _datetime_selector(),
        vol.Exclusive(FIELD_TIME_TO, "time_window"): _datetime_selector(),
        vol.Exclusive(FIELD_TIME_WINDOW, "time_window"): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_TIME_WINDOW, max=MAX_TIME_WINDOW),
        ),
        vol.Optional(FIELD_FILTER_FROM): str,
        vol.Optional(FIELD_FILTER_TO): str,
        vol.Optional(FIELD_DETAILED, default=False): bool,
        vol.Optional(FIELD_LIMIT, default=DEFAULT_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
        ),
    }
)


_GET_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector(),
        vol.Exclusive(FIELD_UNIQUE_IDENTITY, "service_id"): str,
        vol.Exclusive(FIELD_HEADCODE, "service_id"): str,
        vol.Optional(FIELD_NAMESPACE, default=DEFAULT_NAMESPACE): str,
        vol.Optional(FIELD_DATE): DateSelector(DateSelectorConfig()),
    }
)


_FIND_STATION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): ConfigEntrySelector(),
        vol.Optional(FIELD_QUERY): str,
        vol.Optional(FIELD_NAMESPACE): str,
        vol.Optional(FIELD_LIMIT, default=DEFAULT_FIND_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
        ),
    }
)


_REFRESH_NOW_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
    }
)


# --- Error translation ------------------------------------------------------


def _raise_for(err: Exception) -> None:
    """Translate an RTT client error into a ServiceValidationError."""
    if isinstance(err, RttAuthError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
            translation_placeholders={"detail": str(err)},
        ) from err
    if isinstance(err, RttRateLimitError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="rate_limited",
            translation_placeholders={"detail": str(err)},
        ) from err
    if isinstance(err, RttNotFoundError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_found",
            translation_placeholders={"detail": str(err)},
        ) from err
    if isinstance(err, RttBadRequestError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="bad_request",
            translation_placeholders={"detail": str(err)},
        ) from err
    if isinstance(err, RttConnectionError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"detail": str(err)},
        ) from err
    if isinstance(err, RttError):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown",
            translation_placeholders={"detail": str(err)},
        ) from err
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown",
        translation_placeholders={"detail": str(err) or repr(err)},
    ) from err


# --- Account + client access ------------------------------------------------


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> RealtimeTrainsConfigEntry:
    """Fetch the config entry referenced by a service call.

    Raises a ServiceValidationError with translation_key=config_entry_not_found
    if the entry does not exist.
    """
    entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
    try:
        entry: RealtimeTrainsConfigEntry = service.async_get_config_entry(
            call.hass, DOMAIN, entry_id
        )
    except (ValueError, HomeAssistantError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="config_entry_not_found",
            translation_placeholders={"entry_id": str(entry_id)},
        ) from err
    if entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="config_entry_not_found",
            translation_placeholders={"entry_id": str(entry_id)},
        )
    return entry


def _runtime(entry: RealtimeTrainsConfigEntry) -> RealtimeTrainsRuntimeData:
    """Return the runtime data on the entry or raise."""
    runtime_data: RealtimeTrainsRuntimeData | None = getattr(
        entry, "runtime_data", None
    )
    if runtime_data is None or runtime_data.account is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="account_not_ready",
        )
    return runtime_data


def _client(runtime_data: RealtimeTrainsRuntimeData) -> RealtimeTrainsApi:
    return runtime_data.account.api


# --- Service handlers -------------------------------------------------------


async def _async_get_departures(call: ServiceCall) -> dict[str, Any] | None:
    """Fetch a departure board on demand for the chosen account."""
    hass = call.hass
    entry = _resolve_entry(hass, call)
    runtime_data = _runtime(entry)
    account: RealtimeTrainsAccountCoordinator = runtime_data.account
    client = _client(runtime_data)

    # User may pass either "gb-nr:CLPHMJN" or "CLPHMJN" with explicit namespace.
    raw_code: str = call.data[FIELD_STATION]
    namespace = DEFAULT_NAMESPACE
    if ":" in raw_code:
        ns_part, _, code_part = raw_code.partition(":")
        namespace, raw_code = ns_part, code_part

    time_from = _coerce_dt(call.data.get(FIELD_TIME_FROM))
    time_to = _coerce_dt(call.data.get(FIELD_TIME_TO))
    time_window = call.data.get(FIELD_TIME_WINDOW)
    if time_to is not None:
        time_window = None
    elif time_window is None:
        time_window = DEFAULT_TIME_WINDOW
    if time_from is not None and time_to is not None:
        delta = (time_to - time_from).total_seconds()
        if delta > MAX_QUERY_WINDOW_MINUTES * 60:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="window_too_large",
            )

    try:
        response = await account.serialise(
            client.async_get_location,
            raw_code,
            filter_from=call.data.get(FIELD_FILTER_FROM),
            filter_to=call.data.get(FIELD_FILTER_TO),
            time_from=time_from,
            time_to=time_to,
            time_window=int(time_window) if time_window is not None else None,
            detailed=call.data[FIELD_DETAILED] or None,
            namespace=namespace,
        )
    except RttError as err:
        _raise_for(err)
        return None  # pragma: no cover
    except Exception as err:  # noqa: BLE001
        _raise_for(err)
        return None  # pragma: no cover

    services: list[Any] = getattr(response, "services", []) or []
    limit = int(call.data[FIELD_LIMIT])
    payload = [_lineup_to_dict(svc) for svc in services[:limit]]
    query_block: dict[str, Any] = {
        "code": raw_code,
        "namespace": namespace,
        "time_from": _iso(time_from),
        "time_to": _iso(time_to),
        # Report the *effective* window (``time_window`` is optional in the
        # schema, so reading it back off ``call.data`` would KeyError, and it
        # is cleared above when an explicit ``time_to`` is supplied).
        "time_window": time_window,
    }
    return {"services": payload, "query": _strip_none(query_block)}


async def _async_get_service(call: ServiceCall) -> dict[str, Any] | None:
    """Fetch full detail for a single service."""
    entry = _resolve_entry(call.hass, call)
    runtime_data = _runtime(entry)
    client = _client(runtime_data)

    unique_identity: str | None = call.data.get(FIELD_UNIQUE_IDENTITY)
    headcode: str | None = call.data.get(FIELD_HEADCODE)
    namespace = call.data.get(FIELD_NAMESPACE) or DEFAULT_NAMESPACE

    if not unique_identity and not headcode:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="service_id_required",
        )
    if headcode and not call.data.get(FIELD_DATE):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="date_required_with_headcode",
        )

    try:
        detail = await runtime_data.account.serialise(
            client.async_get_service,
            unique_identity,
            identity=headcode,
            departure_date=call.data.get(FIELD_DATE),
            namespace=namespace,
        )
    except RttError as err:
        _raise_for(err)
        return None  # pragma: no cover
    except Exception as err:  # noqa: BLE001
        _raise_for(err)
        return None  # pragma: no cover

    return {"service": _service_to_dict(detail)}


async def _async_find_station(call: ServiceCall) -> dict[str, Any] | None:
    """Search the cached RTT stops list without network I/O."""
    # find_station has no mandatory config_entry_id, but when supplied we
    # use that entry's account. Otherwise the first ready one.
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        entry = _resolve_entry(call.hass, call)
        runtime_data = _runtime(entry)
        stops = await runtime_data.account.refresh_stops()
    else:
        stops = await _stops_from_any_account(call.hass)

    query = (call.data.get(FIELD_QUERY) or "").lower().strip()
    namespace = call.data.get(FIELD_NAMESPACE)
    limit = int(call.data[FIELD_LIMIT])

    results: list[dict[str, Any]] = []
    for stop in stops:
        if namespace and stop.namespace != namespace:
            continue
        if query and not _stop_matches(stop, query):
            continue
        results.append(_stop_to_dict(stop))
        if len(results) >= limit:
            break

    return {"stops": results}


async def _async_refresh_now(call: ServiceCall) -> dict[str, Any] | None:
    """Force an immediate refresh of one board or service tracker device."""
    device_id: str = call.data[ATTR_DEVICE_ID]
    registry = dr.async_get(call.hass)
    device = registry.async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )

    subentry_id = _subentry_id_from_device(device)
    if subentry_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_a_subentry",
            translation_placeholders={"device_id": device_id},
        )

    config_entry_id = next(iter(device.config_entries), None)
    if config_entry_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_a_subentry",
            translation_placeholders={"device_id": device_id},
        )
    entry = call.hass.config_entries.async_get_entry(config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_a_subentry",
            translation_placeholders={"device_id": device_id},
        )

    runtime_data: RealtimeTrainsRuntimeData | None = getattr(
        entry, "runtime_data", None
    )
    if runtime_data is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="account_not_ready",
        )
    coordinator = runtime_data.subentry_coordinators.get(subentry_id)
    if coordinator is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="coordinator_not_found",
            translation_placeholders={"subentry_id": subentry_id},
        )

    # ``async_refresh`` awaits the poll, stores the result on the coordinator
    # and notifies entities (unlike ``_async_update_data``, which discards its
    # result). It swallows update errors into ``last_update_success`` rather
    # than raising, so re-surface any failure to the caller afterwards.
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _raise_for(coordinator.last_exception or RttError("Refresh failed"))
        return None  # pragma: no cover
    return {"ok": True}


async def _stops_from_any_account(hass: HomeAssistant) -> list[Stop]:
    """Refresh stops from the first ready RTT account entry.

    Falls back to an empty list if no account is set up yet.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data: RealtimeTrainsRuntimeData | None = getattr(
            entry, "runtime_data", None
        )
        if runtime_data is None or runtime_data.account is None:
            continue
        return await runtime_data.account.refresh_stops()
    return []


# --- Serialisation helpers --------------------------------------------------


def _lineup_to_dict(
    svc: LocationLineUp | NetworkRailLocationLineUp,
) -> dict[str, Any] | None:
    """Reduce a line-up entry to a response dict.

    Mirrors the departure-slot attributes documented in docs/entities.md.
    """
    sched = svc.schedule_metadata
    headcode = getattr(sched, "train_reporting_identity", None) if sched else None
    operator = sched.operator if sched else None
    metadata = svc.location_metadata
    platform_planned = (
        metadata.platform.planned
        if metadata is not None and metadata.platform is not None
        else None
    )
    platform_actual = (
        metadata.platform.actual
        if metadata is not None and metadata.platform is not None
        else None
    )
    td = svc.temporal_data
    departure_dt = (
        td.departure.schedule_advertised
        if td is not None and td.departure is not None
        else None
    )
    arrival_dt = (
        td.arrival.schedule_advertised
        if td is not None and td.arrival is not None
        else None
    )
    delay = (
        td.departure.realtime_advertised_lateness
        if td is not None and td.departure is not None
        else None
    )
    is_cancelled = (
        td.departure.is_cancelled
        if td is not None and td.departure is not None
        else None
    )
    live_status = (
        str(td.status).lower() if td is not None and td.status is not None else None
    )
    uid = sched.unique_identity if sched else None
    ns = sched.namespace if sched else None
    mode = (
        str(sched.mode_type).lower() if sched and sched.mode_type is not None else None
    )
    return _strip_none(
        {
            "headcode": headcode,
            "origin": _first_location_description(svc.origin),
            "destination": _first_location_description(svc.destination),
            "departure": _iso(departure_dt),
            "arrival": _iso(arrival_dt),
            "delay": delay,
            "platform_planned": platform_planned,
            "platform_actual": platform_actual,
            "is_cancelled": is_cancelled,
            "live_status": live_status,
            "operator_code": operator.code if operator else None,
            "operator_name": operator.name if operator else None,
            "unique_identity": uid,
            "namespace": ns,
            "mode": mode,
        }
    )


def _service_to_dict(detail: Any) -> dict[str, Any] | None:
    """Serialise a NetworkRailServiceDetail / ServiceDetail for the response."""
    return asdict(detail)


def _stop_to_dict(stop: Stop) -> dict[str, Any]:
    """Reduce a Stop to a compact dict for the find_station response."""
    return {
        "namespace": stop.namespace,
        "description": stop.description,
        "short_code": stop.short_code,
        "unique_identity": stop.unique_identity,
    }


def _stop_matches(stop: Stop, query: str) -> bool:
    """Match a query string against description or codes (case-insensitive)."""
    query = query.lower()
    description = (stop.description or "").lower()
    short_code = (stop.short_code or "").lower()
    unique_identity = (stop.unique_identity or "").lower()
    return query in description or query in short_code or query in unique_identity


def _first_location_description(locations: list[LocationPair]) -> str | None:
    """Pick the first pair's location description, if any."""
    if not locations:
        return None
    first = locations[0]
    loc: GeographicLocation | None = first.location
    if loc is None:
        return None
    return loc.description


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _strip_none(d: dict[str, Any]) -> dict[str, Any] | None:
    return {k: v for k, v in d.items() if v is not None}


def _subentry_id_from_device(device: dr.DeviceEntry) -> str | None:
    """Extract the subentry_id encoded in one of the device's identifiers."""
    for identifier in device.identifiers:
        if identifier[0] != DOMAIN:
            continue
        value = identifier[1]
        if value.startswith("board:"):
            return value[len("board:") :]
        if value.startswith("service:"):
            return value[len("service:") :]
    return None


def _coerce_dt(value: Any) -> datetime | None:
    """Parse a user-supplied ISO 8601 string or pass through a datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    # ``fromisoformat`` accepts the offset forms HA's datetime selectors emit.
    try:
        return datetime.fromisoformat(text)
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="bad_datetime",
            translation_placeholders={"value": text},
        ) from err


# --- Public registration entry point ----------------------------------------


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register all realtime_trains services.

    ``hass.services.async_register`` is idempotent — re-registering on
    reload just replaces the handler, so no manual guard is needed.
    """
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        _async_get_departures,
        schema=_GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SERVICE,
        _async_get_service,
        schema=_GET_SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_STATION,
        _async_find_station,
        schema=_FIND_STATION_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_NOW,
        _async_refresh_now,
        schema=_REFRESH_NOW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove all realtime_trains services.

    Called when the final account entry unloads so the integration leaves
    no orphaned services behind that would call into torn-down runtime.
    """
    for service_name in (
        SERVICE_GET_DEPARTURES,
        SERVICE_GET_SERVICE,
        SERVICE_FIND_STATION,
        SERVICE_REFRESH_NOW,
    ):
        hass.services.async_remove(DOMAIN, service_name)
