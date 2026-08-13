(function () {
  var deviceList = document.getElementById("device-list");
  var acList = document.getElementById("ac-list");
  var categoryTabs = document.querySelector(".category-tabs");
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
  var rgbModal = document.getElementById("rgb-modal");
  var rgbModalPreview = document.getElementById("rgb-modal-preview");
  var rgbModalColorValue = document.getElementById("rgb-modal-color-value");
  var rgbModalHue = document.getElementById("rgb-modal-hue");
  var rgbModalSaturation = document.getElementById("rgb-modal-saturation");
  var rgbModalSaturationValue = document.getElementById("rgb-modal-saturation-value");
  var rgbModalBrightness = document.getElementById("rgb-modal-brightness");
  var rgbModalBrightnessValue = document.getElementById("rgb-modal-brightness-value");
  var rgbModalPresets = document.getElementById("rgb-modal-presets");
  var rgbModalCancel = document.getElementById("rgb-modal-cancel");
  var rgbModalSave = document.getElementById("rgb-modal-save");
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
  var activeRgbCard = null;
  var selectedRgb = [255, 255, 255];
  var activeAcCard = null;
  var touchStartX = 0;
  var touchStartY = 0;
  var touchMoved = false;
  var suppressClickUntil = 0;
  var debugEnabled = /[?&]debug=1\b/.test(window.location.search);
  var debugBox = null;
  var agentForm = document.getElementById("agent-form");
  var agentMessage = document.getElementById("agent-message");
  var agentSend = document.getElementById("agent-send");
  var agentResult = document.getElementById("agent-result");
  var agentConfirmActions = document.getElementById("agent-confirm-actions");
  var agentConfirm = document.getElementById("agent-confirm");
  var agentCancel = document.getElementById("agent-cancel");
  var agentConfirmationToken = null;
  var spotifyTimer = null;
  var spotifyDevices = [];
  var spotifyPlayer = document.getElementById("spotify-player");
  var spotifyLogin = document.getElementById("spotify-login");
  var spotifyUnconfigured = document.getElementById("spotify-unconfigured");
  var spotifyDevice = document.getElementById("spotify-device");
  var spotifyVolume = document.getElementById("spotify-volume");
  var spotifyVolumeValue = document.getElementById("spotify-volume-value");

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
      try {
        done(new Error("Request failed"), JSON.parse(xhr.responseText));
      } catch (_error) {
        done(new Error("Request failed"));
      }
    };
    xhr.send(payload ? JSON.stringify(payload) : null);
  }

  function showAgentResult(message, isError) {
    if (!agentResult) {
      return;
    }
    agentResult.hidden = false;
    agentResult.textContent = message;
    if (isError) {
      agentResult.classList.add("is-error");
    } else {
      agentResult.classList.remove("is-error");
    }
  }

  function setAgentBusy(busy) {
    if (agentSend) {
      agentSend.disabled = busy;
      agentSend.textContent = busy ? "A interpretar…" : "Enviar";
    }
  }

  function clearAgentConfirmation() {
    agentConfirmationToken = null;
    if (agentConfirmActions) {
      agentConfirmActions.hidden = true;
    }
  }

  function spotifyMessage(value, error) {
    var node = document.getElementById("spotify-message");
    if (!node) { return; }
    node.hidden = !value;
    node.textContent = value || "";
    if (error) { node.classList.add("is-error"); } else { node.classList.remove("is-error"); }
  }

  function refreshSpotify() {
    requestJSON("GET", "/api/spotify/auth/status", null, function (_err, auth) {
      if (!auth || !auth.configured) { if (spotifyUnconfigured) { spotifyUnconfigured.hidden = false; } return; }
      if (!auth.authenticated) { if (spotifyLogin) { spotifyLogin.hidden = false; } return; }
      if (spotifyPlayer) { spotifyPlayer.hidden = false; }
      requestJSON("GET", "/api/spotify/status", null, function (_statusErr, status) {
        var track; var art = document.getElementById("spotify-art");
        if (!status || !status.ok) { spotifyMessage((status && status.error) || "Spotify indisponível.", true); return; }
        track = status.track;
        document.getElementById("spotify-track").textContent = track ? track.name : "Sem reprodução ativa";
        document.getElementById("spotify-artist").textContent = track ? track.artists.join(", ") : "—";
        document.getElementById("spotify-album").textContent = track ? (track.album || "") : "—";
        document.getElementById("spotify-toggle").textContent = status.is_playing ? "❚❚" : "▶";
        if (art) { art.hidden = !(track && track.image); if (track && track.image) { art.src = track.image; } }
        if (spotifyVolume && status.device) { spotifyVolume.value = status.device.volume_percent || 0; spotifyVolume.disabled = !status.device.supports_volume; spotifyVolumeValue.textContent = status.device.supports_volume ? String(spotifyVolume.value) + "%" : "indisponível"; }
      });
      requestJSON("GET", "/api/spotify/devices", null, function (_deviceErr, result) {
        var i; var option;
        if (!result || !result.ok || !spotifyDevice) { return; }
        spotifyDevices = result.devices || []; spotifyDevice.innerHTML = "";
        for (i = 0; i < spotifyDevices.length; i += 1) { option = document.createElement("option"); option.value = spotifyDevices[i].id; option.textContent = (spotifyDevices[i].is_active ? "✓ " : "") + spotifyDevices[i].name; option.selected = spotifyDevices[i].is_active; spotifyDevice.appendChild(option); }
      });
    });
  }

  function spotifyPost(path, payload) { requestJSON("POST", path, payload, function (err, result) { spotifyMessage(err || !result || !result.ok ? ((result && result.error) || "Pedido Spotify falhou.") : "", true); refreshSpotify(); }); }

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

  function showCategory(name) {
    var sections = document.querySelectorAll("[data-category-section]");
    var tabs = document.querySelectorAll("[data-category-tab]");
    eachNode(sections, function (section) {
      section.hidden = section.getAttribute("data-category-section") !== name;
    });
    eachNode(tabs, function (tab) {
      var isActive = tab.getAttribute("data-category-tab") === name;
      if (isActive) {
        tab.classList.add("is-active");
      } else {
        tab.classList.remove("is-active");
      }
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    });
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

  function clampByte(value) {
    var parsed = parseInt(value, 10);
    if (isNaN(parsed)) {
      return 0;
    }
    return Math.max(0, Math.min(255, parsed));
  }

  function normalizeRgb(rgb) {
    if (!rgb || rgb.length !== 3) {
      return [255, 255, 255];
    }
    return [clampByte(rgb[0]), clampByte(rgb[1]), clampByte(rgb[2])];
  }

  function rgbCss(rgb) {
    return "rgb(" + rgb[0] + ", " + rgb[1] + ", " + rgb[2] + ")";
  }

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

    if (component === "rgbcct") {
      var rgb = normalizeRgb(info.rgb);
      var swatch = card.querySelector("[data-rgb-card-swatch]");
      var brightness = typeof info.brightness === "number"
        ? Math.max(1, Math.min(100, Math.round(info.brightness)))
        : 100;

      card.setAttribute("data-rgb-red", String(rgb[0]));
      card.setAttribute("data-rgb-green", String(rgb[1]));
      card.setAttribute("data-rgb-blue", String(rgb[2]));
      card.setAttribute("data-rgb-brightness", String(brightness));

      if (swatch) {
        swatch.style.backgroundColor = rgbCss(rgb);
        swatch.style.opacity = info.state === "on" ? "1" : "0.4";
      }

      if (info.state === "on") {
        stateNode.textContent = String(brightness) + "%";
        card.classList.add("is-on");
        stateNode.classList.add("is-on");
      } else {
        stateNode.textContent = "Off";
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

  function closeRgbModal() {
    if (!rgbModal) {
      return;
    }
    rgbModal.hidden = true;
    activeRgbCard = null;
  }

  function rgbToHsv(rgb) {
    var red = rgb[0] / 255;
    var green = rgb[1] / 255;
    var blue = rgb[2] / 255;
    var maxValue = Math.max(red, green, blue);
    var minValue = Math.min(red, green, blue);
    var difference = maxValue - minValue;
    var hue = 0;
    var saturation = maxValue === 0 ? 0 : difference / maxValue;

    if (difference !== 0) {
      if (maxValue === red) {
        hue = 60 * (((green - blue) / difference) % 6);
      } else if (maxValue === green) {
        hue = 60 * (((blue - red) / difference) + 2);
      } else {
        hue = 60 * (((red - green) / difference) + 4);
      }
    }
    if (hue < 0) {
      hue += 360;
    }
    return { hue: Math.round(hue), saturation: Math.round(saturation * 100) };
  }

  function hsvToRgb(hue, saturation) {
    var normalizedHue = ((hue % 360) + 360) % 360;
    var normalizedSaturation = Math.max(0, Math.min(100, saturation)) / 100;
    var chroma = normalizedSaturation;
    var second = chroma * (1 - Math.abs(((normalizedHue / 60) % 2) - 1));
    var match = 1 - chroma;
    var red = 0;
    var green = 0;
    var blue = 0;

    if (normalizedHue < 60) {
      red = chroma;
      green = second;
    } else if (normalizedHue < 120) {
      red = second;
      green = chroma;
    } else if (normalizedHue < 180) {
      green = chroma;
      blue = second;
    } else if (normalizedHue < 240) {
      green = second;
      blue = chroma;
    } else if (normalizedHue < 300) {
      red = second;
      blue = chroma;
    } else {
      red = chroma;
      blue = second;
    }

    return [
      Math.round((red + match) * 255),
      Math.round((green + match) * 255),
      Math.round((blue + match) * 255)
    ];
  }

  function paintRgbModal() {
    var hue;
    var fullColor;
    if (!rgbModalHue || !rgbModalSaturation) {
      return;
    }
    hue = parseInt(rgbModalHue.value, 10) || 0;
    fullColor = hsvToRgb(hue, 100);
    if (rgbModalPreview) {
      rgbModalPreview.style.backgroundColor = rgbCss(selectedRgb);
    }
    if (rgbModalColorValue) {
      rgbModalColorValue.textContent = rgbCss(selectedRgb);
    }
    if (rgbModalSaturationValue) {
      rgbModalSaturationValue.textContent = String(rgbModalSaturation.value) + "%";
    }
    if (rgbModalSaturation) {
      rgbModalSaturation.style.background =
        "linear-gradient(to right, rgb(255, 255, 255), " + rgbCss(fullColor) + ")";
    }
  }

  function setRgbSelection(rgb) {
    var hsv;
    selectedRgb = normalizeRgb(rgb);
    hsv = rgbToHsv(selectedRgb);
    if (rgbModalHue) {
      rgbModalHue.value = String(hsv.hue);
    }
    if (rgbModalSaturation) {
      rgbModalSaturation.value = String(hsv.saturation);
    }
    paintRgbModal();
  }

  function updateRgbFromSliders() {
    var hue = parseInt(rgbModalHue ? rgbModalHue.value : "0", 10) || 0;
    var saturation = parseInt(rgbModalSaturation ? rgbModalSaturation.value : "0", 10) || 0;
    selectedRgb = hsvToRgb(hue, saturation);
    paintRgbModal();
  }

  function openRgbModal(card) {
    var red;
    var green;
    var blue;
    var brightness;
    if (!rgbModal || !rgbModalBrightness || !rgbModalBrightnessValue) {
      return;
    }
    red = card.getAttribute("data-rgb-red");
    green = card.getAttribute("data-rgb-green");
    blue = card.getAttribute("data-rgb-blue");
    if (red === null || green === null || blue === null) {
      red = 255;
      green = 255;
      blue = 255;
    }
    brightness = parseInt(card.getAttribute("data-rgb-brightness"), 10);
    if (isNaN(brightness)) {
      brightness = 100;
    }
    brightness = Math.max(1, Math.min(100, brightness));
    activeRgbCard = card;
    rgbModalBrightness.value = String(brightness);
    rgbModalBrightnessValue.textContent = String(brightness) + "%";
    setRgbSelection([red, green, blue]);
    rgbModal.hidden = false;
    debugLog("Open RGB modal for " + card.getAttribute("data-device-id"));
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

  function setRgbColor(card, rgb, brightness) {
    card.disabled = true;
    card.classList.add("is-busy");
    requestJSON(
      "POST",
      "/api/shelly/" + card.getAttribute("data-device-id") + "/rgbcct",
      { on: true, brightness: brightness, mode: "rgb", rgb: rgb },
      function (_err, result) {
        paintCard(card, _err ? null : result);
        card.disabled = false;
        card.classList.remove("is-busy");
      }
    );
  }

  function handleDeviceListActivate(target) {
    var coverCmd = closestWithAttr(target, "data-cover-cmd");
    var lightSet = closestWithAttr(target, "data-light-set");
    var rgbSet = closestWithAttr(target, "data-rgb-set");
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

    if (rgbSet) {
      debugLog("RGB settings pressed");
      openRgbModal(card);
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

  if (categoryTabs) {
    categoryTabs.addEventListener("click", function (event) {
      var tab = closestWithAttr(event.target, "data-category-tab");
      if (!tab) {
        return;
      }
      showCategory(tab.getAttribute("data-category-tab"));
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
        closestWithAttr(event.target, "data-light-set") ||
        closestWithAttr(event.target, "data-rgb-set")
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

  if (rgbModalHue) {
    rgbModalHue.addEventListener("input", updateRgbFromSliders);
    rgbModalHue.addEventListener("change", updateRgbFromSliders);
  }

  if (rgbModalSaturation) {
    rgbModalSaturation.addEventListener("input", updateRgbFromSliders);
    rgbModalSaturation.addEventListener("change", updateRgbFromSliders);
  }

  if (rgbModalBrightness && rgbModalBrightnessValue) {
    rgbModalBrightness.addEventListener("input", function () {
      rgbModalBrightnessValue.textContent = String(rgbModalBrightness.value) + "%";
    });
    rgbModalBrightness.addEventListener("change", function () {
      rgbModalBrightnessValue.textContent = String(rgbModalBrightness.value) + "%";
    });
  }

  if (rgbModalPresets) {
    rgbModalPresets.addEventListener("click", function (event) {
      var preset = closestWithAttr(event.target, "data-rgb-preset");
      var values;
      if (!preset) {
        return;
      }
      values = preset.getAttribute("data-rgb-preset").split(",");
      setRgbSelection(values);
    });
  }

  if (rgbModalCancel) {
    rgbModalCancel.addEventListener("click", closeRgbModal);
  }

  if (rgbModalSave) {
    rgbModalSave.addEventListener("click", function () {
      var card = activeRgbCard;
      var brightness;
      if (!card || !rgbModalBrightness) {
        closeRgbModal();
        return;
      }
      brightness = Math.max(1, Math.min(100, parseInt(rgbModalBrightness.value, 10) || 100));
      closeRgbModal();
      setRgbColor(card, selectedRgb.slice(0), brightness);
    });
  }

  if (rgbModal) {
    rgbModal.addEventListener("click", function (event) {
      if (event.target === rgbModal) {
        closeRgbModal();
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

  if (agentForm) {
    agentForm.addEventListener("submit", function (event) {
      var message = agentMessage ? agentMessage.value.replace(/^\s+|\s+$/g, "") : "";
      event.preventDefault();
      clearAgentConfirmation();
      if (!message) {
        showAgentResult("Escreva um pedido para o assistente.", true);
        return;
      }
      setAgentBusy(true);
      showAgentResult("A interpretar o pedido…", false);
      requestJSON("POST", "/api/agent/request", {message: message}, function (err, result) {
        setAgentBusy(false);
        if (err || !result || !result.ok) {
          showAgentResult((result && result.error) || "Não foi possível contactar o assistente.", true);
          return;
        }
        showAgentResult(result.message || "Concluído.", false);
        if (result.kind === "automation_confirmation" && result.token) {
          agentConfirmationToken = result.token;
          if (agentConfirmActions) {
            agentConfirmActions.hidden = false;
          }
        }
      });
    });
  }

  if (agentCancel) {
    agentCancel.addEventListener("click", function () {
      clearAgentConfirmation();
      showAgentResult("Automação cancelada.", false);
    });
  }

  if (agentConfirm) {
    agentConfirm.addEventListener("click", function () {
      var token = agentConfirmationToken;
      if (!token) {
        return;
      }
      agentConfirm.disabled = true;
      agentConfirm.textContent = "A guardar…";
      requestJSON("POST", "/api/agent/confirm", {token: token}, function (err, result) {
        agentConfirm.disabled = false;
        agentConfirm.textContent = "Guardar automação";
        clearAgentConfirmation();
        if (err || !result || !result.ok) {
          showAgentResult((result && result.error) || "Não foi possível guardar a automação.", true);
          return;
        }
        showAgentResult(result.message || "Automação guardada.", false);
      });
    });
  }

  document.addEventListener("click", function (event) {
    var button = closestWithAttr(event.target, "data-spotify-command");
    var command;
    if (!button) { return; }
    command = button.getAttribute("data-spotify-command");
    if (command === "toggle") { command = button.textContent === "❚❚" ? "pause" : "play"; }
    spotifyPost("/api/spotify/" + command, {device_id: spotifyDevice ? spotifyDevice.value : null});
  });

  if (spotifyDevice) { spotifyDevice.addEventListener("change", function () { spotifyPost("/api/spotify/device", {device_id: spotifyDevice.value}); }); }
  if (spotifyVolume) { spotifyVolume.addEventListener("change", function () { spotifyPost("/api/spotify/volume", {volume: parseInt(spotifyVolume.value, 10), device_id: spotifyDevice ? spotifyDevice.value : null}); }); }
  if (document.getElementById("spotify-search-form")) {
    document.getElementById("spotify-search-form").addEventListener("submit", function (event) {
      var query = document.getElementById("spotify-search-query").value; var results = document.getElementById("spotify-results");
      event.preventDefault();
      requestJSON("GET", "/api/spotify/search?q=" + encodeURIComponent(query), null, function (err, result) {
        var i; var item; var button;
        if (err || !result || !result.ok) { spotifyMessage((result && result.error) || "A pesquisa falhou.", true); return; }
        results.innerHTML = ""; results.hidden = false;
        for (i = 0; i < result.results.length; i += 1) { item = result.results[i]; button = document.createElement("button"); button.type = "button"; button.className = "spotify-result"; button.setAttribute("data-spotify-uri", item.uri); button.textContent = item.name + " — " + item.subtitle; results.appendChild(button); }
      });
    });
    document.getElementById("spotify-results").addEventListener("click", function (event) { var item = closestWithAttr(event.target, "data-spotify-uri"); if (item) { spotifyPost("/api/spotify/play-uri", {uri: item.getAttribute("data-spotify-uri"), device_id: spotifyDevice ? spotifyDevice.value : null}); } });
  }

  tickClock();
  setInterval(tickClock, 1000);
  refreshAll();
  startStatusPolling();
  refreshAllAcStatuses();
  startAcStatusPolling();
  refreshWeather();
  startWeatherPolling();
  refreshSpotify();
  spotifyTimer = setInterval(function () { if (!isPageHidden()) { refreshSpotify(); } }, 10000);
})();
