const deviceList = document.getElementById("device-list");
const refreshButton = document.getElementById("refresh-all");

async function fetchStatus() {
  const res = await fetch("/api/shelly/devices");
  if (!res.ok) {
    throw new Error("Failed to fetch status");
  }
  return res.json();
}

function paintCard(card, info) {
  const stateNode = card.querySelector("[data-state]");
  stateNode.classList.remove("is-on", "is-off", "is-error");

  if (!info || !info.ok) {
    stateNode.textContent = "Offline";
    stateNode.classList.add("is-error");
    return;
  }

  if (info.state === "on") {
    stateNode.textContent = "On";
    stateNode.classList.add("is-on");
    return;
  }

  stateNode.textContent = "Off";
  stateNode.classList.add("is-off");
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
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }

    const card = button.closest(".device-card");
    if (!card) {
      return;
    }

    const deviceId = card.dataset.deviceId;
    const action = button.dataset.action;
    button.disabled = true;

    try {
      const result = await sendAction(deviceId, action);
      paintCard(card, result);
    } catch (_err) {
      paintCard(card, null);
    } finally {
      button.disabled = false;
    }
  });
}

if (refreshButton) {
  refreshButton.addEventListener("click", refreshAll);
}

refreshAll();
