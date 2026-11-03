(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let latestState = null;
  let polling = false;
  let commandBusy = false;
  let activeRoute = "A";
  let routeChangeUntil = 0;
  let animationStarted = performance.now();
  let showCurrentRunOnly = true;
  // A visual sample is deliberately held until the controller completes the
  // next counter sample.  That prevents the numbers from changing before the
  // route colour and packet stream describe the same network state.
  let visualSample = null;
  let visibleState = null;

  const hasNumber = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const format = (value, suffix = "", digits = 1) => {
    const number = Number(value);
    return hasNumber(value) ? `${number.toFixed(digits)}${suffix}` : "—";
  };
  const percent = (value) => format(value, "%", 1);
  const displayedPercent = (value) => hasNumber(value) && Number(value) >= 100 ? "100%+" : percent(value);
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

  function sampleForDisplay(state) {
    const controller = state.controller || {};
    const generation = controller.measurement_generation ?? 0;
    const changed = !visualSample
      || visualSample.generation !== generation
      || visualSample.testRunning !== state.test_running
      || visualSample.networkRunning !== state.network_running;
    if (changed) {
      visualSample = {
        generation,
        testRunning: state.test_running,
        networkRunning: state.network_running,
        path: controller.active_path || "A",
        congested: Boolean(controller.congestion_active),
        loads: { ...(state.path_utilisation_percent || {}) },
        links: { ...(state.links || {}) },
        receiver: state.receiver_live ? { ...state.receiver_live } : null,
      };
      if (visualSample.path !== activeRoute) {
        activeRoute = visualSample.path;
        routeChangeUntil = Date.now() + 1400;
      }
      // Restart the packet pattern exactly when this visual sample changes.
      animationStarted = performance.now();
    }
    return {
      ...state,
      path_utilisation_percent: visualSample.loads,
      links: visualSample.links,
      receiver_live: visualSample.receiver,
      controller: state.controller ? {
        ...state.controller,
        active_path: visualSample.path,
        congestion_active: visualSample.congested,
      } : state.controller,
    };
  }

  function routeDescription(state) {
    if (!state.network_running) return ["READY TO PREPARE", "Start the network when you are ready", "The dashboard shows real switch counters and receiver measurements after Mininet starts.", "OFFLINE"];
    if (!state.controller_available) return ["NETWORK STARTING", "Waiting for the OpenFlow controller", state.controller_error || "Mininet is running. The manager is waiting for the switches to connect.", "WAITING"];
    const controller = state.controller || {};
    const path = controller.active_path || "A";
    if (!state.test_running && state.last_result) return ["TEST COMPLETE", `Last test finished on Path ${path}`, "No UDP packets are being sent now, so live link loads return to zero. The final result is saved below and in the CSV.", "COMPLETE"];
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
    const label = `path-${name}-load`;
    setText(label, hasNumber(load) ? displayedPercent(value) : "Waiting for traffic");
    $(label).title = hasNumber(load) && value > 100
      ? `Raw counter calculation: ${percent(value)}. The link is saturated; short sample intervals can report a burst above its configured capacity.`
      : "";
    const meter = $(`path-${name}-meter`);
    meter.style.width = hasNumber(load) ? `${clamp(value, 0, 100)}%` : "0%";
    meter.classList.toggle("alert", hasNumber(load) && value >= threshold);
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
    setText("receiver-rate", hasNumber(receiver.receiver_throughput_mbps) ? format(receiver.receiver_throughput_mbps, " Mbps", 2) : "Waiting for packets");
    setText("packet-loss", hasNumber(receiver.packet_loss_percent) ? percent(receiver.packet_loss_percent) : "Calculated at finish");
    const received = receiver.received_expected_packets;
    const sent = (state.test && state.test.sent_packets) ?? receiver.sent_packets;
    setText("packet-count", hasNumber(received) ? `${received}${hasNumber(sent) ? ` / ${sent}` : ""}` : "Waiting for packets");
    const recovery = (state.controller || {}).recovery_time_ms || (state.last_result || {}).recovery_time_ms;
    setText("recovery-time", hasNumber(recovery) ? format(recovery, " ms", 0) : "Waiting for reroute");
    const selected = (state.controller || {}).active_path || "A";
    setText("measurement-note", `Path ${selected} is the selected route. Both values are measured separately from directional switch-port counters; the other route can still show background or transition traffic.`);
    for (const name of ["A", "B"]) {
      const pathLinks = new Set((((state.port_map || {}).forward_counters || {})[name] || []).map((entry) => entry.link));
      const busiest = Object.entries(state.links || {})
        .filter(([linkName, sample]) => pathLinks.has(linkName) && sample.fresh && hasNumber(sample.rate_bps) && hasNumber(sample.capacity_mbps))
        .map(([linkName, sample]) => ({ linkName, ...sample }))
        .sort((left, right) => (right.utilisation_percent || 0) - (left.utilisation_percent || 0))[0];
      const rawLoad = busiest && Number(busiest.utilisation_percent) > 100
        ? `${format(busiest.utilisation_percent, "%", 1)} observed (short-interval burst)`
        : busiest ? format(busiest.utilisation_percent, "%", 1) : null;
      $("formula-" + name.toLowerCase()).textContent = busiest
        ? `Path ${name}, ${busiest.linkName}: (${Math.round(busiest.rate_bps).toLocaleString()} bps) ÷ (${busiest.capacity_mbps} Mbps × 1,000,000) × 100 = ${rawLoad}`
        : `Path ${name}: waiting for fresh byte-counter samples`;
    }
  }

  function updateTopology(state) {
    const controller = state.controller || {};
    const path = controller.active_path || "A";
    const congested = Boolean(controller.congestion_active);
    const routeA = $("path-a"), routeB = $("path-b");
    routeA.className.baseVal = "route"; routeB.className.baseVal = "route";
    if (state.test_running) {
      const active = path === "B" ? routeB : routeA;
      active.classList.add("active");
      if (congested) active.classList.add("alert");
      if (Date.now() < routeChangeUntil && !congested) active.classList.add("verified");
    }
    const loads = state.path_utilisation_percent || {};
    setText("path-a-label", `Path A  ·  ${displayedPercent(loads.A)}`);
    setText("path-b-label", `Path B  ·  ${displayedPercent(loads.B)}`);
    const note = !state.network_running ? "Start the network to show the actual topology measurements." : !state.test_running && state.last_result ? `The test is complete. Path ${path} was the final selected route; the gray paths and zero live load mean traffic has stopped.` : congested ? `Congestion is confirmed on Path ${path}: orange packet dots show the busy route while the controller verifies its decision.` : `Path ${path} is highlighted because it currently carries the selected UDP flow.`;
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

  function pointOnRoute(points, fraction) {
    const distance = fraction * (points.length - 1);
    const index = Math.min(Math.floor(distance), points.length - 2);
    const local = distance - index;
    const start = points[index], end = points[index + 1];
    return [start[0] + (end[0] - start[0]) * local, start[1] + (end[1] - start[1]) * local];
  }

  function animatePacket(now) {
    const stream = $("packet-stream");
    const running = visibleState && visibleState.test_running;
    if (!running) { if (stream.childElementCount) stream.replaceChildren(); requestAnimationFrame(animatePacket); return; }
    const congested = Boolean((visibleState.controller || {}).congestion_active);
    stream.classList.toggle("packet-stream-congested", congested);
    while (stream.children.length < 8) {
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("class", stream.children.length === 0 ? "packet-dot lead" : "packet-dot");
      dot.setAttribute("r", stream.children.length === 0 ? "7.5" : "5.3");
      stream.append(dot);
    }
    const elapsed = now - animationStarted;
    [...stream.children].forEach((dot, index) => {
      const spacing = congested ? 270 : 490;
      const duration = congested ? 4100 : 5000;
      const fraction = ((elapsed - index * spacing) % duration + duration) % duration / duration;
      const [x, y] = pointOnRoute(activeRoute === "B"
        ? [[200,256],[265,256],[405,290],[475,390],[615,390],[725,290],[865,256],[930,256]]
        : [[200,256],[265,256],[405,222],[475,130],[615,130],[725,222],[865,256],[930,256]], fraction);
      dot.setAttribute("cx", x); dot.setAttribute("cy", y);
    });
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
    visibleState = sampleForDisplay(state);
    updateConnection(state); updateHeader(visibleState); updateMeasurements(visibleState); updateTopology(visibleState); updateLastResult(state.last_result); updateEvents(state); updateControls(state);
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

  function syncRate(value) {
    const rate = clamp(Number(value) || 0.5, 0.5, 10);
    $("rate").value = rate;
    $("rate-number").value = rate;
  }
  $("rate").addEventListener("input", () => syncRate($("rate").value));
  $("rate-number").addEventListener("change", () => syncRate($("rate-number").value));
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
