# AGENTS.md — Home Dashboard

## Project goal

Build a lean local home dashboard for my house.

The dashboard must be accessible from any browser, iPad, or phone on the local network. It should be simple, robust, and easy to maintain.

The first milestone is a working dashboard frame with buttons for controlling Shelly devices.

Do not build Spotify, calendar, photos, voice control, or other integrations yet. Leave the architecture ready for them, but focus only on the frame and Shelly controls.

---

## Core principles

Use the simplest stack that works:

- Python 3
- Flask
- Jinja2 templates
- Plain HTML
- Plain CSS
- Small plain JavaScript only where needed

Avoid:

- Node.js
- npm
- React
- Vue
- Svelte
- Angular
- TypeScript
- Tailwind
- Vite
- Webpack
- Docker
- Databases, unless explicitly requested

The app should run with:

```bash
python app.py
```

and be reachable at:

http://localhost:5000

or from other devices on the LAN:

http://<desktop-ip>:5000

Browser / iPad / phone
    ↓
HTML + CSS + small JavaScript
    ↓
Flask server
    ↓
Python modules for device integrations


The browser must never talk directly to device APIs if the server can do it cleanly.

### Flask should:

- serve the dashboard
- render templates
- expose small JSON API endpoints
- call Shelly devices
- keep configuration and secrets away from the browser
