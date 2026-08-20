const canvas = document.getElementById("world-canvas");
const ctx = canvas.getContext("2d");

const engineSelect = document.getElementById("engine-select");
const modelSelect = document.getElementById("model-select");
const slidersContainer = document.getElementById("sliders-container");
const monitorsContainer = document.getElementById("monitors-container");
const plotsContainer = document.getElementById("plots-container");
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
  life: null,
  sierpinski: null,
  preferential_attachment: null,
  rock_paper_scissors: null,
  random_basic: null,
  diffusion_on_directed_network: null,
  dimerizing_gas: null,
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
let plotStates = []; // one {spec, canvas, ctx, legendEl} per plot_widget() the active model declared
let lastState = null; // most recent drawState() input, so mouse handlers can invert worldToCanvas()

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
    // slider() lets a model declare units= (e.g. "%", "K", "amu") -- shown
    // here as "label (units)", the same convention real NetLogo itself
    // uses for its own unit-bearing sliders.
    label.textContent = slider.units ? `${slider.label} (${slider.units})` : slider.label;

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

  plotsContainer.innerHTML = "";
  plotStates = (spec.plots || []).map((plotSpec) => {
    const widget = document.createElement("div");
    widget.className = "widget plot-widget";

    const title = document.createElement("div");
    title.className = "widget-label";
    title.textContent = plotSpec.title;

    const canvas = document.createElement("canvas");
    canvas.width = 250;
    canvas.height = 160;
    const ctx = canvas.getContext("2d");

    const legend = document.createElement("div");
    legend.className = "plot-legend";
    plotSpec.pens.forEach((pen) => {
      const item = document.createElement("span");
      item.className = "plot-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "plot-legend-swatch";
      swatch.style.background = pen.color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(pen.name));
      legend.appendChild(item);
    });

    widget.appendChild(title);
    widget.appendChild(canvas);
    widget.appendChild(legend);
    plotsContainer.appendChild(widget);

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    return {
      spec: plotSpec,
      canvas,
      ctx,
    };
  });

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

// A "bar" pen's own x-values are bin left edges (histogram(), see
// engine/netlogo.py) all the same width apart -- inferred from the first
// two points, since the data itself doesn't carry the width along.
function penBarWidth(points) {
  return points.length > 1 ? points[1][0] - points[0][0] : 1;
}

