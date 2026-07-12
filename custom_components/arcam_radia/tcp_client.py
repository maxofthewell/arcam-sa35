"""Client for the Arcam SA35 binary control protocol on TCP port 50000.

This is the official Arcam RS232/NET protocol (documented in Arcam's SA35
Control Installation Notes), used here specifically for input selection,
which the HTTPS JSON API does not expose.

Frame format:
    Command:  St(0x21) Cc Dl Data... Et(0x0D)
    Response: St(0x21) Cc Ac Dl Data... Et(0x0D)

Only the Input command (Cc=0x1D) is implemented here, since the JSON API
already handles power/volume/mute/metadata with richer data. This client
opens a short-lived connection per operation rather than holding one open,
which keeps it simple and avoids interfering with the amp's own periodic
broadcasts on this port.
"""
from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

PORT = 50000
ST = 0x21
ET = 0x0D
CC_POWER = 0x00
CC_INPUT = 0x1D
CC_SIMULATE_IR = 0x08
CC_SOFTWARE_VERSION = 0x04
CC_MODEL = 0x5E
CC_HEARTBEAT = 0x25
REQUEST = 0xF0
ANSWER_STATUS_UPDATE = 0x00

# Power command data bytes / response states (Cc=0x00).
POWER_OFF = 0x00
POWER_ON = 0x01
POWER_STATE_STANDBY = 0x00
POWER_STATE_ON = 0x01

# RC5 system code used by the SA35 (per Arcam docs, either 0x10 or 0x13;
# 0x10 is confirmed working on this unit).
RC5_SYSTEM = 0x10

# RC5 command codes we use (from the doc's RC5 table).
RC5_DISPLAY_BRIGHTNESS = 0x3B

# Documented input map (data byte -> friendly name). 0x0D (Net/USB) is
# response-only per the docs but included so we can display it as current
# source when the amp reports it.
INPUT_ID_TO_NAME = {
    0x01: "Phono MM",
    0x02: "Phono MC",
    0x03: "Analogue 1",
    0x04: "Analogue 2",
    0x05: "Analogue 3",
    0x07: "Digital 1",
    0x08: "Digital 2",
    0x09: "Digital 3",
    0x0A: "Digital 4",
    0x0B: "ARC/eARC",
    0x0C: "Bluetooth",
    0x0D: "Net/USB",
}

# Reverse map for selecting a source by name. Excludes Net/USB since that's
# selected by choosing a streaming source in the app, not by this command.
NAME_TO_INPUT_ID = {
    name: id_ for id_, name in INPUT_ID_TO_NAME.items() if id_ != 0x0D
}

# The list of sources we expose as selectable in Home Assistant.
SELECTABLE_SOURCES = list(NAME_TO_INPUT_ID.keys())


class ArcamTcpError(Exception):
    """Raised when a port-50000 operation fails."""


