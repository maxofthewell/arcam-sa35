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

## What this does NOT support

- **Input/source switching.** The physical inputs (Phono, AV1-4, Balanced,
  etc.) are not exposed anywhere in the amp's local API - this was
  confirmed by inspecting the web client's own JavaScript bundle, which
  contains no references to any physical input names or switching
  mechanism. If you need to switch inputs from Home Assistant, you'll
  need an IR blaster (e.g. Broadlink, ESPHome) sending the amp's remote
  IR codes instead.
- **Playback transport controls** (play/pause/next/previous). The amp's
  API does expose a `player:player/control` path for this, but the exact
  values it expects haven't been captured/confirmed yet - contributions
  welcome if you can grab that traffic.

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
