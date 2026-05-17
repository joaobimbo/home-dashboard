const deviceList = document.getElementById("device-list");
const refreshButton = document.getElementById("refresh-all");
const clockWidget = document.getElementById("clock-widget");
const roomFilter = document.getElementById("room-filter");
const statusOverview = document.getElementById("status-overview");
const deviceForm = document.getElementById("device-form");
const formEmpty = document.getElementById("device-form-empty");
const sceneForm = document.getElementById("scene-form");
const sceneList = document.getElementById("scene-list");

let configuredDevices = Array.isArray(window.__CONFIGURED_DEVICES__)
  ? window.__CONFIGURED_DEVICES__
  : [];
let activeRoom = "all";

async function fetchStatus() {
  const res = await fetch("/api/shelly/devices");
  if (!res.ok) {
    throw new Error("Failed to fetch status");
  }
  return res.json();
}

async function sendAction(deviceId, action) {
  const res = await fetch(`/api/shelly/${deviceId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) {
    throw new Error("Action failed");
  }
  return res.json();
}

async function updateDeviceConfig(deviceId, payload) {
  const res = await fetch(`/api/shelly/${deviceId}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error("Failed to update device config");
  }
  return res.json();
}

async function fetchScenes() {
  const res = await fetch("/api/scenes");
  if (!res.ok) {
    throw new Error("Failed to fetch scenes");
  }
  return res.json();
}

async function createScene(payload) {
  const res = await fetch("/api/scenes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error("Failed to create scene");
  }
  return res.json();
}

async function runSavedScene(sceneId) {
  const res = await fetch(`/api/scenes/${sceneId}/run`, { method: "POST" });
  if (!res.ok) {
    throw new Error("Failed to run scene");
  }
  return res.json();
}

async function deleteSavedScene(sceneId) {
  const res = await fetch(`/api/scenes/${sceneId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error("Failed to delete scene");
  }
  return res.json();
}

function applyRoomFilter() {
  document.querySelectorAll(".device-card[data-device-id]").forEach((card) => {
    const visible = activeRoom === "all" || card.dataset.room === activeRoom;
    card.hidden = !visible;
  });
}

function repaintOverview() {
  if (!statusOverview) {
    return;
  }
  const cards = Array.from(document.querySelectorAll(".device-card[data-device-id]")).filter(
    (card) => !card.hidden,
  );
  const onCount = cards.filter((card) => card.classList.contains("is-on")).length;
  const offlineCount = cards.filter((card) => card.classList.contains("is-error")).length;
  statusOverview.querySelector("[data-total]").textContent = String(cards.length);
  statusOverview.querySelector("[data-on]").textContent = String(onCount);
  statusOverview.querySelector("[data-offline]").textContent = String(offlineCount);
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
  } else {
    stateNode.textContent = "Off";
    card.classList.add("is-off");
    stateNode.classList.add("is-off");
  }
  repaintOverview();
}

function pickDevice(deviceId) {
  document.querySelectorAll(".device-card").forEach((card) => {
    card.classList.toggle("is-selected", card.dataset.deviceId === deviceId);
  });
  const device = configuredDevices.find((item) => item.id === deviceId);
  if (!device || !deviceForm) {
    return;
  }
  if (formEmpty) {
    formEmpty.hidden = true;
  }
  document.getElementById("form-device-id").value = device.id;
  document.getElementById("form-display-name").value = device.display_name || device.name;
  document.getElementById("form-room").value = device.room || "Casa";
  document.getElementById("form-other-names").value = (device.other_names || []).join(", ");
  document.getElementById("form-image").value = device.image || "";
}

function renderScenes(scenes) {
  if (!sceneList) {
    return;
  }
  if (!scenes.length) {
    sceneList.innerHTML = '<p class="note">Sem cenas guardadas.</p>';
    return;
  }
  sceneList.innerHTML = scenes
    .map(
      (scene) => `
      <div class="scene-item" data-scene-id="${scene.id}">
        <div><strong>${scene.name}</strong><br><small>${scene.action.toUpperCase()} · ${scene.room}</small></div>
        <button type="button" data-run-scene="${scene.id}">Executar</button>
        <button type="button" data-delete-scene="${scene.id}">Apagar</button>
      </div>`,
    )
    .join("");
}

async function refreshAll() {
  try {
    const statuses = await fetchStatus();
    const statusMap = new Map(statuses.map((entry) => [entry.id, entry]));
    document.querySelectorAll(".device-card[data-device-id]").forEach((card) => {
      paintCard(card, statusMap.get(card.dataset.deviceId));
    });
  } catch (_err) {
    document.querySelectorAll(".device-card[data-device-id]").forEach((card) => {
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
      try {
        const result = await sendAction(card.dataset.deviceId, action);
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

if (deviceList) {
  deviceList.addEventListener("click", async (event) => {
    const card = event.target.closest(".device-card[data-device-id]");
    if (!card || card.disabled) {
      return;
    }

    pickDevice(card.dataset.deviceId);
    card.disabled = true;
    card.classList.add("is-busy");
    try {
      const result = await sendAction(card.dataset.deviceId, card.dataset.action || "toggle");
      paintCard(card, result);
    } catch (_err) {
      paintCard(card, null);
    } finally {
      card.disabled = false;
      card.classList.remove("is-busy");
    }
  });
}

if (roomFilter) {
  roomFilter.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-room]");
    if (!chip) {
      return;
    }
    activeRoom = chip.dataset.room || "all";
    roomFilter.querySelectorAll(".chip").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.room === activeRoom);
    });
    applyRoomFilter();
    repaintOverview();
  });
}

if (refreshButton) {
  refreshButton.addEventListener("click", refreshAll);
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

if (deviceForm) {
  deviceForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const deviceId = document.getElementById("form-device-id").value;
    if (!deviceId) {
      return;
    }
    const payload = {
      display_name: document.getElementById("form-display-name").value,
      room: document.getElementById("form-room").value,
      other_names: document.getElementById("form-other-names").value,
      image: document.getElementById("form-image").value,
    };
    const saveButton = document.getElementById("save-device");
    saveButton.disabled = true;
    try {
      await updateDeviceConfig(deviceId, payload);
      window.location.reload();
    } finally {
      saveButton.disabled = false;
    }
  });
}

if (sceneForm) {
  sceneForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("scene-name").value.trim();
    const action = document.getElementById("scene-action").value;
    const room = document.getElementById("scene-room").value.trim() || "all";
    if (!name) {
      return;
    }
    await createScene({ name, action, room });
    const scenes = await fetchScenes();
    renderScenes(scenes);
    sceneForm.reset();
  });
}

if (sceneList) {
  sceneList.addEventListener("click", async (event) => {
    const runButton = event.target.closest("[data-run-scene]");
    if (runButton) {
      await runSavedScene(runButton.dataset.runScene);
      await refreshAll();
      return;
    }
    const deleteButton = event.target.closest("[data-delete-scene]");
    if (deleteButton) {
      await deleteSavedScene(deleteButton.dataset.deleteScene);
      const scenes = await fetchScenes();
      renderScenes(scenes);
    }
  });
}

async function bootstrap() {
  applyRoomFilter();
  await refreshAll();
  try {
    const scenes = await fetchScenes();
    renderScenes(scenes);
  } catch (_err) {
    if (sceneList) {
      sceneList.innerHTML = '<p class="note">Falha ao carregar cenas.</p>';
    }
  }
}

tickClock();
setInterval(tickClock, 1000);
bootstrap();
