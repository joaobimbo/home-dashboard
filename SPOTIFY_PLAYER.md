# SPOTIFY_PLAYER.md — Spotify Connect Music Player for Home Dashboard

## Goal

Add Spotify playback control to the existing `home-dashboard` project. This specification is implemented on the main branch; it remains as the feature design and operational reference.

The dashboard should treat Spotify as one household music player whose playback can be transferred between Spotify Connect devices:

- Amazon Echo speaker
- Google Home / Nest speaker
- the Linux home-dashboard server connected to the Hi-Fi through the analog jack

The Linux server must appear as a normal Spotify Connect target by running `librespot`.

Do **not** integrate directly with Alexa APIs, Google Cast APIs, Home Assistant, Snapcast, or other multi-room systems for this feature. Spotify Connect is the device abstraction.

The intended architecture is:

```text
HTML dashboard
      |
      v
Flask app
      |
      v
modules/spotify/
      |
      v
Spotify Web API
      |
      v
Spotify Connect
   /      |       \
Echo   Google   librespot
Home             on server
                    |
                    v
                 audio jack
                    |
                    v
                   Hi-Fi
```

## Repository constraints

Read and follow the existing `AGENTS.md` before changing code.

Important existing conventions:

- Keep the stack minimal: Python + Flask + Jinja + plain HTML/CSS + vanilla JS.
- Do not introduce Node, npm, frontend frameworks, Docker, or a database.
- Backend wiring belongs in `app.py`.
- Device/service-specific logic belongs under `modules/`.
- Browser code must talk only to Flask endpoints, never directly to Spotify.
- Keep `static/app.js` compatible with old iPad Safari:
  - no `async` / `await`
  - no arrow functions
  - avoid modern-only JS APIs unless already used/polyfilled
  - call `classList.add()` / `classList.remove()` with one class at a time
- Preserve current Shelly, Daikin, weather, Telegram-agent, and dashboard behavior.

The current frontend entrypoints are:

```text
templates/index.html
static/app.js
static/style.css
```

The backend entrypoint is:

```text
app.py
```

## Spotify account assumption

This is a private household application.

Assume:

- one Spotify account is used for the dashboard player;
- that account has Spotify Premium;
- the Spotify developer application remains in Development Mode;
- only the owner / explicitly allowlisted users will authenticate.

Spotify currently requires the app owner to have Premium for Development Mode applications, and Player API operations such as transfer playback require Premium.

Do not build account registration, multi-tenant support, or a general public Spotify application.

## Spotify API requirements

Use the current Spotify Web API documentation as source of truth. Do not rely on remembered endpoint behavior.

Relevant official documentation:

- Web API:
  https://developer.spotify.com/documentation/web-api
- Player endpoints:
  https://developer.spotify.com/documentation/web-api/reference/get-information-about-the-users-current-playback
- Available devices:
  https://developer.spotify.com/documentation/web-api/reference/get-a-users-available-devices
- Transfer playback:
  https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback
- Authorization:
  https://developer.spotify.com/documentation/web-api/concepts/authorization
- Redirect URI rules:
  https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- Scopes:
  https://developer.spotify.com/documentation/web-api/concepts/scopes
- Rate limits:
  https://developer.spotify.com/documentation/web-api/concepts/rate-limits
- February 2026 Development Mode migration:
  https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide

Before implementing an endpoint, confirm its current request/response format in the official reference.

## Authentication

Implement Spotify OAuth in the Flask backend.

Because this application has a backend capable of keeping a secret, use the **Authorization Code flow**.

Do not use:

- Implicit Grant
- Client Credentials for player control
- browser-side tokens
- browser-side client secrets

Environment variables:

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
```

Optional:

```text
SPOTIFY_TOKEN_FILE
```

Default token file if not supplied:

```text
~/.config/home-dashboard/spotify-token.json
```

Never commit Spotify credentials or refresh tokens.

Add relevant generated/local files to `.gitignore` if necessary.

### Redirect URI warning

Spotify now requires HTTPS redirect URIs except for explicit loopback IP literals.

`http://localhost:...` is not allowed.

For setup/testing on the server itself, a valid example is:

```text
http://127.0.0.1:5000/api/spotify/callback
```

