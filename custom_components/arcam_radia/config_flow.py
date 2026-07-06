"""Config flow for the Arcam Radia integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcamRadiaApiError, ArcamRadiaClient
from .const import CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Optional(CONF_MAX_VOLUME, default=DEFAULT_MAX_VOLUME): int,
    }
)


async def _validate_host(hass: HomeAssistant, host: str) -> str:
    """Try to contact the amp and return its model name, or raise."""
    session = async_get_clientsession(hass, verify_ssl=False)
    client = ArcamRadiaClient(session, host)
    try:
        return await client.get_model_name()
    except ArcamRadiaApiError as err:
        raise CannotConnect from err
    except aiohttp.ClientError as err:
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Arcam Radia."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input["host"]
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            try:
                model_name = await _validate_host(self.hass, host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=model_name or f"Arcam Radia ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect to the amp."""
