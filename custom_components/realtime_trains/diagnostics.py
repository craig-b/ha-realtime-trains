"""Diagnostics support for the Realtime Trains integration.

Two diagnostic dumps are exposed:

* ``async_get_config_entry_diagnostics`` — the full account snapshot
  (config entry data with token redacted, /api/info payload, the last
  rate-limit snapshot, and a summary of every board / service-tracker
  subentry).
* ``async_get_device_diagnostics`` — one board or service tracker's
  latest polled data plus its last response headers (with
  ``Authorization`` / ``Cookie`` / ``Set-Cookie`` redacted).

Nothing in either dump ever contains the bearer token in plaintext.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import (
    RealtimeTrainsBoardCoordinator,
    RealtimeTrainsConfigEntry,
    RealtimeTrainsRuntimeData,
    RealtimeTrainsServiceTrackerCoordinator,
)

# Keys redacted wherever they appear in any dict surfaced by diagnostics.
TO_REDACT = {
    CONF_TOKEN,
    "token",
    "Authorization",
    "Cookie",
    "Set-Cookie",
    "accessToken",
    "refreshToken",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RealtimeTrainsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Realtime Trains account config entry."""
    runtime_data: RealtimeTrainsRuntimeData | None = getattr(
        entry, "runtime_data", None
    )
    if runtime_data is None or runtime_data.account is None:
        return {
            "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
            "runtime_data": None,
            "subentry_coordinators": {},
        }

    account = runtime_data.account
    api_info: dict[str, Any] | list[Any] | None = None
    if account.data is not None and account.data.api_info is not None:
        api_info = _redact(asdict(account.data.api_info))

    subentries: dict[str, Any] = {}
    for subentry_id, coordinator in runtime_data.subentry_coordinators.items():
        subentries[subentry_id] = _summarise_coordinator(coordinator)

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "account": {
            "name": account.name,
            "update_interval": str(account.update_interval)
            if account.update_interval
            else None,
            "api_info": api_info,
            "rate_limits": _redact(asdict(account.api.rate_limits)),
            "last_response_headers": _redact(dict(account.api.last_response_headers)),
            "is_refresh_token": account.api.is_refresh_token,
            "stops_count": len(account.data.stops) if account.data else 0,
        },
        "subentry_coordinators": subentries,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for one board or service tracker device."""
    runtime_data: RealtimeTrainsRuntimeData | None = getattr(
        entry, "runtime_data", None
    )
    if runtime_data is None:
        return {
            "entry_id": entry.entry_id,
            "device_id": device.id,
            "runtime_data": None,
        }

    subentry_id = _subentry_id_from_device(device)
    coordinator = (
        runtime_data.subentry_coordinators.get(subentry_id)
        if subentry_id is not None
        else None
    )

    if coordinator is None:
        return {
            "entry_id": entry.entry_id,
            "device_id": device.id,
            "subentry_id": subentry_id,
            "coordinator": None,
        }

    return {
        "entry_id": entry.entry_id,
        "device_id": device.id,
        "subentry_id": subentry_id,
        "coordinator": _summarise_coordinator(coordinator, include_data=True),
    }


# --- Helpers ---------------------------------------------------------------


def _summarise_coordinator(
    coordinator: RealtimeTrainsBoardCoordinator
    | RealtimeTrainsServiceTrackerCoordinator,
    *,
    include_data: bool = False,
) -> dict[str, Any]:
    """Build a coordinator summary; optionally include full polled data."""
    summary: dict[str, Any] = {
        "name": coordinator.name,
        "update_interval": str(coordinator.update_interval)
        if coordinator.update_interval
        else None,
        "last_update_success": coordinator.last_update_success,
        "last_exception": _stringify_exception(coordinator.last_exception),
    }
    if isinstance(coordinator, RealtimeTrainsBoardCoordinator):
        summary["kind"] = "departure_board"
        summary["station"] = coordinator.station_code
        summary["slot_count"] = coordinator.slot_count
        if include_data and coordinator.data is not None:
            summary["data"] = _redact(asdict(coordinator.data))
    elif isinstance(coordinator, RealtimeTrainsServiceTrackerCoordinator):
        summary["kind"] = "service_tracker"
        summary["headcode"] = coordinator.headcode
        summary["unique_identity"] = coordinator.unique_identity
        summary["departure_date"] = coordinator.departure_date
        if include_data and coordinator.data is not None:
            summary["data"] = _redact(asdict(coordinator.data))
    return summary


def _subentry_id_from_device(device: DeviceEntry) -> str | None:
    """Extract subentry_id from a board:/service: device identifier."""
    for identifier in device.identifiers:
        if identifier[0] != DOMAIN:
            continue
        value = identifier[1]
        if value.startswith("board:"):
            return value[len("board:") :]
        if value.startswith("service:"):
            return value[len("service:") :]
    return None


def _redact(payload: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    """Recursively redact sensitive keys anywhere in a nested structure."""
    if isinstance(payload, dict):
        redacted = dict(payload)
        for key in list(redacted.keys()):
            if key in TO_REDACT:
                redacted[key] = "**REDACTED**"
            else:
                redacted[key] = _redact(redacted[key])
        return redacted
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    return payload


def _stringify_exception(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    return f"{type(exc).__name__}: {exc}"
