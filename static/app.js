const canvas = document.getElementById("world-canvas");
const ctx = canvas.getContext("2d");

const engineSelect = document.getElementById("engine-select");
const modelSelect = document.getElementById("model-select");
const slidersContainer = document.getElementById("sliders-container");
const monitorsContainer = document.getElementById("monitors-container");
const plotContainer = document.getElementById("plot-container");
const plotCanvas = document.getElementById("plot-canvas");
const plotCtx = plotCanvas.getContext("2d");
const plotTitle = document.getElementById("plot-title");
const plotLegend = document.getElementById("plot-legend");
const speedSlider = document.getElementById("speed-slider");
const speedLabel = document.getElementById("speed-label");
const btnSetup = document.getElementById("btn-setup");
const btnGo = document.getElementById("btn-go");
const btnRunScript = document.getElementById("btn-run-script");
const commandInput = document.getElementById("command-input");
const commandOutput = document.getElementById("command-output");
const infoText = document.getElementById("info-text");
const codeView = document.getElementById("code-view");
const codeEditorWrap = document.getElementById("code-editor-wrap");
const codeEditor = document.getElementById("code-editor");

// Each model's editable-in-the-browser class name, for the WASM engine's
// `run-script` message (see static/pyodide-worker.js) -- matches the class
// defined in models/fire.py / models/flocking.py.
// null means "no class" -- the worker's _run_script() falls back to
// treating the executed script as a plain module (setup()/go()/state() as
// free functions), which is what models/fire.py actually is now. See
// engine/netlogo.py's module docstring for why.
const WASM_CLASS_NAMES = {
  fire: null,
  flocking: null,
  gaslab: null,
  ants: null,
  wolf_sheep: null,
  virus_on_network: null,
};

// Not a plain setInterval: doStep() is an async network round-trip, and a
// fixed-cadence interval fires again regardless of whether the previous
// call has actually finished -- for a model whose per-tick server cost can
// exceed the interval (e.g. Flocking's O(N^2)-ish flockmate search), that
// piles up overlapping in-flight requests, and clicking "go" to stop only
// stops *scheduling new* ones -- the backlog already queued keeps
// resolving and redrawing regardless, so the model visibly keeps running
// for a while (or indefinitely) after you click stop. goRunning is checked
// again after every doStep() resolves, before the next one is scheduled,
// so stopping always takes effect within at most one in-flight step.
let goRunning = false;
let goTimeoutId = null;
let specsByKey = {};
let currentEngine = "vectorized";
let currentPlotSpec = null; // the active model's plot_widget() declaration, or null

function currentParams() {
  const params = {};
  document.querySelectorAll(".param-slider").forEach((el) => {
    params[el.dataset.param] = Number(el.value);
  });
  document.querySelectorAll(".param-switch").forEach((el) => {
    params[el.dataset.param] = el.checked;
  });
  document.querySelectorAll(".param-chooser").forEach((el) => {
    params[el.dataset.param] = el.value;
  });
  return params;
}

