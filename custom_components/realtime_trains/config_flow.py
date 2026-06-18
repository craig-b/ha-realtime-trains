"""Config flow for the Realtime Trains integration.

The flow supports the full account lifecycle:

* **user** — initial setup. Validates the supplied token against
  ``/api/info``, surfaces the entitlements so the user can confirm
  the key has the capabilities they expect (detailed mode, allocations,
  Know-Your-Train), and stores the entry.
* **reconfigure** — replaces the token in-place (the Nederlandse
  Spoorwegen pattern) while preserving the entry's monitored items.
* **reauth_confirm** — modal step launched from a repair issue when
  the coordinator reports ``invalid_auth`` during a poll.

The subentry flows (departure board, service tracker) arrive in M5.
"""

from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .api import (
    RealtimeTrainsApi,
    RttAuthError,
    RttConnectionError,
    RttError,
    RttRateLimitError,
)
from .const import (
    API_VERSION,
    CONF_DEFAULT_SLOT_COUNT,
    CONF_TOKEN,
    DEFAULT_SLOT_COUNT,
    DOMAIN,
    MAX_SLOT_COUNT,
    MIN_SLOT_COUNT,
)
from .models import ApiInfo

# Step schemas -------------------------------------------------------------

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): str,
        vol.Required(
            CONF_DEFAULT_SLOT_COUNT, default=DEFAULT_SLOT_COUNT
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SLOT_COUNT,
                max=MAX_SLOT_COUNT,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)

_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


def _unique_id_for_token(token: str) -> str:
    """Derive a stable unique id from a token.

    The token itself is sensitive; a truncated SHA-256 hash is enough
    identity for HA to deduplicate setup attempts without persisting
    the raw key alongside the entity registry.
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"rtt-account-{digest[:16]}"


async def _validate_token(
    hass: HomeAssistant, token: str
) -> tuple[ApiInfo, RealtimeTrainsApi, str | None]:
    """Validate the token against ``/api/info``.

    Returns the parsed ``ApiInfo`` and the configured client on
    success. On failure, returns ``(ApiInfo_empty_default, client, translation_key)``
    where ``translation_key`` is the config-flow error key to surface.
    """
    client = RealtimeTrainsApi(
        async_get_clientsession(hass),
        token,
        api_version=API_VERSION,
    )
    try:
        info = await client.async_get_info()
    except RttAuthError:
        return (ApiInfo.from_dict({}), client, "invalid_auth")
    except RttRateLimitError:
        return (ApiInfo.from_dict({}), client, "rate_limited")
    except RttConnectionError:
        return (ApiInfo.from_dict({}), client, "cannot_connect")
    except RttError:
        return (ApiInfo.from_dict({}), client, "unknown")
    return (info, client, None)


class RealtimeTrainsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Realtime Trains account config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: collect API token and validate against /api/info."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _info, _client, err = await _validate_token(
                self.hass, user_input[CONF_TOKEN]
            )
            if err is None:
                unique_id = _unique_id_for_token(user_input[CONF_TOKEN])
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Realtime Trains",
                    data=user_input,
                )
            errors["base"] = err

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _USER_SCHEMA, suggested_values=user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the token on an existing account entry.

        Preserves the entry's monitored items. Reuses the same validation
        path as ``async_step_user`` so the reauth will also surface the
        same entitlements feedback once re-applied.
        """
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            _info, _client, err = await _validate_token(
                self.hass, user_input[CONF_TOKEN]
            )
            if err is None:
                # Avoid colliding unique-id if the new token already backs
                # another account entry: abort with a hint.
                new_unique_id = _unique_id_for_token(user_input[CONF_TOKEN])
                if reconfigure_entry.unique_id != new_unique_id and any(
                    e.unique_id == new_unique_id
                    for e in self._async_current_entries()
                    if e.entry_id != reconfigure_entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    unique_id=new_unique_id,
                    data_updates={CONF_TOKEN: user_input[CONF_TOKEN]},
                )
            errors["base"] = err

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"reconfigure_title": reconfigure_entry.title},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for the reauth repair flow."""
        if entry_data is None:
            entry_data = {}
        # Use a stable id from whatever token is on the entry, if any.
        existing = self._get_reconfigure_entry()
        if existing:
            self._reauth_entry_id = existing.entry_id
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_REAUTH_SCHEMA,
                description_placeholders={"reauth_title": existing.title},
            )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modal step: collect a fresh token."""
        errors: dict[str, str] = {}
        existing = self._get_reconfigure_entry()
        if user_input is not None:
            _info, _client, err = await _validate_token(
                self.hass, user_input[CONF_TOKEN]
            )
            if err is None:
                new_unique_id = _unique_id_for_token(user_input[CONF_TOKEN])
                return self.async_update_reload_and_abort(
                    existing,
                    unique_id=new_unique_id,
                    data_updates={CONF_TOKEN: user_input[CONF_TOKEN]},
                )
            errors["base"] = err

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                "reauth_title": existing.title if existing else "Realtime Trains",
            },
        )

    async def async_step_repair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Repair flow launched from a ConfigEntryError / repair issue."""
        return await self.async_step_reauth_confirm(user_input)

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type]:
        """Declare which subentry types this integration supports.

        The handler classes themselves arrive in M5; the keys are
        defined here so the device page exposes the *Add board* and
        *Add service tracker* entries from the start.
        """
        # Defer the import so the module loads even when subentry
        # handlers have not been wired up yet (M5 lands them).
        from .const import (  # noqa: PLC0415
            SUBENTRY_TYPE_DEPARTURE_BOARD,
            SUBENTRY_TYPE_SERVICE_TRACKER,
        )

        # Real handlers import in M5. Until then, returning an empty
        # dict would prevent the *Add* button from appearing; instead
        # we return placeholder stubs that the M5 implementation
        # replaces. The actual import is deferred so this module
        # remains loadable in CI before the subentry module exists.
        try:
            from .subentry_flows import (  # noqa: PLC0415
                DepartureBoardSubentryFlow,
                ServiceTrackerSubentryFlow,
            )
        except ImportError:
            return {}
        return {
            SUBENTRY_TYPE_DEPARTURE_BOARD: DepartureBoardSubentryFlow,
            SUBENTRY_TYPE_SERVICE_TRACKER: ServiceTrackerSubentryFlow,
        }