If authentication must be initiated from another machine on the LAN, do not assume that an HTTP LAN address such as `http://192.168.1.x:5000/...` is accepted. Use an HTTPS hostname/reverse proxy or another compliant redirect arrangement.

The redirect URI registered in the Spotify developer dashboard must exactly match `SPOTIFY_REDIRECT_URI`.

## Required scopes

Request only the scopes actually needed.

Minimum initial scopes:

```text
user-read-playback-state
user-modify-playback-state
```

Add:

```text
user-read-currently-playing
```

only if needed by the chosen current-track endpoint.

If search is implemented and the current Spotify API requires an additional scope such as `user-read-private`, add only the scope required by the current reference.

Do not request playlist/library modification scopes in this task.

## Python implementation

Prefer direct HTTP requests to the Spotify Web API rather than introducing a large abstraction layer.

It is acceptable to add the `requests` package to `requirements.txt`.

Do not implement OAuth or API calls manually with raw sockets or `urllib` if `requests` makes the code simpler.

Create:

```text
modules/
  spotify/
    __init__.py
    controller.py
    auth.py
```

A separate `config.py` is optional if it improves clarity.

### `SpotifyController`

Create a `SpotifyController` analogous in spirit to the existing Shelly and Daikin controllers.

Responsibilities:

- obtain a valid access token from the auth/token store;
- refresh expired access tokens automatically;
- query available Spotify Connect devices;
- query current playback state;
- play;
- pause;
- previous track;
- next track;
- set volume;
- transfer playback to another Spotify Connect device;
- play a Spotify URI/context on a selected or active device;
- optionally search Spotify if implemented;
- normalize Spotify responses into small dashboard-oriented payloads;
- handle Spotify API errors consistently;
- handle HTTP 429 using `Retry-After`;
- never expose access tokens or refresh tokens to the browser.

The controller should return data structures in the existing project style, preferably:

```python
{
    "ok": True,
    ...
}
```

or:

```python
{
    "ok": False,
    "error": "Human-readable message"
}
```

Do not let routine Spotify HTTP failures raise uncaught exceptions through Flask.

### Token persistence

Persist the refresh token and current access token server-side.