function renderControls(spec) {
  slidersContainer.innerHTML = "";
  spec.sliders.forEach((slider) => {
    const widget = document.createElement("div");
    widget.className = "widget slider-widget";

    const label = document.createElement("div");
    label.className = "widget-label";
    label.textContent = slider.label;

    const row = document.createElement("div");
    row.className = "slider-row";

    const input = document.createElement("input");
    input.type = "range";
    input.className = "param-slider";
    input.dataset.param = slider.name;
    input.min = slider.min;
    input.max = slider.max;
    input.step = slider.step;
    input.value = slider.default;

    const valueLabel = document.createElement("span");
    valueLabel.className = "slider-value";
    valueLabel.textContent = slider.default;

    input.addEventListener("input", () => {
      valueLabel.textContent = input.value;
    });

    row.appendChild(input);
    row.appendChild(valueLabel);
    widget.appendChild(label);
    widget.appendChild(row);
    slidersContainer.appendChild(widget);
  });

  (spec.switches || []).forEach((sw) => {
    const widget = document.createElement("div");
    widget.className = "widget switch-widget";

    const row = document.createElement("label");
    row.className = "switch-row";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "param-switch";
    input.dataset.param = sw.name;
    input.checked = sw.default;

    const label = document.createElement("span");
    label.className = "widget-label";
    label.textContent = sw.label;

    row.appendChild(input);
    row.appendChild(label);
    widget.appendChild(row);
    slidersContainer.appendChild(widget);
  });

  (spec.choosers || []).forEach((chooser) => {
    const widget = document.createElement("div");
    widget.className = "widget chooser-widget";

    const label = document.createElement("div");
    label.className = "widget-label";
    label.textContent = chooser.label;

    const select = document.createElement("select");
    select.className = "param-chooser";
    select.dataset.param = chooser.name;
    chooser.options.forEach((option) => {
      const opt = document.createElement("option");
      opt.value = option;
      opt.textContent = option;
      select.appendChild(opt);
    });
    select.value = chooser.default;

    widget.appendChild(label);
    widget.appendChild(select);
    slidersContainer.appendChild(widget);
  });

  monitorsContainer.innerHTML = "";
  spec.monitors.forEach((monitor) => {
    const widget = document.createElement("div");
    widget.className = "widget monitor-widget";

    const label = document.createElement("div");
    label.className = "widget-label";
    label.textContent = monitor.label;

    const value = document.createElement("div");
    value.className = "monitor-value";
    value.dataset.monitor = monitor.key;
    value.textContent = "0";

    widget.appendChild(label);
    widget.appendChild(value);
    monitorsContainer.appendChild(widget);
  });

  currentPlotSpec = spec.plot || null;
  if (currentPlotSpec) {
    plotContainer.classList.remove("hidden");
    plotTitle.textContent = currentPlotSpec.title;
    plotLegend.innerHTML = "";
    currentPlotSpec.pens.forEach((pen) => {
      const item = document.createElement("span");
      item.className = "plot-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "plot-legend-swatch";
      swatch.style.background = pen.color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(pen.name));
      plotLegend.appendChild(item);
    });
    plotCtx.fillStyle = "#ffffff";
    plotCtx.fillRect(0, 0, plotCanvas.width, plotCanvas.height);
  } else {
    plotContainer.classList.add("hidden");
  }

  infoText.innerHTML = spec.info;
}

function minMax(values) {
  // Not Math.min(...values) -- that spreads the whole array onto the call
  // stack, which can overflow for a plot pen with many thousands of
  // points (a model like Wolf Sheep can run indefinitely).
  let min = Infinity;
  let max = -Infinity;
  values.forEach((v) => {
    if (v < min) {
      min = v;
    }
    if (v > max) {
      max = v;
    }
  });
  return [min, max];
}

function drawPlot(plotData, plotSpec) {
  if (!plotSpec) {
    return;
  }
  plotCtx.fillStyle = "#ffffff";
  plotCtx.fillRect(0, 0, plotCanvas.width, plotCanvas.height);

  const xs = [];
  const ys = [];
  plotSpec.pens.forEach((pen) => {
    (plotData[pen.name] || []).forEach(([x, y]) => {
      xs.push(x);
      ys.push(y);
    });
  });
  if (xs.length === 0) {
    return;
  }

  const [xMin, xMax] = minMax([...xs, 0]);
  const [yMin, yMax] = minMax([...ys, 0]);
  const pad = 4;
  const w = plotCanvas.width - pad * 2;
  const h = plotCanvas.height - pad * 2;
  const toPx = (x, y) => [
    pad + ((x - xMin) / (xMax - xMin || 1)) * w,
    pad + h - ((y - yMin) / (yMax - yMin || 1)) * h,
  ];

  plotSpec.pens.forEach((pen) => {
    const points = plotData[pen.name];
    if (!points || points.length === 0) {
      return;
    }
    plotCtx.strokeStyle = pen.color;
    plotCtx.lineWidth = 1.5;
    plotCtx.beginPath();
    points.forEach(([x, y], i) => {
      const [px, py] = toPx(x, y);
      if (i === 0) {
        plotCtx.moveTo(px, py);
      } else {
        plotCtx.lineTo(px, py);
      }
    });
    plotCtx.stroke();
  });
}

function drawPatches(state) {
  const cols = state.width;
  const rows = state.height;
  const cellW = canvas.width / cols;
  const cellH = canvas.height / rows;

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const rgb = state.colors[row][col];
      ctx.fillStyle = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
      ctx.fillRect(col * cellW, row * cellH, Math.ceil(cellW), Math.ceil(cellH));
    }
  }
}

// Shared by drawLinks()/drawTurtles(): world coordinates -> canvas pixels.
// Both need this identically, so a link's endpoints line up exactly with
// where its two turtles are actually drawn.
function worldToCanvas(state, x, y) {
  const w = state.width;
  const h = state.height;
  const scaleX = canvas.width / w;
  return [(x + w / 2) * scaleX, (1 - (y + h / 2) / h) * canvas.height];
}

