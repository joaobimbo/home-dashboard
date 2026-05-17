(function () {
  var deviceList = document.getElementById("device-list");
  var refreshButton = document.getElementById("refresh-all");
  var clockWidget = document.getElementById("clock-widget");
  var roomFilter = document.getElementById("room-filter");
  var statusOverview = document.getElementById("status-overview");
  var deviceForm = document.getElementById("device-form");
  var formEmpty = document.getElementById("device-form-empty");
  var sceneForm = document.getElementById("scene-form");
  var sceneList = document.getElementById("scene-list");

  var configuredDevices = Array.isArray(window.__CONFIGURED_DEVICES__)
    ? window.__CONFIGURED_DEVICES__
    : [];
  var activeRoom = "all";
  var refreshInFlight = false;
  var refreshModules = [];
  var statusTimer = null;

  function requestJSON(method, url, payload, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) {
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          done(null, JSON.parse(xhr.responseText));
        } catch (_err) {
          done(new Error("Invalid JSON"));
        }
        return;
      }
      done(new Error("Request failed"));
    };
    xhr.send(payload ? JSON.stringify(payload) : null);
  }

  function byId(arr, id) {
    var i;
    for (i = 0; i < arr.length; i += 1) {
      if (arr[i] && arr[i].id === id) {
        return arr[i];
      }
    }
    return null;
  }

  function closestWithAttr(node, attrName) {
    while (node && node !== document.body) {
      if (node.getAttribute && node.getAttribute(attrName) !== null) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function eachNode(list, fn) {
    var i;
    for (i = 0; i < list.length; i += 1) {
      fn(list[i], i);
    }
  }

  function applyRoomFilter() {
    var cards = document.querySelectorAll(".device-card[data-device-id]");
    eachNode(cards, function (card) {
      var visible = activeRoom === "all" || card.getAttribute("data-room") === activeRoom;
      card.hidden = !visible;
    });
  }

  function repaintOverview() {
    if (!statusOverview) {
      return;
    }
    var cards = document.querySelectorAll(".device-card[data-device-id]");
    var total = 0;
    var onCount = 0;
    var offlineCount = 0;
    eachNode(cards, function (card) {
      if (card.hidden) {
        return;
      }
      total += 1;
      if (card.classList.contains("is-on")) {
        onCount += 1;
      }
      if (card.classList.contains("is-error")) {
        offlineCount += 1;
      }
    });
    statusOverview.querySelector("[data-total]").textContent = String(total);
    statusOverview.querySelector("[data-on]").textContent = String(onCount);
    statusOverview.querySelector("[data-offline]").textContent = String(offlineCount);
  }

  function paintCard(card, info) {
    var stateNode = card.querySelector("[data-state]");
    if (!stateNode) {
      return;
    }
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
    var cards = document.querySelectorAll(".device-card[data-device-id]");
    eachNode(cards, function (card) {
      card.classList.toggle("is-selected", card.getAttribute("data-device-id") === deviceId);
    });

    if (!deviceForm) {
      return;
    }
    var device = byId(configuredDevices, deviceId);
    if (!device) {
      return;
    }
    if (formEmpty) {
      formEmpty.hidden = true;
    }
    document.getElementById("form-device-id").value = device.id;
    document.getElementById("form-display-name").value = device.display_name || device.name || "";
    document.getElementById("form-room").value = device.room || "Casa";
    document.getElementById("form-other-names").value = (device.other_names || []).join(", ");
    document.getElementById("form-image").value = device.image || "";
  }

  function renderScenes(scenes) {
    if (!sceneList) {
      return;
    }
    if (!scenes || !scenes.length) {
      sceneList.innerHTML = '<p class="note">Sem cenas guardadas.</p>';
      return;
    }
    var html = "";
    var i;
    for (i = 0; i < scenes.length; i += 1) {
      html += '<div class="scene-item" data-scene-id="' + scenes[i].id + '">';
      html += "<div><strong>" + scenes[i].name + "</strong><br><small>";
      html += String(scenes[i].action || "").toUpperCase() + " · " + scenes[i].room;
      html += "</small></div>";
      html += '<button type="button" data-run-scene="' + scenes[i].id + '">Executar</button>';
      html += '<button type="button" data-delete-scene="' + scenes[i].id + '">Apagar</button>';
      html += "</div>";
    }
    sceneList.innerHTML = html;
  }

  function registerRefreshModule(name, refreshFn) {
    refreshModules.push({ name: name, refreshFn: refreshFn });
  }

  function refreshDeviceStates(done) {
    requestJSON("GET", "/api/shelly/devices", null, function (_err, statuses) {
      var cards;
      var i;
      var j;
      var card;
      var id;
      var info;

      cards = document.querySelectorAll(".device-card[data-device-id]");
      if (_err || !statuses) {
        eachNode(cards, function (item) {
          paintCard(item, null);
        });
        done();
        return;
      }

      for (i = 0; i < cards.length; i += 1) {
        card = cards[i];
        id = card.getAttribute("data-device-id");
        info = null;
        for (j = 0; j < statuses.length; j += 1) {
          if (statuses[j].id === id) {
            info = statuses[j];
            break;
          }
        }
        paintCard(card, info);
      }
      done();
    });
  }

  function refreshScenesModule(done) {
    if (!sceneList) {
      done();
      return;
    }
    requestJSON("GET", "/api/scenes", null, function (_err, scenes) {
      if (_err) {
        sceneList.innerHTML = '<p class="note">Falha ao carregar cenas.</p>';
      } else {
        renderScenes(scenes);
      }
      done();
    });
  }

  function runRefreshModule(index, done) {
    if (index >= refreshModules.length) {
      done();
      return;
    }
    refreshModules[index].refreshFn(function () {
      runRefreshModule(index + 1, done);
    });
  }

  function refreshAll() {
    if (refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    runRefreshModule(0, function () {
      refreshInFlight = false;
    });
  }

  function runScene(action) {
    var cards = document.querySelectorAll(".device-card[data-device-id]");
    eachNode(cards, function (card) {
      if (card.hidden) {
        return;
      }
      requestJSON(
        "POST",
        "/api/shelly/" + card.getAttribute("data-device-id") + "/action",
        { action: action },
        function (_err, result) {
          paintCard(card, _err ? null : result);
        }
      );
    });
  }

  function tickClock() {
    if (!clockWidget) {
      return;
    }
    var now = new Date();
    var hh = String(now.getHours());
    var mm = String(now.getMinutes());
    if (hh.length < 2) {
      hh = "0" + hh;
    }
    if (mm.length < 2) {
      mm = "0" + mm;
    }
    clockWidget.textContent = hh + ":" + mm;
  }

  function startStatusPolling() {
    if (statusTimer) {
      clearInterval(statusTimer);
    }
    statusTimer = setInterval(function () {
      if (document.hidden) {
        return;
      }
      refreshAll();
    }, 5000);
  }

  if (deviceList) {
    deviceList.addEventListener("click", function (event) {
      var card = closestWithAttr(event.target, "data-device-id");
      if (!card || card.disabled) {
        return;
      }
      pickDevice(card.getAttribute("data-device-id"));
      card.disabled = true;
      card.classList.add("is-busy");
      requestJSON(
        "POST",
        "/api/shelly/" + card.getAttribute("data-device-id") + "/action",
        { action: card.getAttribute("data-action") || "toggle" },
        function (_err, result) {
          paintCard(card, _err ? null : result);
          card.disabled = false;
          card.classList.remove("is-busy");
        }
      );
    });
  }

  if (roomFilter) {
    roomFilter.addEventListener("click", function (event) {
      var chip = closestWithAttr(event.target, "data-room");
      if (!chip) {
        return;
      }
      activeRoom = chip.getAttribute("data-room") || "all";
      eachNode(roomFilter.querySelectorAll(".chip"), function (node) {
        node.classList.toggle("is-active", node.getAttribute("data-room") === activeRoom);
      });
      applyRoomFilter();
      repaintOverview();
    });
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", refreshAll);
  }

  eachNode(document.querySelectorAll("[data-scene]"), function (button) {
    button.addEventListener("click", function () {
      var action = button.getAttribute("data-scene");
      if (action !== "on" && action !== "off") {
        return;
      }
      button.disabled = true;
      runScene(action);
      setTimeout(function () {
        button.disabled = false;
      }, 900);
    });
  });

  if (deviceForm) {
    deviceForm.addEventListener("submit", function (event) {
      var deviceId;
      var saveButton;
      event.preventDefault();
      deviceId = document.getElementById("form-device-id").value;
      if (!deviceId) {
        return;
      }
      saveButton = document.getElementById("save-device");
      saveButton.disabled = true;
      requestJSON(
        "POST",
        "/api/shelly/" + deviceId + "/config",
        {
          display_name: document.getElementById("form-display-name").value,
          room: document.getElementById("form-room").value,
          other_names: document.getElementById("form-other-names").value,
          image: document.getElementById("form-image").value,
        },
        function () {
          window.location.reload();
        }
      );
    });
  }

  if (sceneForm) {
    sceneForm.addEventListener("submit", function (event) {
      var name;
      var action;
      var room;
      event.preventDefault();
      name = document.getElementById("scene-name").value.replace(/^\s+|\s+$/g, "");
      action = document.getElementById("scene-action").value;
      room = document.getElementById("scene-room").value.replace(/^\s+|\s+$/g, "") || "all";
      if (!name) {
        return;
      }
      requestJSON("POST", "/api/scenes", { name: name, action: action, room: room }, function () {
        requestJSON("GET", "/api/scenes", null, function (_err, scenes) {
          if (!_err) {
            renderScenes(scenes);
          }
          sceneForm.reset();
        });
      });
    });
  }

  if (sceneList) {
    sceneList.addEventListener("click", function (event) {
      var runButton = closestWithAttr(event.target, "data-run-scene");
      var deleteButton = closestWithAttr(event.target, "data-delete-scene");

      if (runButton) {
        requestJSON(
          "POST",
          "/api/scenes/" + runButton.getAttribute("data-run-scene") + "/run",
          {},
          function () {
            refreshAll();
          }
        );
        return;
      }

      if (deleteButton) {
        requestJSON(
          "DELETE",
          "/api/scenes/" + deleteButton.getAttribute("data-delete-scene"),
          null,
          function () {
            requestJSON("GET", "/api/scenes", null, function (_err, scenes) {
              if (!_err) {
                renderScenes(scenes);
              }
            });
          }
        );
      }
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      refreshAll();
    }
  });

  registerRefreshModule("devices", refreshDeviceStates);
  registerRefreshModule("scenes", refreshScenesModule);

  applyRoomFilter();
  tickClock();
  setInterval(tickClock, 1000);
  refreshAll();
  startStatusPolling();
})();