The token store should contain only what is needed, for example:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1234567890,
  "scope": "..."
}
```

Requirements:

- create parent directories if needed;
- write atomically where practical;
- use restrictive file permissions on Linux where practical;
- never serve this file over HTTP;
- never log tokens;
- refresh shortly before expiry rather than waiting for an API call to fail.

A simple JSON token file is preferable to adding a database.

## Flask integration

Instantiate the Spotify controller once in `app.py`, similar to the existing device controllers.

Spotify should be optional: if environment variables are missing, the rest of the dashboard must still start normally.

Expose the following endpoints.

### Authentication

```text
GET /api/spotify/auth/status
GET /api/spotify/login
GET /api/spotify/callback
```

`GET /api/spotify/auth/status`

Example authenticated response:

```json
{
  "ok": true,
  "configured": true,
  "authenticated": true
}
```

Example unconfigured response:

```json
{
  "ok": true,
  "configured": false,
  "authenticated": false
}
```

`GET /api/spotify/login`

- redirects to Spotify authorization;
- generate and validate OAuth `state`;
- do not disable CSRF/state validation for convenience.

`GET /api/spotify/callback`

- validate `state`;
- exchange authorization code for tokens;
- store token data;
- redirect back to `/`;
- do not display credentials/tokens.

### Playback state

```text
GET /api/spotify/status
GET /api/spotify/devices
```

`GET /api/spotify/status` should normalize the useful current state.

Suggested response:

```json
{
  "ok": true,
  "authenticated": true,
  "is_playing": true,
  "progress_ms": 82341,
  "device": {
    "id": "...",
    "name": "Sala Hi-Fi",
    "type": "Computer",
    "volume_percent": 58,
    "supports_volume": true
  },
  "track": {
    "id": "...",
    "uri": "spotify:track:...",
    "name": "So What",
    "artists": ["Miles Davis"],
    "album": "Kind of Blue",
    "duration_ms": 545000,
    "image": "https://..."
  }
}
```

Handle no active playback gracefully:

```json
{
  "ok": true,
  "authenticated": true,
  "is_playing": false,
  "device": null,
  "track": null
}
```

`GET /api/spotify/devices`

Suggested response:

```json
{
  "ok": true,
  "devices": [
    {
      "id": "...",
      "name": "Sala Hi-Fi",
      "type": "Computer",
      "is_active": true,
      "is_restricted": false,
      "volume_percent": 58,
      "supports_volume": true
    },
    {
      "id": "...",
      "name": "Echo Cozinha",
      "type": "Speaker",
      "is_active": false,
      "is_restricted": false,
      "volume_percent": 35,
      "supports_volume": true
    }
  ]
}
```

Do not assume Spotify device IDs are permanent. Refresh the list periodically and identify devices by returned IDs at the time of the operation.

### Playback commands

```text
POST /api/spotify/play
POST /api/spotify/pause
POST /api/spotify/next
POST /api/spotify/previous
POST /api/spotify/device
POST /api/spotify/volume
POST /api/spotify/play-uri
```

Examples:

#### Transfer playback

Request:

```json
{
  "device_id": "..."
}
```

Call Spotify's transfer playback endpoint.

Transfer only to **one** device. Although Spotify's body uses `device_ids`, the current API supports one target at a time.

Unless there is a strong reason otherwise, keep the current play/pause state during transfer rather than unexpectedly starting music.

The UI may explicitly request play after transfer when the user selects a song.

#### Volume

Request:

```json
{
  "volume": 65,
  "device_id": "..."
}
```

Validate:

```text
0 <= volume <= 100
```

If the device reports `supports_volume == false`, disable volume control in the UI and return a meaningful backend error if called anyway.

#### Play URI

Request:

```json
{
  "uri": "spotify:album:...",
  "device_id": "..."
}
```

Support at least:

- track URI
- album URI
- playlist URI

Use the correct Spotify playback request format for track vs context URIs according to the current API.

Do not infer malformed Spotify identifiers.

## Search

Search is useful but is secondary to the core playback implementation.

If current Development Mode restrictions permit the required search endpoint for this application, implement:

```text
GET /api/spotify/search?q=...
```

Search at least:

- tracks
- albums
- artists
- playlists if the current API permits it

Keep results small.

Example normalized result:

```json
{
  "ok": true,
  "results": [
    {
      "type": "track",
      "name": "So What",
      "subtitle": "Miles Davis — Kind of Blue",
      "uri": "spotify:track:...",
      "image": "https://..."
    }
  ]
}
```

If Spotify's current Development Mode restrictions make a proposed search feature unavailable, do not invent a workaround. Implement the supported subset and document the limitation.

## Polling and rate limits

Do not hammer Spotify.

The dashboard does not need sub-second state synchronization.

Suggested browser polling:

```text
current playback: every 5 s while page is visible
device list: every 20–30 s while page is visible
```

If the page is hidden, suspend or substantially reduce polling using the project's existing old-Safari-compatible page visibility helpers.

Do not start one server-side polling thread per browser tab.

For Spotify 429 responses:

- honor the `Retry-After` header;
- do not retry in a tight loop;
- expose a useful temporary error to the UI.

Spotify currently applies rate limits over a rolling window and Development Mode also has quota restrictions. Design polling conservatively.

## Dashboard UI

Add a new category tab:

```text
Música
```

Do not redesign the entire dashboard.

Preserve the existing visual language.

The music section should contain one compact player card rather than one card per Spotify device.

Suggested layout:

```text
┌───────────────────────────────────────────┐
│ [album]  So What                         │
│          Miles Davis                     │
│          Kind of Blue                    │
│                                           │
│        ◀        ▶/❚❚        ▶             │
│                                           │
│ Volume   ━━━━━━━━━━━━━━━  58%             │
│ Output   Sala Hi-Fi                 ▾     │
└───────────────────────────────────────────┘
```

Required UI state:

- album art if available;
- track title;
- artist;
- play/pause;
- previous;
- next;
- current output device;
- output device selector;
- volume if supported;
- clear disconnected/authentication state.

Optional:

- playback progress;
- search box/result overlay.

### Device selector

Selecting the output should list currently available Spotify Connect devices, for example:

```text
✓ Sala Hi-Fi
  Echo Cozinha
  Google Home Escritório
