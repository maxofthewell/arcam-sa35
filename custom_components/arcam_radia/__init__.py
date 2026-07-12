"""The Arcam Radia integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcamRadiaClient
from .const import DOMAIN, PLATFORMS
from .tcp_client import ArcamTcpClient, ArcamTcpError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arcam Radia from a config entry."""
    host = entry.data["host"]

    # The amp's HTTPS cert is self-signed, so we use a session configured
    # to skip verification for this integration's requests.
    session = async_get_clientsession(hass, verify_ssl=False)
    client = ArcamRadiaClient(session, host)

    # Separate client for the port-50000 binary protocol, used for input
    # selection and a few diagnostic queries the JSON API doesn't expose.
    tcp_client = ArcamTcpClient(host)

    # Best-effort fetch of model + firmware for the device registry. These
    # are optional - if the amp is unreachable on port 50000 right now,
    # setup still proceeds and they're just left unset.
    model_name = None
    sw_version = None
    try:
        model_name = await tcp_client.get_model_name()
        sw_version = await tcp_client.get_software_version()
    except ArcamTcpError as err:
        _LOGGER.debug("Could not fetch model/firmware at setup: %s", err)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": client,
        "tcp": tcp_client,
        "model_name": model_name,
        "sw_version": sw_version,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
