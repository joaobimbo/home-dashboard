# User-editable configuration for the M5PaperS3 dashboard client.

# LAN address of the Flask dashboard server, e.g. "http://192.168.1.50:5000"
# (find it from what `python app.py` prints on startup, or `hostname -I` on the host).
SERVER_URL = "http://192.168.1.50:5000"

# Polling cadence, in milliseconds. Matches static/app.js's cadence on the web dashboard.
SHELLY_POLL_MS = 30000
AC_POLL_MS = 30000
WEATHER_POLL_MS = 900000

# HTTP timeouts, in seconds. Daikin calls are slow on purpose (real BLE round trip).
HTTP_TIMEOUT_FAST = 10
HTTP_TIMEOUT_DAIKIN = 30

# Force a full (flash) e-paper refresh every N partial refreshes, to clear ghosting.
FULL_REFRESH_EVERY = 20

# Main loop tick, in milliseconds - how often touch is polled and timers are checked.
TICK_MS = 100
