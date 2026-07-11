"""Button entities for the Arcam Radia integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .tcp_client import RC5_DISPLAY_BRIGHTNESS, ArcamTcpClient, ArcamTcpError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    tcp_client: ArcamTcpClient = data["tcp"]
    async_add_entities([ArcamDisplayBrightnessButton(tcp_client, entry)])


class ArcamDisplayBrightnessButton(ButtonEntity):
    """Cycles the amp's front-panel display brightness (bright -> dim -> off).

    The amp only exposes brightness as a cycle (one press advances one
    level), and does not report the current brightness back, so this is a
    simple 'press to advance' button that mirrors the remote's behaviour
    rather than a stateful on/off control.
    """

    _attr_has_entity_name = True
    _attr_name = "Display brightness"
    _attr_icon = "mdi:brightness-6"

    def __init__(self, tcp_client: ArcamTcpClient, entry: ConfigEntry) -> None:
        self._tcp_client = tcp_client
        self._attr_unique_id = f"{entry.entry_id}_display_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Arcam Radia",
            manufacturer="Arcam",
            model="Radia (SA35/SA45/ST25)",
        )

    async def async_press(self) -> None:
        try:
            await self._tcp_client.simulate_ir(RC5_DISPLAY_BRIGHTNESS)
        except ArcamTcpError as err:
            _LOGGER.error("Failed to cycle display brightness: %s", err)
