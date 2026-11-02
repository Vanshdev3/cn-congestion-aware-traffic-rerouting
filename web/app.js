(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const controls = ["start-test", "start-network", "apply-rate", "apply-settings", "reset", "stop-test", "stop-network", "export"];
  let latestState = null;
  let polling = false;
  let commandBusy = false;
  let activeRoute = "A";
  let animationStarted = performance.now();
  let showCurrentRunOnly = true;

  const format = (value, suffix = "", digits = 1) => {
    const number = Number(value);
    return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : "—";
  };
  const percent = (value) => format(value, "%", 1);
  const selectedMode = () => document.querySelector("input[name=mode]:checked").value;
  const clamp = (number, low, high) => Math.max(low, Math.min(high, number));
  const setText = (id, value) => { $(id).textContent = value; };

  function toast(message, isError = false) {
    const item = $("toast");
    item.textContent = message;
    item.classList.toggle("error", isError);
    item.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => item.classList.remove("show"), 3600);
  }

  async function request(path, body) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
        signal: controller.signal,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The manager rejected the request");
      return result;
    } finally { window.clearTimeout(timer); }
  }

  function updateConnection(state, error) {
    const item = $("connection-status");
    item.classList.remove("live", "problem");
    if (error) {
      item.classList.add("problem");
      item.lastElementChild.textContent = "Manager not reachable";
    } else if (state.controller_available) {
      item.classList.add("live");
      item.lastElementChild.textContent = "Manager connected · controller live";
    } else if (state.network_running) {
      item.lastElementChild.textContent = "Manager connected · waiting for controller";
    } else {
      item.lastElementChild.textContent = "Manager connected · network stopped";
    }
  }

  function routeDescription(state) {
    if (!state.network_running) return ["READY TO PREPARE", "Start the network when you are ready", "The dashboard shows real switch counters and receiver measurements after Mininet starts.", "OFFLINE"];
    if (!state.controller_available) return ["NETWORK STARTING", "Waiting for the OpenFlow controller", state.controller_error || "Mininet is running. The manager is waiting for the switches to connect.", "WAITING"];
    const controller = state.controller || {};
    const path = controller.active_path || "A";
    if (!state.test_running) return ["NETWORK READY", `Path ${path} is prepared for the next test`, "The forwarding rules are verified. Start a static or adaptive UDP experiment.", "READY"];
    if (controller.congestion_active) return ["CONGESTION CONFIRMED", `Path ${path} is carrying the selected UDP flow`, "The controller is checking its route decision against actual switch-port counters.", "REROUTING"];
    return ["TEST RUNNING", `Traffic is using Path ${path}`, `${state.test.mode === "adaptive" ? "Adaptive" : "Static"} routing is monitoring both paths while UDP packets are sent.`, "ACTIVE"];
  }

  function updateHeader(state) {
    const [kicker, title, copy, badge] = routeDescription(state);
    setText("run-kicker", kicker); setText("run-title", title); setText("run-copy", copy); setText("run-state", badge);
    $("run-state").style.color = badge === "REROUTING" ? "var(--alert)" : "";
  }

  function updateMeter(name, load, threshold) {
    const value = Number(load);
    setText(`path-${name}-load`, percent(value));
    const meter = $(`path-${name}-meter`);
    meter.style.width = Number.isFinite(value) ? `${clamp(value, 0, 100)}%` : "0%";
    meter.classList.toggle("alert", Number.isFinite(value) && value >= threshold);
  }

  function liveReceiver(state) {
    if (state.receiver_live) return state.receiver_live;
    return state.last_result ? state.last_result.receiver : null;
  }

  function updateMeasurements(state) {
    const loads = state.path_utilisation_percent || {};
    const threshold = Number((state.test || {}).threshold_percent || (state.controller || {}).threshold_percent || $("threshold").value);
    updateMeter("a", loads.A, threshold); updateMeter("b", loads.B, threshold);
    const receiver = liveReceiver(state) || {};
    setText("receiver-rate", format(receiver.receiver_throughput_mbps, " Mbps", 2));
    setText("packet-loss", percent(receiver.packet_loss_percent));
    const received = receiver.received_expected_packets;
    const sent = (state.test && state.test.sent_packets) || receiver.sent_packets;
    setText("packet-count", Number.isFinite(Number(received)) ? `${received}${sent ? ` / ${sent}` : ""}` : "—");
    const recovery = (state.controller || {}).recovery_time_ms || (state.last_result || {}).recovery_time_ms;
    setText("recovery-time", format(recovery, " ms", 0));
    const selected = (state.controller || {}).active_path || "A";
    setText("measurement-note", `Path ${selected} is the selected route. Both values are measured separately from directional switch-port counters; the other route can still show background or transition traffic.`);
  }

  function updateTopology(state) {
    const controller = state.controller || {};
    const path = controller.active_path || "A";
    const congested = Boolean(controller.congestion_active);
    activeRoute = path;
    const routeA = $("path-a"), routeB = $("path-b");
    routeA.className.baseVal = "route"; routeB.className.baseVal = "route";
    const active = path === "B" ? routeB : routeA;
    active.classList.add("active");
    if (congested) active.classList.add("alert");
    const loads = state.path_utilisation_percent || {};
    setText("path-a-label", `Path A · ${percent(loads.A)}`);
    setText("path-b-label", `Path B · ${percent(loads.B)}`);
    const note = !state.network_running ? "Start the network to show the actual topology measurements." : congested ? `Congestion is confirmed on Path ${path}. The controller will verify traffic after a route decision.` : `Path ${path} is highlighted because it is the route selected for the UDP flow.`;
    setText("route-caption", note);
  }

  function updateLastResult(result) {
    const target = $("last-result");
    if (!result) { target.className = "empty-result"; target.textContent = "No completed test in this manager session."; return; }
    const receiver = result.receiver || {};
    target.className = "result-summary";
    target.innerHTML = [
      ["Mode / final route", `${result.mode || "—"} · Path ${result.active_path || "—"}`],
      ["Delivered rate", format(receiver.receiver_throughput_mbps, " Mbps", 2)],
      ["Packet loss", percent(receiver.packet_loss_percent)],
      ["Recovery time", format(result.recovery_time_ms, " ms", 0)],
    ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
  }

  function meaningfulEvents(state) {
    const events = state.events || [];
    if (!showCurrentRunOnly || !state.test) return events.slice(-18);
    const marker = `UDP test ${state.test.test_id}`;
    const start = events.findIndex((event) => String(event.message || "").includes(marker));
    return (start >= 0 ? events.slice(start) : events.slice(-14)).slice(-18);
  }

  function friendlyEvent(message) {
    return String(message || "").replace("Traffic-counter changes verified", "Packets are now confirmed").replace("flow entries", "forwarding rules").replace("utilisation", "link load");
  }

  function updateEvents(state) {
    const events = meaningfulEvents(state);
    const target = $("event-list");
    if (!events.length) { target.innerHTML = '<li class="muted">Waiting for an experiment event.</li>'; return; }
    target.innerHTML = events.map((event) => {
      const time = event.time ? new Date(event.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
      const kind = ["success", "warning", "error"].includes(event.kind) ? event.kind : "";
      return `<li class="${kind}"><time>${time}</time><span>${friendlyEvent(event.message)}</span></li>`;
    }).join("");
  }

  function animatePacket(now) {
    const packet = $("packet");
    if (!latestState || !latestState.network_running) { packet.style.opacity = "0"; requestAnimationFrame(animatePacket); return; }
    const elapsed = (now - animationStarted) % 4200;
    const fraction = elapsed / 4200;
    const points = activeRoute === "B" ? [[130,184],[286,184],[452,273],[650,273],[790,184]] : [[130,184],[286,184],[452,95],[650,95],[790,184]];
    const distance = fraction * (points.length - 1);
    const index = Math.min(Math.floor(distance), points.length - 2);
    const local = distance - index;
    const start = points[index], end = points[index + 1];
    packet.setAttribute("cx", start[0] + (end[0] - start[0]) * local);
    packet.setAttribute("cy", start[1] + (end[1] - start[1]) * local);
    packet.style.opacity = "1";
    requestAnimationFrame(animatePacket);
  }

  function updateControls(state) {
    $("start-test").disabled = commandBusy || !state.controller_available || state.test_running;
    $("start-network").disabled = commandBusy || state.network_running;
    $("apply-rate").disabled = commandBusy || !state.test_running;
    $("apply-settings").disabled = commandBusy || !state.network_running;
    $("reset").disabled = commandBusy || !state.controller_available;
    $("stop-test").disabled = commandBusy || !state.test_running;
    $("stop-network").disabled = commandBusy || !state.network_running;
  }

  function render(state) {
    latestState = state;
    updateConnection(state); updateHeader(state); updateMeasurements(state); updateTopology(state); updateLastResult(state.last_result); updateEvents(state); updateControls(state);
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try { render(await request("/state")); }
    catch (error) { updateConnection({}, error); }
    finally { polling = false; }
  }

  async function command(path, body, message) {
    if (commandBusy) return;
    commandBusy = true;
    if (latestState) updateControls(latestState);
    try { const result = await request(path, body); toast(message || result.path || "Command completed"); await poll(); }
    catch (error) { toast(error.name === "AbortError" ? "The manager did not respond in time." : error.message, true); }
    finally { commandBusy = false; if (latestState) updateControls(latestState); }
  }

  $("rate").addEventListener("input", () => setText("rate-value", `${Number($("rate").value).toFixed(1)} Mbps`));
  $("start-network").addEventListener("click", () => command("/command/start-network", {}, "Network started. Waiting for controller verification."));
  $("start-test").addEventListener("click", () => command("/command/start-test", { rate_mbps: Number($("rate").value), duration_seconds: Number($("duration").value), threshold_percent: Number($("threshold").value), mode: selectedMode() }, "Test started."));
  $("apply-rate").addEventListener("click", () => command("/command/set-rate", { rate_mbps: Number($("rate").value) }, "Live sender rate updated."));
  $("apply-settings").addEventListener("click", () => command("/command/configure", { mode: selectedMode(), threshold_percent: Number($("threshold").value) }, "Controller settings updated."));
  $("reset").addEventListener("click", () => command("/command/reset", { mode: selectedMode(), threshold_percent: Number($("threshold").value) }, "Reset complete. Path A is prepared."));
  $("stop-test").addEventListener("click", () => command("/command/stop-test", {}, "Test stopped and final measurements saved."));
  $("stop-network").addEventListener("click", () => command("/command/stop-network", {}, "Network stopped."));
  $("export").addEventListener("click", () => command("/export", {}, "CSV export is ready in results/experiments.csv."));
  $("clear-events").addEventListener("click", () => { showCurrentRunOnly = !showCurrentRunOnly; $("clear-events").textContent = showCurrentRunOnly ? "Show all recent" : "Show current run"; if (latestState) updateEvents(latestState); });

  requestAnimationFrame(animatePacket);
  poll();
  window.setInterval(poll, 250);
})();
