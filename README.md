# Arcam Radia for Home Assistant

Custom Home Assistant integration for Arcam Radia amplifiers (SA35, SA45,
ST25, and likely other models sharing the same platform), controlling them
via the amp's local HTTPS JSON API (the same API used internally by the
amp's own web control page at `https://<amp-ip>/webclient/`).

## What this supports

- **Power** (on / network standby)
- **Volume** - absolute set, plus volume up/down stepping
- **Mute / unmute**
- **Now playing metadata** - track title, artist, album, album art,
  duration, and live playback position, when something is actively
  streaming through the amp (Qobuz Connect, AirPlay, Bluetooth, etc.)
- **Transport controls** - play/pause, next track, previous track, and
  seeking to a specific position in the track
- **Input/source selection** - switch between all physical inputs (Phono
  MM/MC, Analogue 1-3, Digital 1-4, ARC/eARC, Bluetooth) and see the
  current input. This uses the documented Arcam binary control protocol
  on TCP port 50000, separate from the JSON API used for everything else.
- **Display brightness button** - a button entity that cycles the amp's
  front-panel display brightness (bright -> dim -> off), mirroring the
  remote's brightness button. It's a cycle rather than a direct on/off
  because the amp only exposes brightness as a cycle and doesn't report
  the current level back.
- **Device info** - the amp's model and firmware versions (network, host
  MCU, ARC) are read via the binary protocol and shown in the Home
  Assistant device page.
- **Optional keep-awake** - a setup toggle (off by default) that sends a
  periodic heartbeat while the amp is on, resetting its auto-standby
  timer so it won't sleep on its own. Only takes effect while the amp is
  already on - it never wakes a sleeping amp. Note this will increase
  idle power draw, so leave it off unless you specifically need it.

**Note on play/pause:** the amp's API only exposes a single toggle
command (confirmed via captured traffic - there is no separate "play"
command, only "pause" which flips the current state). Both the Play and
Pause buttons in Home Assistant send this same toggle, so they'll work
correctly most of the time, but pressing "Play" while already playing
will pause it instead of being a no-op. This is a limitation of the
amp's own API, not something this integration can work around.

## What this does NOT support

- **Net/USB as a directly selectable source.** The amp reports "Net/USB"
  as the current input when you're streaming (Qobuz, AirPlay, Bluetooth
  app streaming, etc.), and this integration will display that correctly.
  But you can't *switch to* Net/USB with a single command - it becomes
  active when you start streaming to the amp from an app, so it's shown
  as current-state-only rather than in the selectable source list.

## How this works

The amp runs an embedded web server (the same one powering its own
`/webclient/` control page) exposing a simple JSON API:

- `GET /api/getData?path=<path>&roles=@all&type=structure` - read a value
- `POST /api/setData` with `{"path": ..., "role": "value", "value": {...}}` - write a value

This integration talks to that same API directly. The amp's HTTPS
certificate is self-signed, so SSL verification is disabled for requests
to it.

**Security note:** the amp's local API does not appear to require any
authentication - anything on your LAN can query/control it. This is a
property of the amp itself, not something this integration can change.

## Installation via HACS (custom repository)

This is not in the default HACS store. To install it:

1. In Home Assistant, go to **HACS → Integrations**.
2. Click the three-dot menu (top right) → **Custom repositories**.
3. Add this repository's URL, select category **Integration**, and click **Add**.
4. Find "Arcam Radia" in HACS and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration**, search for
   "Arcam Radia", and enter your amp's IP address.

## Manual installation (without HACS)

Copy the `custom_components/arcam_radia` folder into your Home
Assistant's `config/custom_components/` directory, then restart Home
Assistant and add the integration as above.

## Configuration

- **Host**: the amp's IP address (a static IP or DHCP reservation on your
  router is strongly recommended, since this integration does not
  currently support mDNS/discovery).
- **Maximum volume value**: the integer scale the amp's API uses
  internally for 100% volume. This was not confirmed during development
  (only mid-range values like 16-22 were observed) - the default of `100`
  is a guess. If your volume slider in Home Assistant doesn't track the
  amp's actual volume proportionally, adjust this in the integration's
  options and let us know what the correct value turned out to be.

## Troubleshooting

Enable debug logging by adding this to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.arcam_radia: debug
```

This will log every request/response to/from the amp's API, which is
useful for diagnosing any response-shape mismatches (the exact JSON shape
for volume/mute reads was inferred from limited packet captures rather
than exhaustively confirmed).

## Contributing

This was built by reverse-engineering browser dev tools traffic against
the amp's own web control page, since Arcam has not published this API.
If you find additional working paths (source switching, EQ, balance,
now-playing metadata, etc.), pull requests are welcome.