function drawLinks(state) {
  state.links.forEach(([x1, y1, x2, y2, color]) => {
    const [px1, py1] = worldToCanvas(state, x1, y1);
    const [px2, py2] = worldToCanvas(state, x2, y2);
    ctx.strokeStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px1, py1);
    ctx.lineTo(px2, py2);
    ctx.stroke();
  });
}

function drawTurtles(state) {
  state.turtles.forEach((t) => {
    const [x, y, heading, extra] = t;
    const [px, py] = worldToCanvas(state, x, y);
    const rad = (heading * Math.PI) / 180;

    // NetLogo heading: 0 = up (screen -y), increases clockwise.
    const dirX = Math.sin(rad);
    const dirY = -Math.cos(rad);
    const perpX = -dirY;
    const perpY = dirX;
    const length = 7;
    const width = 3.5;

    const tipX = px + dirX * length;
    const tipY = py + dirY * length;
    const baseLX = px - dirX * length * 0.6 + perpX * width;
    const baseLY = py - dirY * length * 0.6 + perpY * width;
    const baseRX = px - dirX * length * 0.6 - perpX * width;
    const baseRY = py - dirY * length * 0.6 - perpY * width;

    // The 4th element's shape says what it means: missing (Flocking) draws
    // a fixed green; a boolean (Ants) flags a turtle carrying food; a
    // [r,g,b] array (GasLab) is the turtle's own real color, computed by
    // the model itself (state()'s color_to_rgb(t.color)).
    if (extra === undefined) {
      ctx.fillStyle = "#39d353";
    } else if (Array.isArray(extra)) {
      ctx.fillStyle = `rgb(${extra[0]}, ${extra[1]}, ${extra[2]})`;
    } else {
      ctx.fillStyle = extra ? "#ff5555" : "#e8c39e";
    }

    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(baseLX, baseLY);
    ctx.lineTo(baseRX, baseRY);
    ctx.closePath();
    ctx.fill();
  });
}

function drawState(state) {
  if (!state) {
    return;
  }

  // Shape-driven, not a fixed per-model mode: only Fire omits `turtles`
  // (it has real turtles but represents them purely by patch color); every
  // other model has both `colors` and `turtles` (auto_state()'s defaults),
  // relying on drawPatches() painting every pixel first so drawLinks()/
  // drawTurtles() don't need to separately clear the canvas.
  if (!state.colors) {
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  if (state.colors) {
    drawPatches(state);
  }
  if (state.links) {
    drawLinks(state);
  }
  if (state.turtles) {
    drawTurtles(state);
  }
  if (state.plot_data) {
    drawPlot(state.plot_data, currentPlotSpec);
  }

  document.querySelectorAll("[data-monitor]").forEach((el) => {
    const value = state[el.dataset.monitor];
    if (typeof value === "number" && !Number.isInteger(value)) {
      el.textContent = value.toFixed(2);
    } else {
      el.textContent = value;
    }
  });
}

function setRunningUi(running) {
  if (running) {
    btnGo.classList.add("running");
  } else {
    btnGo.classList.remove("running");
  }
}

function stopGoLoop() {
  goRunning = false;
  if (goTimeoutId !== null) {
    clearTimeout(goTimeoutId);
    goTimeoutId = null;
  }
  setRunningUi(false);
}

async function callApi(path, body) {
  const options = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  };
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  return response.json();
}

function appendOutput(line) {
  commandOutput.textContent += line + "\n";
  commandOutput.scrollTop = commandOutput.scrollHeight;
}

// --- WASM (Pyodide, in a Web Worker) transport ------------------------
//
// Mirrors callApi() above, but talks to static/pyodide-worker.js over
// postMessage instead of fetch(). The worker lazily loads Pyodide on the
// first non-"init" call (see ensurePyodide() in the worker), so callers
// here don't need to special-case "is it loaded yet".

let wasmWorker = null;
let wasmInitPromise = null;
let wasmMsgId = 0;
const wasmPending = new Map();

function getWasmWorker() {
  if (!wasmWorker) {
    wasmWorker = new Worker("/static/pyodide-worker.js");
    wasmWorker.onmessage = (event) => {
      const { id, ok, data, error } = event.data;
      const pending = wasmPending.get(id);
      if (!pending) {
        return;
      }
      wasmPending.delete(id);
      if (ok) {
        pending.resolve(data);
      } else {
        pending.reject(new Error(error));
      }
    };
  }
  return wasmWorker;
}

