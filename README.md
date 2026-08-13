# Home Dashboard

## Spotify Connect

The Flask service controls Spotify; Raspotify/librespot is a separate Spotify Connect receiver on the same machine for the Hi-Fi. Never put Spotify passwords in a systemd unit.

Set these on the dashboard service, register the exact redirect URI in the Spotify Developer Dashboard, restart it, then open `/api/spotify/login` once:

```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
export SPOTIFY_REDIRECT_URI="http://127.0.0.1:5000/api/spotify/callback"
```

For an HTTP redirect, perform OAuth on the server itself. To authorize from another PC, use a registered HTTPS hostname.

On Ubuntu/Debian, Raspotify's `/etc/raspotify/conf` can advertise the analog receiver:

```ini
LIBRESPOT_NAME="Sala Hi-Fi"
LIBRESPOT_DEVICE_TYPE=speaker
LIBRESPOT_BACKEND=alsa
LIBRESPOT_DEVICE="plughw:CARD=Intel,DEV=0"
```

Use `aplay -L` to find the actual audio output; do not copy the example if your host differs. Restart with `sudo systemctl restart raspotify`. The Música tab lists all currently available Spotify Connect targets, so Echo and Google speakers appear automatically when Spotify exposes them.