// Keeps tick-number text short without hiding real precision: whole
// numbers print bare, anything else gets 2 decimal places.
function formatTick(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function drawPlot(plotData, plotSpec, canvas, ctx) {
  if (!plotSpec) {
    return;
  }
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const xs = [];
  const ys = [];
  plotSpec.pens.forEach((pen) => {
    const points = plotData[pen.name] || [];
    const barWidth = pen.mode === "bar" ? penBarWidth(points) : 0;
    points.forEach(([x, y]) => {
      xs.push(x);
      if (barWidth) {
        xs.push(x + barWidth); // so the last bar's right edge isn't clipped
      }
      ys.push(y);
    });
  });
  if (xs.length === 0) {
    return;
  }

  const [xMin, xMax] = minMax([...xs, 0]);
  const [yMin, yMax] = minMax([...ys, 0]);

  // Margins carve out room around the plot area for axis names (x_label/
  // y_label, from plot_widget()) and the min/max value at each axis's
  // ends -- plotted data only ever goes inside [marginLeft, marginLeft+w]
  // x [marginTop, marginTop+h].
  const marginLeft = 28;
  const marginRight = 6;
  const marginTop = 5;
  const marginBottom = 26;
  const w = canvas.width - marginLeft - marginRight;
  const h = canvas.height - marginTop - marginBottom;
  const toPx = (x, y) => [
    marginLeft + ((x - xMin) / (xMax - xMin || 1)) * w,
    marginTop + h - ((y - yMin) / (yMax - yMin || 1)) * h,
  ];

  plotSpec.pens.forEach((pen) => {
    const points = plotData[pen.name];
    if (!points || points.length === 0) {
      return;
    }

    if (pen.mode === "bar") {
      const barWidth = penBarWidth(points);
      ctx.fillStyle = pen.color;
      points.forEach(([x, y]) => {
        const [px1, py1] = toPx(x, y);
        const [px2, py2] = toPx(x + barWidth, 0);
        ctx.fillRect(Math.min(px1, px2), Math.min(py1, py2), Math.abs(px2 - px1), Math.abs(py2 - py1));
      });
      return;
    }

    ctx.strokeStyle = pen.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    points.forEach(([x, y], i) => {
      const [px, py] = toPx(x, y);
      if (i === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    });
    ctx.stroke();
  });

  // Axis lines.
  ctx.strokeStyle = "#999999";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(marginLeft, marginTop);
  ctx.lineTo(marginLeft, marginTop + h);
  ctx.lineTo(marginLeft + w, marginTop + h);
  ctx.stroke();

  // Min/max value at each axis's ends -- a real (if minimal) numeric
  // scale, not just a label naming the axis.
  ctx.fillStyle = "#555555";
  ctx.font = "9px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "top";
  ctx.fillText(formatTick(yMax), marginLeft - 2, marginTop);
  ctx.textBaseline = "bottom";
  ctx.fillText(formatTick(yMin), marginLeft - 2, marginTop + h);
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText(formatTick(xMin), marginLeft, marginTop + h + 2);
  ctx.textAlign = "right";
  ctx.fillText(formatTick(xMax), marginLeft + w, marginTop + h + 2);

  // Axis names (plot_widget()'s x_label/y_label), each model's own choice
  // of units included right in the string (e.g. "time (ticks)").
  ctx.fillStyle = "#333333";
  ctx.font = "10px sans-serif";
  if (plotSpec.x_label) {
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(plotSpec.x_label, marginLeft + w / 2, canvas.height);
  }
  if (plotSpec.y_label) {
    ctx.save();
    ctx.translate(9, marginTop + h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(plotSpec.y_label, 0, 0);
    ctx.restore();
  }
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

// The exact algebraic inverse of worldToCanvas(), for turning a mouse
// event's canvas-pixel position into NetLogo mouse-xcor/mouse-ycor world
// coordinates. Needs the last-drawn state for its width/height (the same
// world size every current frame was drawn at), so it returns null before
// anything has been drawn yet.
function canvasPixelToWorld(px, py) {
  if (!lastState) {
    return null;
  }
  const w = lastState.width;
  const h = lastState.height;
  const scaleX = canvas.width / w;
  const xcor = px / scaleX - w / 2;
  const ycor = (1 - py / canvas.height) * h - h / 2;
  return [xcor, ycor];
}

// Shared by drawLinks()/drawDrawing(): both are just a list of
// [x1, y1, x2, y2, [r,g,b]] line segments in world coordinates -- a link
// between two turtles, or a pen-drawn trail segment, drawn identically.
// A 6th `directed` element (only links_grid() ever sends one -- drawing
// segments don't) draws a small arrowhead partway along the line, from
// (x1,y1) toward (x2,y2), same direction as NetLogo's own directed-link
// indicator.
function drawSegments(state, segments) {
  segments.forEach(([x1, y1, x2, y2, color, directed]) => {
    const [px1, py1] = worldToCanvas(state, x1, y1);
    const [px2, py2] = worldToCanvas(state, x2, y2);
    ctx.strokeStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px1, py1);
    ctx.lineTo(px2, py2);
    ctx.stroke();

    if (directed) {
      const dx = px2 - px1;
      const dy = py2 - py1;
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;
      const tipX = px1 + ux * len * 0.65;
      const tipY = py1 + uy * len * 0.65;
      const backX = tipX - ux * 5;
      const backY = tipY - uy * 5;
      const perpX = -uy * 2.5;
      const perpY = ux * 2.5;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.moveTo(tipX, tipY);
      ctx.lineTo(backX + perpX, backY + perpY);
      ctx.lineTo(backX - perpX, backY - perpY);
      ctx.closePath();
      ctx.fill();
    }
  });
}

function drawLinks(state) {
  drawSegments(state, state.links);
}

function drawDrawing(state) {
  drawSegments(state, state.drawing);
}

function drawTurtles(state) {
  state.turtles.forEach((t) => {
    const [x, y, heading, extra, label, size, shape] = t;
    const [px, py] = worldToCanvas(state, x, y);
    const rad = (heading * Math.PI) / 180;

    // `size` (NetLogo's `set size ...`) scales the marker -- 1 (every
    // turtle's default, and every row from before turtles_grid() started
    // sending a 6th element) draws at the same fixed size as always.
    const sizeScale = size === undefined || size === null ? 1 : size;
    const width = 3.5 * sizeScale;

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

    if (shape === "circle") {
      // A plain filled circle -- no heading indicator, since round
      // particles (e.g. models/dimerizing_gas.py) have no visible
      // orientation to show.
      const radius = 4 * sizeScale;
      ctx.beginPath();
      ctx.arc(px, py, radius, 0, 2 * Math.PI);
      ctx.fill();
    } else {
      // NetLogo heading: 0 = up (screen -y), increases clockwise.
      const dirX = Math.sin(rad);
      const dirY = -Math.cos(rad);
      const perpX = -dirY;
      const perpY = dirX;
      const length = 7 * sizeScale;

      const tipX = px + dirX * length;
      const tipY = py + dirY * length;
      const baseLX = px - dirX * length * 0.6 + perpX * width;
      const baseLY = py - dirY * length * 0.6 + perpY * width;
      const baseRX = px - dirX * length * 0.6 - perpX * width;
      const baseRY = py - dirY * length * 0.6 - perpY * width;

      ctx.beginPath();
      ctx.moveTo(tipX, tipY);
      ctx.lineTo(baseLX, baseLY);
      ctx.lineTo(baseRX, baseRY);
      ctx.closePath();
      ctx.fill();
    }

    // NetLogo's `set label ...` -- floating text just above/right of the
    // turtle, same corner real NetLogo uses.
    if (label !== null && label !== undefined) {
      ctx.fillStyle = "#ffffff";
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText(String(label), px + width + 1, py - width);
    }
  });
}

function drawState(state) {
  if (!state) {
    return;
  }
  lastState = state;

  // Shape-driven, not a fixed per-model mode: only Fire omits `turtles`
  // (it has real turtles but represents them purely by patch color); every
  // other model has both `colors` and `turtles` (auto_state()'s defaults),
  // relying on drawPatches() painting every pixel first so drawLinks()/
  // drawDrawing()/drawTurtles() don't need to separately clear the canvas.
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
  if (state.drawing) {
    drawDrawing(state);
  }
  if (state.turtles) {
    drawTurtles(state);
  }
  if (state.plot_data) {
    plotStates.forEach((ps) => drawPlot(state.plot_data, ps.spec, ps.canvas, ps.ctx));
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

// Mouse interaction (NetLogo's mouse-xcor/mouse-ycor/mouse-down?) -- wired
// up unconditionally, not just for models that use it: a model that
// doesn't define draw_cells() (or an equivalent) just gets its mouse
// state updated with no visible effect, same as an unused slider. See
// engine/netlogo.py's set_mouse_state()/mouse_xcor()/etc. and
// server/main.py's /api/mouse.
async function sendMouseState(xcor, ycor, down) {
  let state;
  if (currentEngine === "wasm") {
    try {
      state = await wasmCall("mouse", { xcor, ycor, down, inside: true });
    } catch (err) {
      appendOutput(`Python error:\n${err.message}`);
      return;
    }
  } else {
    state = await callApi("/api/mouse", { xcor, ycor, down, inside: true });
  }
  drawState(state);
}

// Dedupes on (rounded cell, down-state) so dragging within the same cell's
// several-pixel-wide area doesn't fire a network round-trip per pixel.
let lastMouseCellKey = null;

function maybeSendMouse(px, py, down) {
  const world = canvasPixelToWorld(px, py);
  if (!world) {
    return;
  }
  const [xcor, ycor] = world;
  const cellKey = `${Math.round(xcor)},${Math.round(ycor)},${down}`;
  if (cellKey === lastMouseCellKey) {
    return;
  }
  lastMouseCellKey = cellKey;
  sendMouseState(xcor, ycor, down);
}

canvas.addEventListener("mousedown", (event) => {
  event.preventDefault();
  maybeSendMouse(event.offsetX, event.offsetY, true);
});

canvas.addEventListener("mousemove", (event) => {
  if ((event.buttons & 1) === 0) {
    return; // only while the primary button is actually held (dragging)
  }
  maybeSendMouse(event.offsetX, event.offsetY, true);
});

canvas.addEventListener("mouseup", () => {
  lastMouseCellKey = null;
  sendMouseState(0, 0, false);
});

canvas.addEventListener("mouseleave", () => {
  lastMouseCellKey = null;
  sendMouseState(0, 0, false);
});

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