```

The selected entry is the Spotify device with `is_active == true`.

A device that is unavailable should simply disappear from the refreshed list.

Do not hard-code Echo or Google speaker identifiers.

### Authentication UI

If Spotify is configured but not authenticated, show:

```text
Ligar Spotify
```

This should navigate to `/api/spotify/login`.

If Spotify is not configured at all, hide the music category or show a small configuration message; do not break the rest of the dashboard.

## Search UX

If implementing search, keep it simple.

A search input:

```text
Procurar no Spotify…
```

Results should show image + title + artist/album.

Clicking a result should:

1. use the currently selected output device;
2. transfer playback if necessary;
3. start the requested item.

Avoid building a full Spotify clone.

Do not implement library browsing, queue editing, playlist editing, recommendations, lyrics, podcasts UI, or social features in this task.

## `librespot` receiver on the home server

The home-dashboard Linux server is connected to the Hi-Fi through the analog audio jack.

Install and run `librespot` separately from Flask.

The Flask process must **not** launch or supervise librespot.

Add deployment documentation and, if useful, a sample systemd service under:

```text
deploy/
```

For example:

```text
deploy/librespot.service.example
```

The desired Spotify Connect device name is:

```text
Sala Hi-Fi
```

The exact audio backend/device depends on the Linux host.

Do not guess the ALSA/PulseAudio/PipeWire output device in committed configuration. Use a clearly documented placeholder and explain how to identify/test the correct output.

The service should:

- start on boot;
- restart after failure;
- run as an unprivileged user;
- output to the host's normal audio path / selected sound device;
- advertise itself as `Sala Hi-Fi`.

Avoid storing the user's Spotify password in the unit file.

Use the current librespot documentation for the supported authentication method and command-line flags. Do not copy flags from outdated examples without checking them.

## Amazon Echo and Google Home

No code should be added specifically for Amazon or Google speakers.

Expected setup outside the dashboard:

1. Link the same Spotify account to Amazon Alexa.
2. Link the same Spotify account to Google Home.
3. Make sure each speaker can play Spotify normally.
4. Once Spotify reports the speaker as an available Connect device, the dashboard should display it automatically.

The implementation is correct if a newly available Spotify Connect device appears without code changes.

## Important product model

Do not model this as three independent household streams.

For this first version:

```text
one Spotify account
one active Spotify playback session
one selected output target
```

The dashboard transfers that playback session between outputs.

Example:

```text
Echo Cozinha -> Sala Hi-Fi -> Google Home Escritório
```

Do not attempt synchronized playback across arbitrary Spotify Connect endpoints.

Do not implement separate simultaneous streams from the same account.

## Agent / Telegram integration

Design `SpotifyController` so the existing LLM/Telegram agent can call it later, but keep the music implementation independent of natural-language parsing.

Do not make the Telegram agent the only route to playback.

It should eventually be possible for the agent layer to map:

```text
"Põe Miles Davis na sala"
```

to something conceptually like:

```json
{
  "action": "spotify.play",
  "query": "Miles Davis",
  "device": "Sala Hi-Fi"
}
```

For this task, only add agent tool integration if the existing agent architecture makes it straightforward and well-tested. The dashboard player is the priority.

If agent support is added, expose small semantic operations rather than letting the LLM construct arbitrary Spotify HTTP requests.

Examples:

```text
spotify.status
spotify.devices
spotify.play
spotify.pause
spotify.next
spotify.previous
spotify.set_volume
spotify.transfer
spotify.search
spotify.play_uri
```

## Error handling

Handle at least:

- Spotify not configured;
- user not authenticated;
- expired access token;
- refresh failure;
- invalid OAuth state;
- no active Spotify device;
- requested device no longer available;
- restricted Spotify device;
- device does not support volume;
- no active playback;
- 401;
- 403;
- 404 where applicable;
- 429 rate/quota limit;
- Spotify/network timeout;
- malformed API response.

Do not expose raw exception traces or secrets in API responses.

Log enough information server-side to diagnose failures, but redact:

- access token;
- refresh token;
- client secret;
- authorization code.

## Timeouts

All outbound Spotify requests must have finite HTTP timeouts.

Do not allow a failed external HTTP request to block a Flask worker indefinitely.

Use a short sensible timeout, e.g. around 5–10 seconds.

## Tests

Add focused tests for the Spotify module and Flask endpoints using mocks. Tests must not call the real Spotify service.

At minimum test:

1. unconfigured Spotify module;
2. unauthenticated Spotify module;
3. token refresh;
4. device list normalization;
5. playback-state normalization;
6. no-current-playback response;
7. play;
8. pause;
9. next;
10. previous;
11. volume validation;
12. transfer playback body contains exactly one device;
13. malformed/unknown device handling;
14. 401 handling;
15. 403 handling;
16. 429 + `Retry-After`;
17. network timeout;
18. OAuth state validation;
19. callback stores refreshed credentials correctly;
20. secrets are not returned in public API payloads.

Preserve existing tests.

## Manual verification

Document a manual test procedure.

Expected sequence:

1. install updated Python dependencies;
2. configure Spotify developer app;
3. set environment variables;
4. start Flask;
5. authenticate Spotify once;
6. verify `/api/spotify/devices`;
7. verify Amazon Echo appears after Spotify has discovered/activated it;
8. verify Google Home appears after Spotify has discovered/activated it;
9. install/start librespot;
10. verify `Sala Hi-Fi` appears;
11. start a track;
12. transfer playback Echo -> `Sala Hi-Fi`;
13. transfer playback `Sala Hi-Fi` -> Google Home;
14. pause/resume;
15. previous/next;
16. change volume where supported;
17. reload dashboard and confirm authentication survives Flask restart;
18. confirm Shelly/Daikin/weather behavior remains unchanged.

## Configuration documentation

Update the project documentation with a concise Spotify setup section.

Include:

```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
export SPOTIFY_REDIRECT_URI="http://127.0.0.1:5000/api/spotify/callback"
```

Make clear that the redirect example works when OAuth is performed on the server itself.

Document the Spotify Developer Dashboard steps:

1. create/open the application;
2. register the exact redirect URI;
3. ensure the owner account has Premium;
4. add any additional Development Mode users to the allowlist if needed;
5. export credentials on the server;
6. open `/api/spotify/login`;
7. authorize once.

Do not put real credentials in documentation.

## Implementation sequence

Implement in this order:

### Phase 1 — backend foundation

- Spotify package
- environment configuration
- OAuth
- token persistence/refresh
- status endpoint
- devices endpoint
- normalized errors

### Phase 2 — playback

- play
- pause
- previous
- next
- volume
- transfer device
- play URI

### Phase 3 — dashboard

- `Música` category
- compact player
- state polling
- output selector
- volume
- authentication state

### Phase 4 — local receiver

- librespot deployment documentation
- optional example systemd unit

### Phase 5 — search

- search endpoint if supported by the current API
- simple search UI
- start result on selected device

### Phase 6 — optional agent integration

- expose small Spotify semantic tools to the existing agent architecture if appropriate

## Acceptance criteria

The task is complete when all of the following are true:

- the dashboard starts normally without Spotify environment variables;
- Spotify credentials and tokens never reach browser JavaScript;
- Spotify OAuth survives restart through refresh-token persistence;
- the dashboard displays current playback;
- play/pause/previous/next work;
- currently available Spotify Connect devices are listed dynamically;
- playback can be transferred between Spotify Connect targets;
- the Linux server running librespot appears as `Sala Hi-Fi`;
- Amazon Echo and Google Home require no vendor-specific dashboard code;
- volume works on devices that advertise volume support;
- unsupported volume is represented correctly;
- Spotify API calls have finite timeouts;
- 429 responses are handled without rapid retry;
- polling is conservative;
- old-iPad-compatible JavaScript conventions are preserved;
- existing Shelly, Daikin, weather, and agent behavior is not regressed;
- relevant Spotify functionality has mocked tests;
- setup documentation is sufficient to reproduce the integration on the home server.

## Non-goals

Do not add:

- Home Assistant
- Alexa APIs
- Google Cast control
- Chromecast audio streaming
- Snapcast
- AirPlay
- Sonos integration
- arbitrary local audio files
- YouTube
- Apple Music
- simultaneous multi-account playback
- synchronized Spotify multi-room playback
- database infrastructure
- Node/npm
- React/Vue/Svelte
- Docker

Keep the feature narrow: **a Spotify Connect controller integrated into the existing Home Dashboard.**
