# Home Dashboard API — instructions for the LLM

You are generating a Python script to carry out a home-automation request
against a local Flask dashboard, given the reference file(s) pasted
alongside this one. Output a single, complete, ready-to-run Python script.
Don't ask clarifying questions if the request is reasonably unambiguous —
make a sensible assumption and note it in a comment.

## What controls what

- **Shelly devices** (`shelly.md`) control **lights** (`switch`/`light`
  components) and **blinds** (`cover` component).
- **Daikin devices** (`daikin.md`) control **AC units**, over Bluetooth.
  Every call is slow (~7-10s) — this is normal, use a 30s timeout, never
  assume it's instant.
- **Weather** (`weather.md`) is read-only current conditions.
- If the request involves a delay ("in 2 hours", "at bedtime in 45 min"),
  follow the pattern in `scheduling.md` on top of whichever of the above
  the actual action needs.

Only the files actually pasted alongside this one are relevant — infer
which ones are needed from the request (e.g. "close the blinds" only needs
`shelly.md`; add `scheduling.md` if it also has a delay).

## Hard rules for the script you write

1. Base URL: `http://localhost:5000` unless the user says otherwise (or if
   running elsewhere, the LAN IP Flask printed on startup).
2. Use stdlib `urllib.request` only — no `pip install`, no `requests`.
3. Resolve device IDs by name at runtime with `find_id()` below (don't
   hardcode an ID from the per-file tables — they're a reference for what
   exists, not a source of truth for the current ID).
4. Every response is JSON with `"ok"`: `true`/`false` (+ `"error"` string on
   failure). Always check `ok` and raise/print on failure — don't assume
   success.
5. If the action has a delay, background it (see `scheduling.md`) so it
   survives the terminal closing — don't just block synchronously and tell
   the user to leave the terminal open.

```python
import json, urllib.request
BASE = "http://localhost:5000"

def find_id(list_endpoint, name_substring):
    with urllib.request.urlopen(BASE + list_endpoint, timeout=10) as resp:
        devices = json.load(resp)
    for d in devices:
        if name_substring.lower() in d["display_name"].lower():
            return d["id"]
    raise ValueError("No device matching: " + name_substring)

# find_id("/api/shelly/configured", "escritorio")
# find_id("/api/daikin/devices", "sala")
```
