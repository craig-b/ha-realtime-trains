"""Config flow for the Realtime Trains integration.

This is the M0 scaffold: a minimal single-step user flow that accepts a
token and creates an account config entry. Full validation against
`/api/info`, the station picker, subentries, reauth and reconfigure all
arrive in M4-M5. The schema must remain valid for hassfest to accept the
integration manifest (`config_flow: true`).
"""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_DEFAULT_SLOT_COUNT,
    CONF_TOKEN,
    DEFAULT_SLOT_COUNT,
    DOMAIN,
    MAX_SLOT_COUNT,
    MIN_SLOT_COUNT,
)

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


class RealtimeTrainsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Realtime Trains config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: collect the API token and account defaults.

        No validation against the API is performed in M0 — that arrives
        with the account coordinator in M4. For now, the entry is
        created as soon as the user provides a token.
        """
        if user_input is not None:
            # Use a hash-derived unique id so re-adding the same token
            # aborts cleanly. Replaced by `/api/info`-based identity
            # in M4 (the token itself is sensitive and not used as the
            # unique id once entitlements are available).
            unique_id = f"rtt-account-{abs(hash(user_input[CONF_TOKEN]))}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Realtime Trains",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_USER_SCHEMA,
        )
