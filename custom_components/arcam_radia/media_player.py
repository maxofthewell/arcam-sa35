"""Media player entity for the Arcam Radia integration."""
from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import POWER_ON, POWER_STANDBY, ArcamRadiaApiError, ArcamRadiaClient
from .const import CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 10
VOLUME_STEP_RAW = 1  # step size in the amp's own volume units, not a 0-1 fraction

_PLAYLOGIC_STATE_MAP = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player entity from a config entry."""
    client: ArcamRadiaClient = hass.data[DOMAIN][entry.entry_id]
    max_volume = entry.options.get(
        CONF_MAX_VOLUME, entry.data.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
    )
    async_add_entities([ArcamRadiaMediaPlayer(client, entry, max_volume)], True)


class ArcamRadiaMediaPlayer(MediaPlayerEntity):
    """Representation of an Arcam Radia amp (power/volume/mute only).

    Input/source switching is not exposed by the amp's local API and is
    not supported by this integration - use an IR blaster for that.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )
    _attr_should_poll = True

    def __init__(
        self, client: ArcamRadiaClient, entry: ConfigEntry, max_volume: int
    ) -> None:
        self._client = client
        self._max_volume = max_volume or DEFAULT_MAX_VOLUME
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Arcam Radia",
            manufacturer="Arcam",
            model="Radia (SA35/SA45/ST25)",
        )
        self._attr_available = False

    async def async_update(self) -> None:
        """Poll the amp for current power/volume/mute/now-playing state."""
        try:
            power_target = await self._client.get_power_state()
            is_on = power_target == POWER_ON
            self._attr_state = MediaPlayerState.ON if is_on else MediaPlayerState.OFF

            raw_volume = await self._client.get_volume()
            self._attr_volume_level = max(0.0, min(1.0, raw_volume / self._max_volume))

            self._attr_is_volume_muted = await self._client.get_mute()

            # Clear stale metadata by default; repopulated below if available.
            self._attr_media_title = None
            self._attr_media_artist = None
            self._attr_media_album_name = None
            self._attr_entity_picture = None
            self._attr_media_duration = None
            self._attr_media_position = None
            self._attr_media_position_updated_at = None
            self._attr_app_name = None

            if is_on:
                try:
                    now_playing = await self._client.get_now_playing()
                except ArcamRadiaApiError as err:
                    _LOGGER.debug("No now-playing data available: %s", err)
                    now_playing = {}

                if now_playing:
                    self._attr_media_title = now_playing.get("title")
                    self._attr_media_artist = now_playing.get("artist")
                    self._attr_media_album_name = now_playing.get("album")
                    self._attr_entity_picture = now_playing.get("icon")
                    self._attr_app_name = now_playing.get("source_name")

                    duration_ms = now_playing.get("duration_ms")
                    if isinstance(duration_ms, (int, float)):
                        self._attr_media_duration = int(duration_ms / 1000)

                    playlogic_state = now_playing.get("state")
                    if playlogic_state in _PLAYLOGIC_STATE_MAP:
                        self._attr_state = _PLAYLOGIC_STATE_MAP[playlogic_state]

                    try:
                        position_ms = await self._client.get_play_time()
                        self._attr_media_position = int(position_ms / 1000)
                        self._attr_media_position_updated_at = dt_util.utcnow()
                    except ArcamRadiaApiError as err:
                        _LOGGER.debug("No play time available: %s", err)

            self._attr_available = True
        except ArcamRadiaApiError as err:
            _LOGGER.warning("Error updating Arcam Radia state: %s", err)
            self._attr_available = False

    async def async_turn_on(self) -> None:
        await self._client.set_power_state(POWER_ON)

    async def async_turn_off(self) -> None:
        await self._client.set_power_state(POWER_STANDBY)

    async def async_set_volume_level(self, volume: float) -> None:
        target = round(volume * self._max_volume)
        await self._client.set_volume(target)
        self._attr_volume_level = volume

    async def async_volume_up(self) -> None:
        current_raw = round((self._attr_volume_level or 0.0) * self._max_volume)
        new_raw = min(self._max_volume, current_raw + VOLUME_STEP_RAW)
        await self._client.set_volume(new_raw)
        self._attr_volume_level = new_raw / self._max_volume

    async def async_volume_down(self) -> None:
        current_raw = round((self._attr_volume_level or 0.0) * self._max_volume)
        new_raw = max(0, current_raw - VOLUME_STEP_RAW)
        await self._client.set_volume(new_raw)
        self._attr_volume_level = new_raw / self._max_volume

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.set_mute(mute)
        self._attr_is_volume_muted = mute