function wasmCall(type, payload) {
  if (type !== "init" && !wasmInitPromise) {
    wasmInitPromise = wasmCall("init", {});
  }
  const worker = getWasmWorker();
  const id = ++wasmMsgId;
  const sent = new Promise((resolve, reject) => {
    wasmPending.set(id, {
      resolve,
      reject,
    });
    worker.postMessage({
      id,
      type,
      payload: payload || {},
    });
  });
  return type === "init" ? sent : wasmInitPromise.then(() => sent);
}

async function runWasmScript() {
  const modelKey = modelSelect.value;
  const className = WASM_CLASS_NAMES[modelKey];
  const source = codeEditor.value;
  try {
    const data = await wasmCall("run-script", {
      source,
      className,
      params: currentParams(),
    });
    drawState(data);
    appendOutput("script compiled and running.");
  } catch (err) {
    appendOutput(`Python error:\n${err.message}`);
  }
}

async function runWasmCommand(text) {
  const trimmed = text.trim();
  const lower = trimmed.toLowerCase();

  if (lower === "setup") {
    const state = await wasmCall("setup", { params: currentParams() });
    return {
      output: "setup done",
      state,
    };
  }
  if (lower === "go") {
    const state = await wasmCall("step", {});
    return {
      output: `tick ${state.tick}`,
      state,
    };
  }
  if (lower.startsWith("set ")) {
    const parts = lower.split(/\s+/);
    if (parts.length !== 3) {
      return {
        output: "expected: set <param> <value>",
        state: await wasmCall("state", {}),
      };
    }
    const name = parts[1].replace(/-/g, "_");
    const value = Number(parts[2]);
    if (Number.isNaN(value)) {
      return {
        output: "expected a numeric value",
        state: await wasmCall("state", {}),
      };
    }
    const state = await wasmCall("set-param", {
      name,
      value,
    });
    const output = state.ok ? `${name} set to ${value}` : `unknown param: ${parts[1]}`;
    return {
      output,
      state,
    };
  }
  return {
    output: `unknown command: ${trimmed}`,
    state: await wasmCall("state", {}),
  };
}

// --- Shared engine-agnostic actions ------------------------------------

async function doSetup() {
  stopGoLoop();
  if (currentEngine === "wasm") {
    try {
      drawState(await wasmCall("setup", { params: currentParams() }));
    } catch (err) {
      appendOutput(`Python error:\n${err.message}`);
    }
    return;
  }
  const state = await callApi("/api/setup", currentParams());
  drawState(state);
}

async function doStep() {
  let state;
  if (currentEngine === "wasm") {
    try {
      state = await wasmCall("step", {});
    } catch (err) {
      appendOutput(`Python error:\n${err.message}`);
      stopGoLoop();
      return false;
    }
  } else {
    state = await callApi("/api/step");
  }
  drawState(state);
  if (!state.running) {
    stopGoLoop();
  }
  return state.running;
}

// NetLogo's own toolbar "speed" slider, adapted for this app's simple
// setInterval-based go loop: -100 (slowest) .. 0 (normal speed) .. 100
// (fastest). 60ms was this app's original fixed tick interval -- that's
// still what "normal speed" means; the slider scales it up or down from
// there on a log curve (matching how the real slider feels -- small moves
// near the center barely change anything, the extremes change it a lot).
const NORMAL_SPEED_MS = 60;

function speedToIntervalMs() {
  const v = Number(speedSlider.value);
  const ms = NORMAL_SPEED_MS * Math.pow(10, -v / 100);
  return Math.max(5, Math.round(ms));
}

function updateSpeedLabel() {
  const v = Number(speedSlider.value);
  if (v === 0) {
    speedLabel.textContent = "normal speed";
  } else if (v > 0) {
    speedLabel.textContent = "faster";
  } else {
    speedLabel.textContent = "slower";
  }
}

async function goLoopStep() {
  if (!goRunning) {
    return;
  }
  goTimeoutId = null;
  const stillRunning = await doStep();
  if (!goRunning) {
    // Stopped (or self-stopped via doStep()'s own stopGoLoop() call, e.g.
    // Fire finishing) while this step was in flight -- don't schedule
    // another one.
    return;
  }
  if (!stillRunning) {
    stopGoLoop();
    return;
  }
  goTimeoutId = setTimeout(goLoopStep, speedToIntervalMs());
}

function toggleGo() {
  if (goRunning) {
    stopGoLoop();
    return;
  }
  goRunning = true;
  setRunningUi(true);
  goLoopStep();
}

