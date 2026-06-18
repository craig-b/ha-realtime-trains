"""Subentry flows for the Realtime Trains integration.

Two subentry types are declared by ``RealtimeTrainsConfigFlow``
(see ``config_flow.py``):

* ``departure_board`` — a station, optional filter-from/to, time
  window and board-level options. Surface for adding a board is the
  device page's *Add departure board* action.
* ``service_tracker`` — follows a single train by headcode+date or
  full ``uniqueIdentity``.

Both flows access the parent account's coordinator via
``self._get_entry().runtime_data`` for station search and train
verification — they never go to the API directly.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    CONF_DATE,
    CONF_DEFAULT_SLOT_COUNT,
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
    MAX_POLLING_INTERVAL,
    MAX_SLOT_COUNT,
    MAX_TIME_WINDOW,
    MIN_POLLING_INTERVAL,
    MIN_SLOT_COUNT,
    MIN_TIME_WINDOW,
    SUBENTRY_TYPE_DEPARTURE_BOARD,
    SUBENTRY_TYPE_SERVICE_TRACKER,
)
from .coordinator import RealtimeTrainsAccountCoordinator
from .models import Stop

_LOGGER = logging.getLogger(__name__)

# --- Departure board -------------------------------------------------------


_BOARD_STEP1_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATION): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.TEXT,
            )
        ),
        vol.Optional(CONF_FILTER_FROM): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_FILTER_TO): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_TIME_WINDOW, default=DEFAULT_TIME_WINDOW): NumberSelector(
            NumberSelectorConfig(
                min=MIN_TIME_WINDOW,
                max=MAX_TIME_WINDOW,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_SLOT_COUNT): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SLOT_COUNT,
                max=MAX_SLOT_COUNT,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_POLLING_INTERVAL, default=DEFAULT_POLLING_INTERVAL
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_POLLING_INTERVAL,
                max=MAX_POLLING_INTERVAL,
                step=10,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_DETAILED, default=False): bool,
    }
)


def _select_selector_for_stops(stops: list[Stop]) -> SelectSelector:
    options = [
        {
            "label": (
                f"{stop.description or stop.short_code or stop.unique_identity}"
                + (f" ({stop.short_code})" if stop.short_code else "")
            ),
            "value": stop.unique_identity or stop.short_code or "",
        }
        for stop in stops
        if stop.unique_identity or stop.short_code
    ]
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            multiple=False,
        )
    )


def _select_schema(stops: list[Stop]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STATION): _select_selector_for_stops(stops),
        }
    )


class DepartureBoardSubentryFlow(ConfigSubentryFlow):
    """Subentry flow for adding a departure board."""

    def __init__(self) -> None:
        """Initialise per-flow state."""
        super().__init__()
        self._station_matches: list[Stop] = []
        self._partial_user_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """First step: collect a station fragment plus board options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            fragment = user_input.get(CONF_STATION, "").strip()
            coordinator = self._coordinator()
            if coordinator is None:
                errors["base"] = "account_not_ready"
            elif not fragment:
                errors["base"] = "station_required"
            else:
                try:
                    matches = await coordinator.fetch_stops(fragment, limit=60)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Station search failed for %r: %s", fragment, err)
                    errors["base"] = "cannot_connect"
                else:
                    if not matches:
                        errors["base"] = "no_station_matches"
                    elif len(matches) == 1:
                        return self._finish_with_station(matches[0], user_input)
                    else:
                        self._station_matches = matches
                        self._partial_user_input = user_input
                        return await self.async_step_pick_station()
            # When validation fails, re-render with preserved partial input.
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    _BOARD_STEP1_SCHEMA, suggested_values=user_input
                ),
                errors=errors,
            )
        return self.async_show_form(step_id="user", data_schema=_BOARD_STEP1_SCHEMA)

    async def async_step_pick_station(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Second step: pick the exact station when the search returned multiple."""
        if user_input is not None:
            picked = user_input.get(CONF_STATION)
            station = next(
                (
                    s
                    for s in self._station_matches
                    if (s.unique_identity or s.short_code) == picked
                ),
                None,
            )
            if station is None:
                return self.async_show_form(
                    step_id="pick_station",
                    data_schema=_select_schema(self._station_matches),
                    errors={"base": "station_invalid"},
                )
            return self._finish_with_station(station, self._partial_user_input)
        return self.async_show_form(
            step_id="pick_station",
            data_schema=_select_schema(self._station_matches),
            description_placeholders={"station_count": str(len(self._station_matches))},
        )

    def _finish_with_station(
        self, station: Stop, partial: dict[str, Any]
    ) -> SubentryFlowResult:
        data = dict(partial)
        # Replace the fragment/search-text in user input with the canonical
        # unique_identity (which is the long-code form e.g. ``gb-nr:CLJ``);
        # store a friendly description for the device title.
        station_code = station.short_code or station.unique_identity or ""
        data[CONF_STATION] = station_code
        data[CONF_STATION_DESCRIPTION] = station.description or station_code
        # Fall back to the account-level default for slot_count if not set.
        data.setdefault(CONF_SLOT_COUNT, self._account_default_slot_count())
        title = station.description or station_code or "Departure board"
        return self.async_create_entry(title=title, data=data)

    def _coordinator(self) -> RealtimeTrainsAccountCoordinator | None:
        entry = self._get_entry()
        runtime = getattr(entry, "runtime_data", None)
        if isinstance(runtime, RealtimeTrainsAccountCoordinator):
            return runtime
        return None

    def _account_default_slot_count(self) -> int:
        entry = self._get_entry()
        try:
            return int(entry.data.get(CONF_DEFAULT_SLOT_COUNT, DEFAULT_SLOT_COUNT))
        except TypeError, ValueError:
            return DEFAULT_SLOT_COUNT


# --- Service tracker -------------------------------------------------------


_SERVICE_STEP1_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_UNIQUE_IDENTITY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_HEADCODE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_DATE): DateSelector(),
    }
)


class ServiceTrackerSubentryFlow(ConfigSubentryFlow):
    """Subentry flow for adding a single-train tracker."""

    def __init__(self) -> None:
        """Initialise per-flow state."""
        super().__init__()
        self._partial_input: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Collect headcode + date (or unique_identity) and verify the service."""
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = self._coordinator()
            unique_identity = (user_input.get(CONF_UNIQUE_IDENTITY) or "").strip()
            headcode = (user_input.get(CONF_HEADCODE) or "").strip()
            date = (user_input.get(CONF_DATE) or "").strip()
            if coordinator is None:
                errors["base"] = "account_not_ready"
            elif not unique_identity and not headcode:
                errors["base"] = "headcode_required"
            else:
                try:
                    if unique_identity:
                        service = await coordinator.serialise(
                            coordinator.api.async_get_service,
                            unique_identity,
                            namespace=DEFAULT_NAMESPACE,
                        )
                    else:
                        service = await coordinator.serialise(
                            coordinator.api.async_get_service,
                            identity=headcode,
                            departure_date=date,
                            namespace=DEFAULT_NAMESPACE,
                        )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Service lookup failed: %s", err)
                    errors["base"] = "service_not_found"
                else:
                    sm = getattr(service, "schedule_metadata", None)
                    resolved = getattr(sm, "unique_identity", None) or unique_identity
                    title = self._tracker_title(
                        headcode=headcode
                        or (resolved.split(":")[1] if ":" in resolved else ""),
                        date=date
                        or (
                            resolved.split(":")[2]
                            if resolved.count(":") >= 2  # noqa: PLR2004
                            else ""
                        ),
                        unique_identity=resolved,
                    )
                    data = {
                        CONF_UNIQUE_IDENTITY: resolved,
                        CONF_HEADCODE: headcode,
                        CONF_DATE: date,
                        CONF_NAMESPACE: DEFAULT_NAMESPACE,
                    }
                    return self.async_create_entry(title=title, data=data)
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    _SERVICE_STEP1_SCHEMA, suggested_values=user_input
                ),
                errors=errors,
            )
        return self.async_show_form(step_id="user", data_schema=_SERVICE_STEP1_SCHEMA)

    def _tracker_title(self, *, headcode: str, date: str, unique_identity: str) -> str:
        # ``unique_identity`` is shaped ``namespace:identity:date`` so the
        # second colon separates the date; the headcode half is at index 1.
        if headcode:
            headcode_part = headcode
        elif ":" in unique_identity:
            headcode_part = unique_identity.split(":")[1]
        else:
            headcode_part = unique_identity
        if date:
            date_part = date
        elif unique_identity.count(":") >= 2:  # noqa: PLR2004
            date_part = unique_identity.split(":")[2]
        else:
            date_part = ""
        if headcode_part and date_part:
            return f"{headcode_part} {date_part}"
        return headcode_part or unique_identity or "Service tracker"

    def _coordinator(self) -> RealtimeTrainsAccountCoordinator | None:
        entry = self._get_entry()
        runtime = getattr(entry, "runtime_data", None)
        if isinstance(runtime, RealtimeTrainsAccountCoordinator):
            return runtime
        return None


# Re-exported for tests + config_flow module's lazy import.
__all__ = [
    "DOMAIN",
    "SUBENTRY_TYPE_DEPARTURE_BOARD",
    "SUBENTRY_TYPE_SERVICE_TRACKER",
    "DepartureBoardSubentryFlow",
    "ServiceTrackerSubentryFlow",
]