class ArcamTcpClient:
    """Short-lived-connection client for the SA35 binary protocol."""

    def __init__(self, host: str, timeout: float = 4.0) -> None:
        self._host = host
        self._timeout = timeout

    async def _transact(self, cc: int, data: int) -> bytes:
        """Send a single command frame and return the raw response frame.

        Reads until an End-of-Transmission (0x0D) byte is seen or timeout.
        """
        frame = bytes([ST, cc, 0x01, data, ET])
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, PORT), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ArcamTcpError(f"connect to {self._host}:{PORT} failed: {err}") from err

        try:
            writer.write(frame)
            await writer.drain()
            _LOGGER.debug("port50000 sent: %s", frame.hex(" "))

            # Read response frames until we get one matching our command code.
            # The amp also emits unsolicited broadcasts on this port, so we
            # filter for the frame whose Cc matches what we asked about.
            deadline = asyncio.get_event_loop().time() + self._timeout
            buffer = b""
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(256), timeout=self._timeout)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buffer += chunk
                frame_found = self._extract_matching_frame(buffer, cc)
                if frame_found is not None:
                    _LOGGER.debug("port50000 recv: %s", frame_found.hex(" "))
                    return frame_found
            raise ArcamTcpError(f"no response to Cc=0x{cc:02X} within timeout")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, asyncio.TimeoutError):
                pass

    @staticmethod
    def _extract_matching_frame(buffer: bytes, cc: int) -> bytes | None:
        """Find a complete St..Et frame in the buffer whose Cc matches."""
        start = 0
        while True:
            st_idx = buffer.find(ST, start)
            if st_idx == -1:
                return None
            et_idx = buffer.find(ET, st_idx)
            if et_idx == -1:
                return None
            frame = buffer[st_idx : et_idx + 1]
            # A valid frame is St Cc Ac Dl ...Data Et, so at least 5 bytes,
            # and its second byte is the command code.
            if len(frame) >= 5 and frame[1] == cc:
                return frame
            start = et_idx + 1

    async def get_current_input(self) -> str | None:
        """Return the friendly name of the current input, or None if unknown."""
        resp = await self._transact(CC_INPUT, REQUEST)
        # Response: St Cc Ac Dl Data Et -> data is at index 4
        if len(resp) >= 6:
            data_byte = resp[4]
            return INPUT_ID_TO_NAME.get(data_byte)
        raise ArcamTcpError(f"unexpected input response: {resp.hex(' ')}")

    async def set_input(self, source_name: str) -> None:
        """Switch to the named input (must be a key in NAME_TO_INPUT_ID)."""
        input_id = NAME_TO_INPUT_ID.get(source_name)
        if input_id is None:
            raise ArcamTcpError(f"unknown source name: {source_name!r}")
        resp = await self._transact(CC_INPUT, input_id)
        # A successful set returns Ac=0x00 (status update) at index 2.
        if len(resp) >= 3 and resp[2] != ANSWER_STATUS_UPDATE:
            raise ArcamTcpError(
                f"amp rejected input change, answer code 0x{resp[2]:02X}"
            )

    async def simulate_ir(self, rc5_command: int, system: int = RC5_SYSTEM) -> None:
        """Send a Simulate-IR command (Cc=0x08) with a 2-byte payload.

        Frame: St(0x21) 0x08 Dl(0x02) <system> <command> Et(0x0D)
        Used for remote-only functions like display brightness that have
        no dedicated set/request command.
        """
        frame = bytes([ST, CC_SIMULATE_IR, 0x02, system, rc5_command, ET])
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, PORT), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ArcamTcpError(f"connect to {self._host}:{PORT} failed: {err}") from err
        try:
            writer.write(frame)
            await writer.drain()
            _LOGGER.debug("port50000 IR sent: %s", frame.hex(" "))
            # We don't strictly need to parse the echo response, but drain
            # briefly so the connection closes cleanly.
            try:
                await asyncio.wait_for(reader.read(256), timeout=1.5)
            except asyncio.TimeoutError:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, asyncio.TimeoutError):
                pass

    async def get_model_name(self) -> str | None:
        """Return the amp's model string (e.g. 'SA35') via Cc=0x5E."""
        resp = await self._transact(CC_MODEL, REQUEST)
        # Response: St Cc Ac Dl <ASCII bytes...> Et. Data starts at index 4.
        if len(resp) >= 6:
            ascii_bytes = resp[4:-1]
            try:
                return bytes(ascii_bytes).decode("ascii").strip()
            except UnicodeDecodeError:
                return None
        raise ArcamTcpError(f"unexpected model response: {resp.hex(' ')}")

    async def get_software_version(self) -> str | None:
        """Return a human-readable software version string via Cc=0x04.

        The response data is 7 bytes:
          network upper.middle.lower, host MCU major.minor, ARC major.minor
        We format it as 'net X.Y.Z / MCU A.B / ARC C.D'.
        """
        resp = await self._transact(CC_SOFTWARE_VERSION, REQUEST)
        # Response: St Cc Ac Dl D1..D7 Et. Data starts at index 4.
        if len(resp) >= 12:
            d = resp[4:11]
            net = f"{d[0]}.{d[1]}.{d[2]}"
            mcu = f"{d[3]}.{d[4]}"
            arc = f"{d[5]}.{d[6]}"
            return f"net {net} / MCU {mcu} / ARC {arc}"
        raise ArcamTcpError(f"unexpected software version response: {resp.hex(' ')}")

    async def send_heartbeat(self) -> None:
        """Send a heartbeat (Cc=0x25) to reset the amp's auto-standby timer."""
        await self._transact(CC_HEARTBEAT, REQUEST)

    async def get_power_state(self) -> bool:
        """Return True if the amp is on, False if in standby, via Cc=0x00."""
        resp = await self._transact(CC_POWER, REQUEST)
        # Response: St Cc Ac Dl Data Et -> state at index 4.
        if len(resp) >= 6:
            return resp[4] == POWER_STATE_ON
        raise ArcamTcpError(f"unexpected power response: {resp.hex(' ')}")

    async def set_power(self, on: bool) -> None:
        """Turn the amp on or off (to standby) via Cc=0x00."""
        resp = await self._transact(CC_POWER, POWER_ON if on else POWER_OFF)
        if len(resp) >= 3 and resp[2] != ANSWER_STATUS_UPDATE:
            raise ArcamTcpError(
                f"amp rejected power command, answer code 0x{resp[2]:02X}"
            )
