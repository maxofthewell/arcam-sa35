"""Minimal client for the Arcam Radia (SA35/SA45/ST25) local JSON API.

This talks to the NSDK/StreamUnlimited-based webclient API exposed by the
amp on https://<host>/api/getData and /api/setData. It was reverse
engineered from browser dev tools traffic and covers only the following
confirmed-working paths:

    powermanager:target              (power state: online / networkStandby)
    player:volume                    (integer volume level)
    settings:/mediaPlayer/mute       (boolean mute state)

The amp's HTTPS certificate is self-signed, so SSL verification is
disabled for all requests in this client.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

PATH_POWER = "powermanager:target"
PATH_VOLUME = "player:volume"
PATH_MUTE = "settings:/mediaPlayer/mute"
PATH_NOW_PLAYING = "player:player/data/value"
PATH_PLAY_TIME = "player:player/data/playTime"

POWER_ON = "online"
POWER_STANDBY = "networkStandby"


class ArcamRadiaApiError(Exception):
    """Raised when a request to the amp fails or returns something unexpected."""


class ArcamRadiaClient:
    """Thin async wrapper around the amp's getData/setData HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self._base_url = f"https://{host}/api"

    def _nocache(self) -> str:
        return str(int(time.time() * 1000))

    async def _get_data(self, path: str) -> Any:
        params = {
            "path": path,
            "roles": "@all",
            "type": "structure",
            "_nocache": self._nocache(),
        }
        try:
            async with self._session.get(
                f"{self._base_url}/getData", params=params, ssl=False
            ) as resp:
                if resp.status != 200:
                    raise ArcamRadiaApiError(
                        f"getData {path} returned HTTP {resp.status}"
                    )
                data = await resp.json(content_type=None)
                _LOGGER.debug("getData %s -> %s", path, data)
                return data
        except aiohttp.ClientError as err:
            raise ArcamRadiaApiError(f"getData {path} failed: {err}") from err

    async def _set_data(self, path: str, value_type: str, value: Any) -> bool:
        payload = {
            "path": path,
            "role": "value",
            "value": {"type": value_type, value_type: value},
            "_nocache": self._nocache(),
        }
        try:
            async with self._session.post(
                f"{self._base_url}/setData", json=payload, ssl=False
            ) as resp:
                if resp.status != 200:
                    raise ArcamRadiaApiError(
                        f"setData {path} returned HTTP {resp.status}"
                    )
                result = await resp.json(content_type=None)
                _LOGGER.debug("setData %s=%s -> %s", path, value, result)
                return bool(result)
        except aiohttp.ClientError as err:
            raise ArcamRadiaApiError(f"setData {path} failed: {err}") from err

    @staticmethod
    def _unwrap(response: Any) -> Any:
        """Unwrap a getData response into its actual payload.

        Confirmed real response shape (from captured traffic):

            {
              "timestamp": 1783295312579,
              "value": {
                "powerTarget": {"target": "online", ...},
                "type": "powerTarget"
              },
              "type": "value",
              "path": "powermanager:target"
            }

        The payload lives at response["value"], which is itself an object
        whose own "type" field names which of its keys holds the real
        data. For compound roles (like power) that resolves to a nested
        object; for simple scalar roles (volume, mute) it should resolve
        directly to the value itself, e.g. {"i32_": 22, "type": "i32_"}.
        """
        if not isinstance(response, dict):
            return response

        value_obj = response.get("value")
        if isinstance(value_obj, dict) and "type" in value_obj:
            inner_type = value_obj["type"]
            if inner_type in value_obj:
                return value_obj[inner_type]
            return value_obj

        # Fallback for any response that doesn't match the confirmed shape.
        return value_obj if value_obj is not None else response

    async def get_power_state(self) -> str:
        """Return the raw power target string, e.g. 'online' or 'networkStandby'."""
        data = await self._get_data(PATH_POWER)
        value = self._unwrap(data)
        if isinstance(value, dict) and "target" in value:
            return value["target"]
        raise ArcamRadiaApiError(f"Unexpected power state response: {data}")

    async def set_power_state(self, target: str) -> bool:
        return await self._set_data(PATH_POWER, "string_", target)

    async def get_volume(self) -> int:
        data = await self._get_data(PATH_VOLUME)
        value = self._unwrap(data)
        if isinstance(value, (int, float)):
            return int(value)
        raise ArcamRadiaApiError(f"Unexpected volume response: {data}")

    async def set_volume(self, level: int) -> bool:
        return await self._set_data(PATH_VOLUME, "i32_", int(level))

    async def get_mute(self) -> bool:
        data = await self._get_data(PATH_MUTE)
        value = self._unwrap(data)
        if isinstance(value, bool):
            return value
        raise ArcamRadiaApiError(f"Unexpected mute response: {data}")

    async def set_mute(self, mute: bool) -> bool:
        return await self._set_data(PATH_MUTE, "bool_", bool(mute))

    async def get_model_name(self) -> str:
        data = await self._get_data("settings:/system/modelName")
        value = self._unwrap(data)
        if isinstance(value, str):
            return value
        raise ArcamRadiaApiError(f"Unexpected model name response: {data}")

    async def get_now_playing(self) -> dict[str, Any]:
        """Return now-playing metadata: title, artist, album, icon, state, duration_ms.

        Confirmed real shape (captured from a pollQueue push event, same
        envelope pattern applies to a direct getData call on this path):

            {
              "playLogicData": {
                "trackRoles": {
                  "icon": "https://.../cover.jpg",
                  "title": "Track Name",
                  "mediaData": {"metaData": {"album": "...", "artist": "..."}}
                },
                "state": "paused" | "playing",
                "status": {"duration": 326706},
                "mediaRoles": {"title": "Qobuz Connect"}   # service/source name
              }
            }

        Any fields not present in a given response are omitted from the
        returned dict, so callers should use .get() when reading it.
        """
        data = await self._get_data(PATH_NOW_PLAYING)
        value = self._unwrap(data)
        if not isinstance(value, dict):
            raise ArcamRadiaApiError(f"Unexpected now-playing response: {data}")

        result: dict[str, Any] = {}

        track_roles = value.get("trackRoles", {})
        if isinstance(track_roles, dict):
            if "title" in track_roles:
                result["title"] = track_roles["title"]
            if "icon" in track_roles:
                result["icon"] = track_roles["icon"]
            meta = track_roles.get("mediaData", {}).get("metaData", {})
            if isinstance(meta, dict):
                if "artist" in meta:
                    result["artist"] = meta["artist"]
                if "album" in meta:
                    result["album"] = meta["album"]

        if "state" in value:
            result["state"] = value["state"]

        status = value.get("status", {})
        if isinstance(status, dict) and "duration" in status:
            result["duration_ms"] = status["duration"]

        media_roles = value.get("mediaRoles", {})
        if isinstance(media_roles, dict) and "title" in media_roles:
            result["source_name"] = media_roles["title"]

        return result

    async def get_play_time(self) -> int:
        """Return current playback position in milliseconds.

        Confirmed shape (captured from a pollQueue push event, same
        wrapping convention as everything else in this API):
            {"i64_": 213508, "type": "i64_"}
        """
        data = await self._get_data(PATH_PLAY_TIME)
        value = self._unwrap(data)
        if isinstance(value, (int, float)):
            return int(value)
        raise ArcamRadiaApiError(f"Unexpected play time response: {data}")