speedSlider.addEventListener("input", () => {
  updateSpeedLabel();
  // Take effect immediately for a step that's currently waiting between
  // ticks; a step already in flight will just pick up the new speed when
  // it schedules its own next one, no extra handling needed.
  if (goRunning && goTimeoutId !== null) {
    clearTimeout(goTimeoutId);
    goTimeoutId = setTimeout(goLoopStep, speedToIntervalMs());
  }
});

async function runCommand(text) {
  appendOutput(`observer> ${text}`);
  if (currentEngine === "wasm") {
    try {
      const result = await runWasmCommand(text);
      appendOutput(result.output);
      drawState(result.state);
    } catch (err) {
      appendOutput(`Python error:\n${err.message}`);
    }
    return;
  }
  const result = await callApi("/api/command", { text: text });
  appendOutput(result.output);
  drawState(result.state);
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => {
        t.classList.remove("active");
      });
      tab.classList.add("active");
      const target = tab.dataset.tab;
      document.querySelectorAll(".panel").forEach((panel) => {
        panel.classList.add("hidden");
      });
      document.getElementById(`panel-${target}`).classList.remove("hidden");
    });
  });
}

function updateEngineUi() {
  const isWasm = currentEngine === "wasm";
  codeView.classList.toggle("hidden", isWasm);
  codeEditorWrap.classList.toggle("hidden", !isWasm);
}

async function loadCodeTab() {
  const modelKey = modelSelect.value;
  // The WASM engine always runs the vectorized source (it's the one
  // that's plain NumPy, ideal for Pyodide) regardless of which server
  // engine was last selected.
  const engineParam = currentEngine === "wasm" ? "vectorized" : currentEngine;
  const response = await fetch(`/api/model-source?model=${modelKey}&engine=${engineParam}`, { cache: "no-store" });
  const data = await response.json();
  if (currentEngine === "wasm") {
    codeEditor.value = data.source;
  } else {
    codeView.textContent = data.source;
  }
}

async function selectModel(key) {
  stopGoLoop();
  renderControls(specsByKey[key]);
  // Keep the server's active model in sync even while the WASM engine is
  // driving the UI, so /api/model-source's defaults stay correct if the
  // user switches back to a server engine.
  const state = await callApi("/api/select-model", { model: key });
  if (currentEngine === "wasm") {
    await loadCodeTab();
    await runWasmScript();
  } else {
    drawState(state);
    loadCodeTab();
  }
}

async function selectEngine(engine) {
  stopGoLoop();
  currentEngine = engine;
  updateEngineUi();

  if (engine === "wasm") {
    appendOutput("loading WASM engine (Pyodide + NumPy)… first load can take a few seconds.");
    try {
      await wasmCall("init", {});
    } catch (err) {
      appendOutput(`WASM engine failed to load: ${err.message}`);
      return;
    }
    appendOutput("WASM engine ready.");
    await loadCodeTab();
    await runWasmScript();
  } else {
    const state = await callApi("/api/select-engine", { engine });
    drawState(state);
    loadCodeTab();
  }
}

async function loadModels() {
  const response = await fetch("/api/models");
  const data = await response.json();

  data.models.forEach((spec) => {
    specsByKey[spec.key] = spec;
    const option = document.createElement("option");
    option.value = spec.key;
    option.textContent = spec.label;
    modelSelect.appendChild(option);
  });

  data.engines.forEach((engine) => {
    const option = document.createElement("option");
    option.value = engine.key;
    option.textContent = engine.label;
    engineSelect.appendChild(option);
  });
  const wasmOption = document.createElement("option");
  wasmOption.value = "wasm";
  wasmOption.textContent = "WASM (browser, Pyodide)";
  engineSelect.appendChild(wasmOption);

  modelSelect.value = data.active;
  engineSelect.value = data.active_engine;
  currentEngine = data.active_engine;
  renderControls(specsByKey[data.active]);
  updateEngineUi();

  const state = await callApi("/api/setup", currentParams());
  drawState(state);
  loadCodeTab();
}

engineSelect.addEventListener("change", () => {
  selectEngine(engineSelect.value);
});

modelSelect.addEventListener("change", () => {
  selectModel(modelSelect.value);
});

btnSetup.addEventListener("click", doSetup);
btnGo.addEventListener("click", toggleGo);
btnRunScript.addEventListener("click", () => {
  stopGoLoop();
  runWasmScript();
});

commandInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && commandInput.value.trim() !== "") {
    const text = commandInput.value;
    commandInput.value = "";
    runCommand(text);
  }
});

setupTabs();
loadModels();
