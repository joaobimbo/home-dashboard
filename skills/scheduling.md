# Scheduling — "do this later"

For "turn off the AC in 2 hours", etc: sleep, then make the one API call
(from `shelly.md`/`daikin.md`/`weather.md`), backgrounded so closing the
terminal doesn't kill it.

```python
import time
DELAY_SECONDS = 2 * 60 * 60  # adjust

device_id = find_id("/api/daikin/devices", "sala")
time.sleep(DELAY_SECONDS)
# ...then the normal request, e.g. POST /api/daikin/<id>/power {"state": "off"}
```

Run it backgrounded:
```bash
nohup python3 script.py > /tmp/script.log 2>&1 &
```

Check/cancel:
```bash
ps aux | grep script.py   # find PID
kill <pid>                # cancel
tail -f /tmp/script.log   # watch for the result
```

Note: plain background process, not `cron`/`systemd` — only survives while the machine stays on.
