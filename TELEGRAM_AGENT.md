# Telegram home-automation agent

The agent is a separate long-polling process. It sends natural-language
requests to one configured cloud LLM, validates the returned rule locally,
and calls only the dashboard API at `127.0.0.1:5000`. Model output is never
executed as Python or passed to a shell.

It also starts a private, loopback-only web bridge on `127.0.0.1:5001` by
default. The Flask dashboard forwards web-agent requests to that bridge, so
only this service needs LLM credentials. Set `AGENT_WEB_PORT` only when the
default port is occupied.

## Telegram setup

1. Create the bot with BotFather and add it to the private household group.
2. Configure the group chat ID in `TELEGRAM_ALLOWED_CHAT_IDS`. Multiple group
   IDs can be comma-separated. DMs and other chats are ignored.
3. For free-form group messages, make the bot an administrator or disable its
   group privacy with BotFather's `/setprivacy`, then remove and re-add it.

## Provider setup

Install dependencies in the existing virtual environment:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

Copy `deploy/home-dashboard-agent.env.example` to
`/etc/home-dashboard-agent.env`, restrict it to the service account, and set:

- `LLM_PROVIDER` to `openai`, `anthropic`, or `gemini`;
- `LLM_MODEL` to a model from that provider that supports structured output;
- only the selected provider's API key;
- the Telegram token and allowed group IDs.

Provider model selection is deliberately an environment/restart operation;
Telegram users cannot change it. Consumer chat subscriptions do not include
API access.

The Gemini adapter uses Google's current Interactions API. It sends a concise
list of device tokens/capabilities, the available function signatures, and a
short JSON contract instead of the full provider-neutral schema. The returned
plan still passes through the same strict local device/capability validator
before anything can execute.

## Run manually

Keep the Flask dashboard running, then start:

```bash
set -a
. /etc/home-dashboard-agent.env
set +a
.venv/bin/python telegram_agent.py
```

Available commands:

- `/devices`
- `/status`
- `/on` — shows devices that are off; tap one to turn it on
- `/off` — shows devices that are on; tap one to turn it off
- `/debug` — authorization, engine, rules, and dashboard catalog diagnostics
- `/rules`
- `/enable` — opens a paginated menu of disabled rules
- `/disable` — opens a paginated menu of enabled rules
- `/delete` — opens a paginated rule menu and asks for confirmation

The older `/enable <rule-id>`, `/disable <rule-id>`, and `/delete <rule-id>`
forms remain available for scripting and troubleshooting.

Sending the exact text `on` or `off` provides the same device menus without an
LLM call. Only devices with the existing `power` capability and a known current
state are shown. Menu buttons use short-lived tokens bound to the requesting
user and chat; the catalog and status are checked again before the action runs.

Immediate, valid device actions run directly. Creating/replacing and deleting
saved automations requires an inline confirmation from the person who made the
request. Ambiguous requests produce one follow-up question.

Natural-language requests show their current stage in Telegram: received,
validated, then dispatched. The console/service journal logs the full incoming
Telegram message, a short request ID, the validated plan, each device action,
and its result. API keys and the bot token are never logged. Use `/debug` first
when commands work but device requests do not.

## Install as a service

Create the persistent data directory and install the included unit:

```bash
sudo install -d -o joao -g joao -m 0700 /var/lib/home-dashboard-agent
sudo install -m 0600 deploy/home-dashboard-agent.env.example /etc/home-dashboard-agent.env
sudo install -m 0644 deploy/home-dashboard-agent.service /etc/systemd/system/home-dashboard-agent.service
```

Edit `/etc/home-dashboard-agent.env`, then enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now home-dashboard-agent.service
```

The service assumes the repository is `/home/joao/code/home-dashboard` and the
service user is `joao`.

Inspect logs with:

```bash
journalctl -u home-dashboard-agent.service -f
```

Set `AGENT_LOG_LEVEL=INFO` (the default) for lifecycle and request-stage logs,
or `WARNING` for failures only. If a normal group message creates no journal
entry at all, Telegram did not deliver it to the bot; check BotFather group
privacy or make the bot a group administrator.

`AGENT_MAX_MESSAGE_AGE_SECONDS` defaults to `3600`. Telegram still delivers
pending updates after a restart, preserving recent requests, but the agent
silently discards older commands and natural-language messages before rate
limiting, LLM calls, or device actions. The journal records each discard as
`stale_message_dropped`. Current button taps are not rejected based on the age
of the Telegram message that contains the button; confirmation tokens retain
their separate ten-minute expiry.

## Persistence

`AGENT_DATA_DIR` contains:

- `rules.json`: versioned shared household automations;
- `state.json`: trigger observations and pending delayed runs;
- `audit.jsonl`: rule/action events without raw prompts or secrets. Full
  messages appear only in the console/service journal when INFO logging is on.

Disabling or deleting a rule cancels its pending runs. On restart, a due run
re-checks its conditions before executing. These storage APIs are intentionally
separate from Telegram so a future dashboard UI can enable and disable rules
without changing the executor.

Relative one-time requests use a validated `schedule/after` trigger. Its
countdown starts when the user confirms and the rule is saved; subsequent waits
are persisted in `state.json`, so sequences continue across service restarts.
Re-enabling a completed or disabled relative rule clears its previous fired slot
and restarts the countdown from the time it is enabled.

Clock schedules use the timezone configured by `AGENT_TIMEZONE` (default
`Europe/Lisbon`). Requests can create one-time, daily, or weekly rules, for
example "open the bedroom blinds every day at 7am". Clock conditions can also
restrict another trigger with equal, before/after, or between comparisons. The
agent receives the current local date and time when interpreting requests, and
the confirmation preview shows the exact schedule and timezone before saving.

## Spotify automations

When Spotify is authenticated on the dashboard, the catalog includes a global
`Spotify playback` target for pause/next/previous and the currently available
Spotify Connect outputs for transfers and starting music. Device IDs are
refreshed from Spotify at request time and must never be hard-coded.

Examples: “pause Spotify in 10 minutes”, “move Spotify to Escritorio at 7am”,
or “play playlist Morning on Sala Hi-Fi tomorrow at 7am”. Automation previews
must be confirmed before they are saved.

### Household Spotify outputs

The agent resolves these names against Spotify's currently available Connect
outputs (and never hard-codes an ID):

- `Google Home Mini` — Quarto / bedroom
- `Ana's Echo` — Sala/Cozinha / living room/kitchen
- Server PC `librespot` receiver — Escritorio / office

If a requested speaker is absent from Spotify's live device list, the agent
must report it as unavailable instead of sending playback to another output.
