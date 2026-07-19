(function () {
  var deviceList = document.getElementById("device-list");
  var acList = document.getElementById("ac-list");
  var clockWidget = document.getElementById("clock-widget");
  var weatherTempNode = document.querySelector("[data-weather-temp]");
  var weatherLabelNode = document.querySelector("[data-weather-label]");
  var weatherTimer = null;
  var coverModal = document.getElementById("cover-modal");
  var coverModalValue = document.getElementById("cover-modal-value");
  var coverModalSlider = document.getElementById("cover-modal-slider");
  var coverModalPresets = document.getElementById("cover-modal-presets");
  var coverModalCancel = document.getElementById("cover-modal-cancel");
  var coverModalSave = document.getElementById("cover-modal-save");
  var lightModal = document.getElementById("light-modal");
  var lightModalValue = document.getElementById("light-modal-value");
  var lightModalSlider = document.getElementById("light-modal-slider");
  var lightModalPresets = document.getElementById("light-modal-presets");
  var lightModalCancel = document.getElementById("light-modal-cancel");
  var lightModalSave = document.getElementById("light-modal-save");
  var acSetpointModal = document.getElementById("ac-setpoint-modal");
  var acSetpointModalValue = document.getElementById("ac-setpoint-modal-value");
  var acSetpointModalSlider = document.getElementById("ac-setpoint-modal-slider");
  var acSetpointModalPresets = document.getElementById("ac-setpoint-modal-presets");
  var acSetpointModalCancel = document.getElementById("ac-setpoint-modal-cancel");
  var acSetpointModalSave = document.getElementById("ac-setpoint-modal-save");
  var acModeModal = document.getElementById("ac-mode-modal");
  var acModeModalOptions = document.getElementById("ac-mode-modal-options");
  var acModeModalCancel = document.getElementById("ac-mode-modal-cancel");
  var acFanModal = document.getElementById("ac-fan-modal");
  var acFanModalOptions = document.getElementById("ac-fan-modal-options");
  var acFanModalCancel = document.getElementById("ac-fan-modal-cancel");
  var refreshInFlight = false;
  var statusTimer = null;
  var acRefreshInFlight = false;
  var acStatusTimer = null;
  var activeCoverCard = null;
  var activeLightCard = null;
  var activeAcCard = null;
  var touchStartX = 0;
  var touchStartY = 0;
  var touchMoved = false;
  var suppressClickUntil = 0;
  var debugEnabled = /[?&]debug=1\b/.test(window.location.search);
  var debugBox = null;

  function debugLog(message) {
    if (!debugEnabled) {
      return;
    }
    if (!debugBox) {
      debugBox = document.createElement("pre");
      debugBox.id = "debug-box";
      debugBox.style.position = "fixed";
      debugBox.style.left = "8px";
      debugBox.style.right = "8px";
      debugBox.style.bottom = "8px";
      debugBox.style.maxHeight = "38vh";
      debugBox.style.overflow = "auto";
      debugBox.style.margin = "0";
      debugBox.style.padding = "8px";
      debugBox.style.background = "rgba(0,0,0,0.78)";
      debugBox.style.color = "#f3f3f3";
      debugBox.style.fontSize = "12px";
      debugBox.style.lineHeight = "1.3";
      debugBox.style.zIndex = "9999";
      debugBox.style.borderRadius = "8px";
      document.body.appendChild(debugBox);
    }
    debugBox.textContent += new Date().toISOString().slice(11, 19) + " " + message + "\n";
    debugBox.scrollTop = debugBox.scrollHeight;
  }

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
          debugLog("HTTP " + method + " " + url + " -> " + xhr.status);
          done(null, JSON.parse(xhr.responseText));
        } catch (_err) {
          debugLog("HTTP " + method + " " + url + " JSON parse error");
          done(new Error("Invalid JSON"));
        }
        return;
      }
      debugLog("HTTP " + method + " " + url + " -> " + xhr.status);
      done(new Error("Request failed"));
    };
    xhr.send(payload ? JSON.stringify(payload) : null);
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

  function removeClasses(el, names) {
    var i;
    for (i = 0; i < names.length; i += 1) {
      el.classList.remove(names[i]);
    }
  }

  function isPageHidden() {
    if (typeof document.hidden !== "undefined") {
      return document.hidden;
    }
    if (typeof document.webkitHidden !== "undefined") {
      return document.webkitHidden;
    }
    return false;
  }

  var visibilityChangeEventName = (typeof document.hidden !== "undefined")
    ? "visibilitychange"
    : (typeof document.webkitHidden !== "undefined")
      ? "webkitvisibilitychange"
      : null;

  function paintCard(card, info) {
    var stateNode = card.querySelector("[data-state]");
    var component = (card.getAttribute("data-component") || "relay").toLowerCase();

    if (!stateNode) {
      return;
    }

    removeClasses(card, ["is-on", "is-off", "is-error", "is-busy"]);
    removeClasses(stateNode, ["is-on", "is-off", "is-error"]);

    if (!info || !info.ok) {
      stateNode.textContent = "Offline";
      card.classList.add("is-error");
      stateNode.classList.add("is-error");
      return;
    }

    if (component === "cover") {
      if (typeof info.position === "number") {
        stateNode.textContent = String(info.position) + "%";
      } else if (info.state === "open") {
        stateNode.textContent = "100%";
      } else if (info.state === "closed") {
        stateNode.textContent = "0%";
      } else {
        stateNode.textContent = "--%";
      }
      card.classList.add("is-on");
      stateNode.classList.add("is-on");
      return;
    }

    if (component === "light") {
      if (typeof info.brightness === "number") {
        stateNode.textContent = String(info.brightness) + "%";
      } else if (info.state === "on") {
        stateNode.textContent = "On";
      } else {
        stateNode.textContent = "Off";
      }
      if (info.state === "on") {
        card.classList.add("is-on");
        stateNode.classList.add("is-on");
      } else {
        card.classList.add("is-off");
        stateNode.classList.add("is-off");
      }
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
  }

  function parsePercentText(text) {
    var parsed = parseInt(String(text || "").replace("%", ""), 10);
    if (isNaN(parsed)) {
      return 0;
    }
    if (parsed < 0) {
      return 0;
    }
    if (parsed > 100) {
      return 100;
    }
    return parsed;
  }

  function closeCoverModal() {
    if (!coverModal) {
      return;
    }
    coverModal.hidden = true;
    activeCoverCard = null;
  }

  function closeLightModal() {
    if (!lightModal) {
      return;
    }
    lightModal.hidden = true;
    activeLightCard = null;
  }

  function openCoverModal(card) {
    var stateNode;
    var current;
    if (!coverModal || !coverModalSlider || !coverModalValue) {
      return;
    }
    stateNode = card.querySelector("[data-state]");
    current = parsePercentText(stateNode ? stateNode.textContent : "0");
    activeCoverCard = card;
    coverModalSlider.value = String(current);
    coverModalValue.textContent = String(current) + "%";
    coverModal.hidden = false;
    debugLog("Open cover modal for " + card.getAttribute("data-device-id"));
  }

  function openLightModal(card) {
    var stateNode;
    var current;
    if (!lightModal || !lightModalSlider || !lightModalValue) {
      return;
    }
    stateNode = card.querySelector("[data-state]");
    current = parsePercentText(stateNode ? stateNode.textContent : "0");
    activeLightCard = card;
    lightModalSlider.value = String(current);
    lightModalValue.textContent = String(current) + "%";
    lightModal.hidden = false;
    debugLog("Open light modal for " + card.getAttribute("data-device-id"));
  }

  function setSliderAndLabel(slider, label, value) {
    var clamped = parsePercentText(value);
    if (slider) {
      slider.value = String(clamped);
    }
    if (label) {
      label.textContent = String(clamped) + "%";
    }
  }

  function nudgeSlider(slider, label, delta) {
    var current = parsePercentText(slider ? slider.value : 0);
    setSliderAndLabel(slider, label, current + delta);
  }

  function setCoverPosition(card, position) {
    requestJSON(
      "POST",
      "/api/shelly/" + card.getAttribute("data-device-id") + "/position",
      { position: position },
      function (_err, result) {
        paintCard(card, _err ? null : result);
      }
    );
  }

  function setLightBrightness(card, brightness) {
    requestJSON(
      "POST",
      "/api/shelly/" + card.getAttribute("data-device-id") + "/light_level",
      { brightness: brightness },
      function (_err, result) {
        paintCard(card, _err ? null : result);
      }
    );
  }

  function handleDeviceListActivate(target) {
    var coverCmd = closestWithAttr(target, "data-cover-cmd");
    var lightSet = closestWithAttr(target, "data-light-set");
    var card = closestWithAttr(target, "data-device-id");
    var component;

    if (!card || card.disabled) {
      debugLog("Activate ignored (no card or disabled)");
      return;
    }

    debugLog(
      "Activate on " +
        card.getAttribute("data-device-id") +
        " comp=" +
        (card.getAttribute("data-component") || "relay")
    );

    if (coverCmd) {
      requestJSON(
        "POST",
        "/api/shelly/" + card.getAttribute("data-device-id") + "/cover_action",
        { command: coverCmd.getAttribute("data-cover-cmd") },
        function (_err, result) {
          paintCard(card, _err ? null : result);
        }
      );
      return;
    }

    if (lightSet) {
      debugLog("light % pressed");
      openLightModal(card);
      return;
    }

    component = (card.getAttribute("data-component") || "relay").toLowerCase();
    if (component === "cover") {
      openCoverModal(card);
      return;
    }

    if (component === "light") {
      requestJSON(
        "POST",
        "/api/shelly/" + card.getAttribute("data-device-id") + "/light_action",
        { command: card.classList.contains("is-on") ? "off" : "on" },
        function (_err, result) {
          paintCard(card, _err ? null : result);
        }
      );
      return;
    }

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

  function refreshAll() {
    if (refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    refreshDeviceStates(function () {
      refreshInFlight = false;
    });
  }

  var acModeLabels = {
    auto: "Auto",
    cool: "Frio",
    heat: "Calor",
    dry: "Seco",
    fan: "Vent."
  };

  var acFanLabels = {
    auto: "Auto",
    low: "Baixa",
    mid: "Média",
    high: "Alta"
  };

  function paintAcCard(card, info) {
    var setpointNode = card.querySelector("[data-ac-setpoint]");
    var currentTempNode = card.querySelector("[data-ac-current-temp]");
    var powerBtn = card.querySelector("[data-ac-power]");
    var modeLabelNode = card.querySelector("[data-ac-mode-label]");
    var fanBtn = card.querySelector("[data-ac-fan-open]");

    removeClasses(card, ["is-on", "is-off", "is-error"]);

    if (!info || !info.ok) {
      card.classList.add("is-error");
      return;
    }

    card.setAttribute("data-ac-current-setpoint", String(info.setpoint));
    card.setAttribute("data-ac-current-mode", info.mode);
    card.setAttribute("data-ac-current-fan", info.fan_speed);

    if (info.power) {
      card.classList.add("is-on");
      if (powerBtn) {
        powerBtn.textContent = "Desligar";
      }
    } else {
      card.classList.add("is-off");
      if (powerBtn) {
        powerBtn.textContent = "Ligar";
      }
    }

    if (setpointNode && typeof info.setpoint === "number") {
      setpointNode.textContent = String(info.setpoint);
    }

    if (currentTempNode && typeof info.current_temp === "number") {
      currentTempNode.textContent = String(info.current_temp);
    }

    if (modeLabelNode) {
      modeLabelNode.textContent = acModeLabels[info.mode] || info.mode || "--";
    }

    if (fanBtn) {
      fanBtn.title = "Ventoinha: " + (acFanLabels[info.fan_speed] || info.fan_speed || "--");
    }
    paintFanBars(card, info.fan_speed);
  }

  function paintFanBars(card, level) {
    var bars = card.querySelectorAll(".fan-bar");
    var activeCount = { low: 1, mid: 2, high: 3 }[level] || 0;
    var isAuto = level === "auto";
    eachNode(bars, function (bar, index) {
      removeClasses(bar, ["is-active", "is-auto"]);
      if (isAuto) {
        bar.classList.add("is-auto");
      } else if (index < activeCount) {
        bar.classList.add("is-active");
      }
    });
  }

  function setAcBusy(card, busy) {
    if (busy) {
      card.classList.add("is-busy");
    } else {
      card.classList.remove("is-busy");
    }
  }

  function runAcCommand(card, method, path, payload) {
    setAcBusy(card, true);
    requestJSON(method, path, payload, function (_err, result) {
      setAcBusy(card, false);
      paintAcCard(card, _err ? null : result);
    });
  }

  function refreshAcStatus(card, done, live) {
    var url = "/api/daikin/" + card.getAttribute("data-ac-id") + "/status";
    if (live) {
      url += "?live=1";
    }
    setAcBusy(card, true);
    requestJSON(
      "GET",
      url,
      null,
      function (_err, result) {
        setAcBusy(card, false);
        paintAcCard(card, _err ? null : result);
        if (done) {
          done();
        }
      }
    );
  }

  function refreshAllAcStatuses(done) {
    var cards = document.querySelectorAll(".ac-card[data-ac-id]");
    var index = 0;

    function next() {
      if (index >= cards.length) {
        if (done) {
          done();
        }
        return;
      }
      var card = cards[index];
      index += 1;
      refreshAcStatus(card, next);
    }

    next();
  }

  function startAcStatusPolling() {
    if (acStatusTimer) {
      clearInterval(acStatusTimer);
    }
    acStatusTimer = setInterval(function () {
      if (isPageHidden() || acRefreshInFlight) {
        return;
      }
      acRefreshInFlight = true;
      refreshAllAcStatuses(function () {
        acRefreshInFlight = false;
      });
    }, 30000);
  }

  function closeAcSetpointModal() {
    if (!acSetpointModal) {
      return;
    }
    acSetpointModal.hidden = true;
    activeAcCard = null;
  }

  function openAcSetpointModal(card) {
    var current;
    if (!acSetpointModal || !acSetpointModalSlider || !acSetpointModalValue) {
      return;
    }
    current = parseInt(card.getAttribute("data-ac-current-setpoint") || "22", 10);
    if (isNaN(current)) {
      current = 22;
    }
    activeAcCard = card;
    acSetpointModalSlider.value = String(current);
    acSetpointModalValue.textContent = String(current) + "°";
    acSetpointModal.hidden = false;
  }

  function closeAcModeModal() {
    if (!acModeModal) {
      return;
    }
    acModeModal.hidden = true;
    activeAcCard = null;
  }

  function closeAcFanModal() {
    if (!acFanModal) {
      return;
    }
    acFanModal.hidden = true;
    activeAcCard = null;
  }

  function openAcModeModal(card) {
    if (!acModeModal) {
      return;
    }
    activeAcCard = card;
    acModeModal.hidden = false;
  }

  function openAcFanModal(card) {
    if (!acFanModal) {
      return;
    }
    activeAcCard = card;
    acFanModal.hidden = false;
  }

  function handleAcListActivate(target) {
    var card = closestWithAttr(target, "data-ac-id");
    var powerBtn;
    var setpointOpenBtn;
    var refreshBtn;
    var modeOpenBtn;
    var fanOpenBtn;

    if (!card || card.classList.contains("is-busy")) {
      return;
    }

    powerBtn = closestWithAttr(target, "data-ac-power");
    setpointOpenBtn = closestWithAttr(target, "data-ac-setpoint-open");
    refreshBtn = closestWithAttr(target, "data-ac-refresh");
    modeOpenBtn = closestWithAttr(target, "data-ac-mode-open");
    fanOpenBtn = closestWithAttr(target, "data-ac-fan-open");

    if (refreshBtn) {
      refreshAcStatus(card, null, true);
      return;
    }

    if (setpointOpenBtn) {
      openAcSetpointModal(card);
      return;
    }

    if (modeOpenBtn) {
      openAcModeModal(card);
      return;
    }

    if (fanOpenBtn) {
      openAcFanModal(card);
      return;
    }

    if (powerBtn) {
      runAcCommand(
        card,
        "POST",
        "/api/daikin/" + card.getAttribute("data-ac-id") + "/power",
        { state: card.classList.contains("is-on") ? "off" : "on" }
      );
      return;
    }
  }

  if (acList) {
    acList.addEventListener("click", function (event) {
      handleAcListActivate(event.target);
    });
  }

  if (acSetpointModalSlider && acSetpointModalValue) {
    acSetpointModalSlider.addEventListener("input", function () {
      acSetpointModalValue.textContent = String(acSetpointModalSlider.value) + "°";
    });
    acSetpointModalSlider.addEventListener("change", function () {
      acSetpointModalValue.textContent = String(acSetpointModalSlider.value) + "°";
    });
  }

  if (acSetpointModalPresets) {
    acSetpointModalPresets.addEventListener("click", function (event) {
      var preset = closestWithAttr(event.target, "data-ac-setpoint-preset");
      var value;
      if (!preset) {
        return;
      }
      value = preset.getAttribute("data-ac-setpoint-preset");
      if (acSetpointModalSlider) {
        acSetpointModalSlider.value = value;
      }
      if (acSetpointModalValue) {
        acSetpointModalValue.textContent = String(value) + "°";
      }
    });
  }

  if (acSetpointModalCancel) {
    acSetpointModalCancel.addEventListener("click", function () {
      closeAcSetpointModal();
    });
  }

  if (acSetpointModalSave) {
    acSetpointModalSave.addEventListener("click", function () {
      var value;
      if (!activeAcCard || !acSetpointModalSlider) {
        closeAcSetpointModal();
        return;
      }
      value = parseInt(acSetpointModalSlider.value, 10);
      runAcCommand(
        activeAcCard,
        "POST",
        "/api/daikin/" + activeAcCard.getAttribute("data-ac-id") + "/setpoint",
        { temperature: value }
      );
      closeAcSetpointModal();
    });
  }

  if (acSetpointModal) {
    acSetpointModal.addEventListener("click", function (event) {
      if (event.target === acSetpointModal) {
        closeAcSetpointModal();
      }
    });
  }

  if (acModeModalOptions) {
    acModeModalOptions.addEventListener("click", function (event) {
      var option = closestWithAttr(event.target, "data-ac-mode-option");
      var card = activeAcCard;
      if (!option || !card) {
        return;
      }
      closeAcModeModal();
      runAcCommand(
        card,
        "POST",
        "/api/daikin/" + card.getAttribute("data-ac-id") + "/mode",
        { mode: option.getAttribute("data-ac-mode-option") }
      );
    });
  }

  if (acModeModalCancel) {
    acModeModalCancel.addEventListener("click", function () {
      closeAcModeModal();
    });
  }

  if (acModeModal) {
    acModeModal.addEventListener("click", function (event) {
      if (event.target === acModeModal) {
        closeAcModeModal();
      }
    });
  }

  if (acFanModalOptions) {
    acFanModalOptions.addEventListener("click", function (event) {
      var option = closestWithAttr(event.target, "data-ac-fan-option");
      var card = activeAcCard;
      if (!option || !card) {
        return;
      }
      closeAcFanModal();
      runAcCommand(
        card,
        "POST",
        "/api/daikin/" + card.getAttribute("data-ac-id") + "/fan",
        { speed: option.getAttribute("data-ac-fan-option") }
      );
    });
  }

  if (acFanModalCancel) {
    acFanModalCancel.addEventListener("click", function () {
      closeAcFanModal();
    });
  }

  if (acFanModal) {
    acFanModal.addEventListener("click", function (event) {
      if (event.target === acFanModal) {
        closeAcFanModal();
      }
    });
  }

  function tickClock() {
    var now;
    var hh;
    var mm;
    if (!clockWidget) {
      return;
    }
    now = new Date();
    hh = String(now.getHours());
    mm = String(now.getMinutes());
    if (hh.length < 2) {
      hh = "0" + hh;
    }
    if (mm.length < 2) {
      mm = "0" + mm;
    }
    clockWidget.textContent = hh + ":" + mm;
  }

  function refreshWeather() {
    if (!weatherTempNode && !weatherLabelNode) {
      return;
    }
    requestJSON("GET", "/api/weather", null, function (_err, result) {
      if (_err || !result || !result.ok) {
        return;
      }
      if (weatherTempNode) {
        weatherTempNode.textContent = String(result.temp_c) + "°";
      }
      if (weatherLabelNode) {
        weatherLabelNode.textContent = result.condition;
      }
    });
  }

  function startWeatherPolling() {
    if (weatherTimer) {
      clearInterval(weatherTimer);
    }
    weatherTimer = setInterval(function () {
      if (isPageHidden()) {
        return;
      }
      refreshWeather();
    }, 900000);
  }

  function startStatusPolling() {
    if (statusTimer) {
      clearInterval(statusTimer);
    }
    statusTimer = setInterval(function () {
      if (isPageHidden()) {
        return;
      }
      refreshAll();
    }, 30000);
  }

  if (deviceList) {
    deviceList.addEventListener("touchstart", function (event) {
      var touch;
      if (!event.touches || !event.touches.length) {
        return;
      }
      touch = event.touches[0];
      touchStartX = touch.clientX;
      touchStartY = touch.clientY;
      touchMoved = false;
    });

    deviceList.addEventListener("touchmove", function (event) {
      var touch;
      var dx;
      var dy;
      if (!event.touches || !event.touches.length) {
        return;
      }
      touch = event.touches[0];
      dx = Math.abs(touch.clientX - touchStartX);
      dy = Math.abs(touch.clientY - touchStartY);
      if (dx > 10 || dy > 10) {
        touchMoved = true;
      }
    });

    deviceList.addEventListener("click", function (event) {
      if (Date.now() < suppressClickUntil) {
        return;
      }
      debugLog("click event");
      handleDeviceListActivate(event.target);
    });

    deviceList.addEventListener("touchend", function (event) {
      if (touchMoved) {
        debugLog("touchend ignored (scroll)");
        suppressClickUntil = Date.now() + 400;
        return;
      }
      debugLog("touchend event");
      handleDeviceListActivate(event.target);
      if (
        closestWithAttr(event.target, "data-cover-cmd") ||
        closestWithAttr(event.target, "data-light-set")
      ) {
        event.preventDefault();
      }
      suppressClickUntil = Date.now() + 400;
    });
  }

  debugLog("Debug enabled");

  if (coverModalSlider && coverModalValue) {
    coverModalSlider.addEventListener("input", function () {
      coverModalValue.textContent = String(coverModalSlider.value) + "%";
    });
    coverModalSlider.addEventListener("change", function () {
      coverModalValue.textContent = String(coverModalSlider.value) + "%";
    });
  }

  if (coverModalPresets) {
    coverModalPresets.addEventListener("click", function (event) {
      var preset = closestWithAttr(event.target, "data-cover-preset");
      if (!preset) {
        return;
      }
      setSliderAndLabel(coverModalSlider, coverModalValue, preset.getAttribute("data-cover-preset"));
    });
  }

  if (coverModalCancel) {
    coverModalCancel.addEventListener("click", function () {
      closeCoverModal();
    });
  }

  if (coverModalSave) {
    coverModalSave.addEventListener("click", function () {
      var value;
      if (!activeCoverCard || !coverModalSlider) {
        closeCoverModal();
        return;
      }
      value = parsePercentText(coverModalSlider.value);
      setCoverPosition(activeCoverCard, value);
      closeCoverModal();
    });
  }

  if (coverModal) {
    coverModal.addEventListener("click", function (event) {
      if (event.target === coverModal) {
        closeCoverModal();
      }
    });
  }

  if (lightModalSlider && lightModalValue) {
    lightModalSlider.addEventListener("input", function () {
      lightModalValue.textContent = String(lightModalSlider.value) + "%";
    });
    lightModalSlider.addEventListener("change", function () {
      lightModalValue.textContent = String(lightModalSlider.value) + "%";
    });
  }

  if (lightModalPresets) {
    lightModalPresets.addEventListener("click", function (event) {
      var preset = closestWithAttr(event.target, "data-light-preset");
      if (!preset) {
        return;
      }
      setSliderAndLabel(lightModalSlider, lightModalValue, preset.getAttribute("data-light-preset"));
    });
  }

  if (lightModal) {
    lightModal.addEventListener("click", function (event) {
      var stepBtn = closestWithAttr(event.target, "data-light-modal-step");
      if (!stepBtn) {
        return;
      }
      if (stepBtn.getAttribute("data-light-modal-step") === "up") {
        nudgeSlider(lightModalSlider, lightModalValue, 5);
      } else {
        nudgeSlider(lightModalSlider, lightModalValue, -5);
      }
    });
  }

  if (lightModalCancel) {
    lightModalCancel.addEventListener("click", function () {
      closeLightModal();
    });
  }

  if (lightModalSave) {
    lightModalSave.addEventListener("click", function () {
      var value;
      if (!activeLightCard || !lightModalSlider) {
        closeLightModal();
        return;
      }
      value = parsePercentText(lightModalSlider.value);
      setLightBrightness(activeLightCard, value);
      closeLightModal();
    });
  }

  if (lightModal) {
    lightModal.addEventListener("click", function (event) {
      if (event.target === lightModal) {
        closeLightModal();
      }
    });
  }

  if (visibilityChangeEventName) {
    document.addEventListener(visibilityChangeEventName, function () {
      if (!isPageHidden()) {
        refreshAll();
      }
    });
  }

  tickClock();
  setInterval(tickClock, 1000);
  refreshAll();
  startStatusPolling();
  refreshAllAcStatuses();
  startAcStatusPolling();
  refreshWeather();
  startWeatherPolling();
})();
