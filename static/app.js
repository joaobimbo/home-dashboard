const deviceList = document.getElementById("device-list");
const refreshButton = document.getElementById("refresh-all");
const clockWidget = document.getElementById("clock-widget");
const roomFilter = document.getElementById("room-filter");
const statusOverview = document.getElementById("status-overview");

let configuredDevices = [];
let activeRoom = "all";

async function fetchConfiguredDevices() {
  const res = await fetch("/api/shelly/configured");
  if (!res.ok) {
    throw new Error("Failed to fetch devices");
  }
  return res.json();
}

async function fetchStatus() {
  const res = await fetch("/api/shelly/devices");
  if (!res.ok) {
    throw new Error("Failed to fetch status");
  }
  return res.json();
}

function renderDevices(devices) {
  if (!deviceList) {
    return;
  }

  if (!devices.length) {
    deviceList.innerHTML = '<p class="empty-devices">No devices configured yet.</p>';
    return;
  }

  deviceList.innerHTML = devices
    .map((device) => {
      const image = device.image
        ? `<img class="device-image" src="${device.image}" alt="${device.name}">`
        : '<div class="device-image fallback-icon" aria-hidden="true">💡</div>';
      const aliases = Array.isArray(device.other_names) && device.other_names.length
        ? `<p class="aliases">${device.other_names.join(" / ")}</p>`
        : "";
      const room = device.room || "Casa";

      return `
      <button class="device-card is-off" data-device-id="${device.id}" data-room="${room}" type="button" data-action="toggle" title="Toggle ${device.name}">
        ${image}
        <div class="device-meta">
          <h3>${device.name}</h3>
          <p class="host">${device.host}</p>
          ${aliases}
          <p class="state" data-state>Checking...</p>
        </div>
      </button>`;
    })
    .join("");
}

function renderRoomFilter(devices) {
  if (!roomFilter) {
    return;
  }

  const rooms = [...new Set(devices.map((device) => device.room || "Casa"))].sort();
  roomFilter.innerHTML = ["all", ...rooms]
    .map((room) => {
      const label = room === "all" ? "Todas" : room;
      const isActive = room === activeRoom ? "is-active" : "";
      return `<button class="chip ${isActive}" type="button" data-room="${room}">${label}</button>`;
    })
    .join("");
}

function applyRoomFilter() {
  document.querySelectorAll(".device-card[data-device-id]").forEach((card) => {
    const shouldShow = activeRoom === "all" || card.getAttribute("data-room") === activeRoom;
    card.hidden = !shouldShow;
  });
}

function repaintOverview() {
  if (!statusOverview) {
    return;
  }

  const cards = Array.from(document.querySelectorAll(".device-card[data-device-id]")).filter(
    (card) => !card.hidden,
  );
  const totals = {
    total: cards.length,
    on: cards.filter((card) => card.classList.contains("is-on")).length,
    offline: cards.filter((card) => card.classList.contains("is-error")).length,
  };

  statusOverview.querySelector("[data-total]").textContent = String(totals.total);
  statusOverview.querySelector("[data-on]").textContent = String(totals.on);
  statusOverview.querySelector("[data-offline]").textContent = String(totals.offline);
}

function paintCard(card, info) {
  const stateNode = card.querySelector("[data-state]");
  card.classList.remove("is-on", "is-off", "is-error", "is-busy");
  stateNode.classList.remove("is-on", "is-off", "is-error");

  if (!info || !info.ok) {
    stateNode.textContent = "Offline";
    card.classList.add("is-error");
    stateNode.classList.add("is-error");
    repaintOverview();
    return;
  }

  if (info.state === "on") {
    stateNode.textContent = "On";
    card.classList.add("is-on");
    stateNode.classList.add("is-on");
    repaintOverview();
    return;
  }

  stateNode.textContent = "Off";
  card.classList.add("is-off");
  stateNode.classList.add("is-off");
  repaintOverview();
}

async function refreshAll() {
  try {
    const statuses = await fetchStatus();
    const statusMap = new Map(statuses.map((entry) => [entry.id, entry]));
    document.querySelectorAll(".device-card").forEach((card) => {
      paintCard(card, statusMap.get(card.dataset.deviceId));
    });
  } catch (_err) {
    document.querySelectorAll(".device-card").forEach((card) => {
      paintCard(card, null);
    });
  }
}

async function runScene(action) {
  const cards = Array.from(document.querySelectorAll(".device-card[data-device-id]")).filter(
    (card) => !card.hidden,
  );
  await Promise.all(
    cards.map(async (card) => {
      const deviceId = card.dataset.deviceId;
      try {
        const result = await sendAction(deviceId, action);
        paintCard(card, result);
      } catch (_err) {
        paintCard(card, null);
      }
    }),
  );
}

function tickClock() {
  if (!clockWidget) {
    return;
  }

  const now = new Date();
  clockWidget.textContent = now.toLocaleTimeString("pt-PT", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function bootstrapDashboard() {
  try {
    const devices = await fetchConfiguredDevices();
    configuredDevices = devices;
    renderRoomFilter(configuredDevices);
    renderDevices(configuredDevices);
    applyRoomFilter();
  } catch (_err) {
    if (deviceList) {
      deviceList.innerHTML = '<p class="empty-devices">Failed to load device list.</p>';
    }
    return;
  }

  await refreshAll();
}

async function sendAction(deviceId, action) {
  const res = await fetch(`/api/shelly/${deviceId}/action`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });

  if (!res.ok) {
    throw new Error("Action failed");
  }

  return res.json();
}

if (deviceList) {
  deviceList.addEventListener("click", async (event) => {
    const card = event.target.closest(".device-card[data-device-id]");
    if (!card) {
      return;
    }

    if (card.disabled) {
      return;
    }

    const deviceId = card.dataset.deviceId;
    const action = card.dataset.action || "toggle";
    card.disabled = true;
    card.classList.add("is-busy");

    try {
      const result = await sendAction(deviceId, action);
      paintCard(card, result);
    } catch (_err) {
      paintCard(card, null);
    } finally {
      card.disabled = false;
      card.classList.remove("is-busy");
    }
  });
}

if (refreshButton) {
  refreshButton.addEventListener("click", refreshAll);
}

if (roomFilter) {
  roomFilter.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-room]");
    if (!chip) {
      return;
    }

    activeRoom = chip.getAttribute("data-room") || "all";
    renderRoomFilter(configuredDevices);
    applyRoomFilter();
    repaintOverview();
  });
}

document.querySelectorAll("[data-scene]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.getAttribute("data-scene");
    if (action !== "on" && action !== "off") {
      return;
    }

    button.disabled = true;
    try {
      await runScene(action);
    } finally {
      button.disabled = false;
    }
  });
});

tickClock();
setInterval(tickClock, 1000);

bootstrapDashboard();
