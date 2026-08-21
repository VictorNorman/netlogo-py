"""FastAPI server exposing a small registry of models (Fire, Flocking,
GasLab, Ants) over an HTTP API, and serving the NetLogo-like static
frontend. Run from the project root:

    python -m uvicorn server.main:app --reload --port 8765

Every model in MODEL_REGISTRY must implement the same interface so the
endpoints below can stay model-agnostic:
  - setup(): rebuilds the model from its current module-level globals (the
    ones named in its "sliders" spec below).
  - go(): advances one tick.
  - is_running() -> bool.
  - state() -> JSON-serializable dict -- optional. The frontend
    (static/app.js) renders whatever shape it finds: a "colors" key draws
    patches, a "turtles" key draws turtles, and a model (GasLab, Ants) can
    return both at once. Most models don't define state() at all -- see
    _state() below and engine/netlogo.py's auto_state(), which builds it
    automatically from a model's already-declared widgets.
Slider "name"s below are exactly the model's attribute names, so the setup
and command endpoints can apply them with plain setattr()/hasattr() and
never need to know which model is active.

MODEL_REGISTRY itself is built from models/registry.json plus each
model's own module -- see the loop right after _plots_from_module() below.
registry.json is the only thing that needs editing to add a new model
beyond writing models/<key>.py itself: it just lists each model's key and
display label (any order -- MODEL_REGISTRY sorts by label itself, so the
dropdown is always alphabetical regardless of where a new entry gets
appended). Everything else -- world size/wrapping, every slider/switch/
chooser/monitor/plot, and the info-tab HTML (a plain INFO = "..." string
at the top of the model's own file, easier to write than escaped HTML
embedded in a JSON string) -- comes from the module that key names.

Each model is available on one server-side engine, "server-side" -- every
model is a class-less module of free functions operating on plain
per-agent Python objects (see engine/netlogo.py's module docstring),
computed in this Python process and polled by the frontend over HTTP.

A second engine, "wasm", runs entirely in the browser (Pyodide: CPython
compiled to WebAssembly) and never hits this server for computation -- see
static/pyodide-worker.js. It reuses the same model source (models/fire.py
/ models/flocking.py / models/gas_lab.py / models/ants.py), fetched via
/api/model-source, and imports engine/netlogo.py, fetched raw as text from
the /py/engine static mount below.

(An OOP engine -- one Python object per turtle/patch -- and a separate
NumPy-vectorized engine both used to exist alongside each other, each
model implemented once per engine as a class; both were removed once every
model had been ported onto the single class-less engine/netlogo.py.)

Every model in MODEL_REGISTRY is a plain module (see models/fire.py /
engine/netlogo.py) -- top-level setup()/go()/state()/is_running() and
module-level globals instead of a class's __init__/instance attributes.
Each registry entry has a "module" key; _build_model() calls that module's
own setup() explicitly (there's no __init__ to do it implicitly) and hands
back the *module itself* as "model". Every endpoint below (setattr/
hasattr/model.go() etc.) works unchanged, because Python modules support
attribute access exactly like objects do.
"""

import importlib
import json
import pathlib
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engine.netlogo as netlogo

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


def _world_snapshot():
    """(min_pxcor, max_pxcor, min_pycor, max_pycor, wrap) -- whatever a
    model's own top-level resize_world()/set_wrap() calls (see e.g.
    models/fire.py) just set, captured immediately after importing it.
    Every model module is imported exactly once, so those calls only ever
    run once each -- the *last* one imported below would otherwise "win"
    and silently stick for every other model too, since resize_world()/
    set_wrap() just mutate shared globals in engine/netlogo.py. Each
    snapshot gets stored on its model's MODEL_REGISTRY entry and
    re-applied by _build_model() on every selection, so the active
    model's own world size/wrapping is always what's actually in effect,
    regardless of import order."""
    return (netlogo.min_pxcor(), netlogo.max_pxcor(), netlogo.min_pycor(), netlogo.max_pycor(), netlogo.get_wrap())


# models/registry.json lists every model's key (== its models/<key>.py
# filename, minus the extension) and display label -- see MODEL_REGISTRY
# below for where the rest of each entry comes from (and where dropdown
# order is actually decided; this file's own order doesn't matter).
# Imported one at a time, in file order, so _world_snapshot() right after
# each import still captures that model's own world config correctly
# (see its docstring -- correctness doesn't actually depend on this order,
# but a stray typo'd key fails loudly here at startup instead of silently
# later).
with open(BASE_DIR / "models" / "registry.json") as _f:
    _REGISTRY_SPEC = json.load(_f)

_MODULES = {}
_WORLDS = {}
for _entry in _REGISTRY_SPEC:
    _key = _entry["key"]
    _MODULES[_key] = importlib.import_module(f"models.{_key}")
    _WORLDS[_key] = _world_snapshot()

app = FastAPI(title="NetLogo.py")


@app.middleware("http")
async def no_store(request, call_next):
    # This is a local single-user dev tool where the whole point is that
    # editing a .py file (or restarting the server) is immediately visible
    # -- most pointedly for /py/engine/*.py, which the WASM engine's Worker
    # fetches exactly once per browser-tab lifetime (see
    # static/pyodide-worker.js) with no other way to notice new server-side
    # code. Browsers differ on whether a page reload forces revalidation of
    # a Worker's own fetch()es (observed: Chrome does, Firefox doesn't), so
    # don't rely on cache heuristics or reload semantics at all here.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

ENGINES = {
    "server-side": {"label": "Server-side"},
}


def _sliders_from_module(module):
    """Reads slider specs off a models/*.py module's __widgets__ (built by
    engine/netlogo.py's slider() as each `x = slider("x", ...)` line runs
    at import time), instead of hand-maintaining a duplicate list here."""
    return [
        {key: value for key, value in widget.items() if key != "type"}
        for widget in getattr(module, "__widgets__", [])
        if widget["type"] == "slider"
    ]


def _monitors_from_module(module):
    """Same idea as _sliders_from_module(), for monitor() declarations.
    "ticks" isn't a real <monitor> widget in a .nlogox file -- it's the
    view widget's own tick-counter option -- so it's prepended here rather
    than something every model has to declare for itself."""
    declared = [
        {"key": widget["key"], "label": widget["label"]}
        for widget in getattr(module, "__widgets__", [])
        if widget["type"] == "monitor"
    ]
    return [{"key": "tick", "label": "ticks"}, *declared]


def _switches_from_module(module):
    """Same idea as _sliders_from_module(), for switch() declarations."""
    return [
        {key: value for key, value in widget.items() if key != "type"}
        for widget in getattr(module, "__widgets__", [])
        if widget["type"] == "switch"
    ]


def _choosers_from_module(module):
    """Same idea as _sliders_from_module(), for chooser() declarations."""
    return [
        {key: value for key, value in widget.items() if key != "type"}
        for widget in getattr(module, "__widgets__", [])
        if widget["type"] == "chooser"
    ]


def _plots_from_module(module):
    """Same idea as _sliders_from_module(), for plot_widget() declarations
    -- a model can declare more than one (see models/dimerizing_gas.py's
    speed histogram alongside its population plot), so this returns every
    one, in declaration order. The live per-pen data isn't here -- that's
    state()'s "plot_data" key, refreshed every tick like any other
    monitor value, shared across all of a model's plots by pen name."""
    return [
        {key: value for key, value in widget.items() if key != "type"}
        for widget in getattr(module, "__widgets__", [])
        if widget["type"] == "plot"
    ]


MODEL_REGISTRY = {
    entry["key"]: {
        "label": entry["label"],
        "world": _WORLDS[entry["key"]],
        # Sliders/switches/choosers/monitors/plots all come straight from
        # the module itself (e.g. models/fire.py's
        # `density = slider("density", ...)`), not hand-copied here -- see
        # engine/netlogo.py's slider()/monitor()/etc. and
        # _sliders_from_module()/_monitors_from_module()/etc. above.
        "sliders": _sliders_from_module(_MODULES[entry["key"]]),
        "switches": _switches_from_module(_MODULES[entry["key"]]),
        "choosers": _choosers_from_module(_MODULES[entry["key"]]),
        "monitors": _monitors_from_module(_MODULES[entry["key"]]),
        "plots": _plots_from_module(_MODULES[entry["key"]]),
        # Each model's own module-level INFO string (see e.g. the top of
        # models/fire.py) -- a plain Python string is much more pleasant to
        # hand-write multi-paragraph HTML in than an escaped JSON string
        # would be, so registry.json only carries the key/label, not this.
        "info": getattr(_MODULES[entry["key"]], "INFO", f"<h2>{entry['label']}</h2>"),
        "engines": {
            "server-side": {
                "module": _MODULES[entry["key"]],
                "source_file": f"models/{entry['key']}.py",
            },
        },
    }
    # Alphabetical by label (not registry.json's own file order) -- so the
    # dropdown always reads sorted regardless of where a new model's entry
    # gets appended to that file.
    for entry in sorted(_REGISTRY_SPEC, key=lambda e: e["label"].lower())
}

active_model_key = "flocking"
active_engine_key = "server-side"


def _build_model():
    # No class, so no __init__ to call setup() implicitly -- do it here. The
    # module itself *is* the model; it's a singleton (Python only ever
    # loads it once), and setup() is what resets it in place, the same way
    # NetLogo's own setup button resets the one shared world rather than
    # constructing a new one.
    entry = MODEL_REGISTRY[active_model_key]
    # World size/wrapping are set once, at each model's own module-level
    # resize_world()/set_wrap() call (import time) -- not something its
    # own setup() re-asserts (see _world_snapshot() above), so re-apply
    # this model's own values now, every time it's (re)selected, rather
    # than leaving whatever the *previously* active model (or, right
    # after server startup, the last model imported) left behind.
    min_x, max_x, min_y, max_y, wrap = entry["world"]
    netlogo.resize_world(min_x, max_x, min_y, max_y)
    netlogo.set_wrap(wrap)
    module = entry["engines"][active_engine_key]["module"]
    module.setup()
    return module


def _state(module):
    # Most models don't define their own state() at all -- see
    # engine/netlogo.py's auto_state() (and the note above it) for why.
    if hasattr(module, "state"):
        return module.state()
    return netlogo.auto_state(module=module)


model = _build_model()


class SelectModelRequest(BaseModel):
    model: str


class SelectEngineRequest(BaseModel):
    engine: str


class CommandRequest(BaseModel):
    text: str


class MouseRequest(BaseModel):
    xcor: float
    ycor: float
    down: bool
    inside: bool = True


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/models")
def list_models():
    return {
        "active": active_model_key,
        "active_engine": active_engine_key,
        "engines": [{"key": key, "label": entry["label"]} for key, entry in ENGINES.items()],
        "models": [
            {
                "key": key,
                "label": entry["label"],
                "sliders": entry["sliders"],
                "switches": entry["switches"],
                "choosers": entry["choosers"],
                "monitors": entry["monitors"],
                "plots": entry["plots"],
                "info": entry["info"],
            }
            for key, entry in MODEL_REGISTRY.items()
        ],
    }


@app.post("/api/select-model")
def select_model(req: SelectModelRequest):
    global active_model_key, model
    if req.model not in MODEL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown model: {req.model}")
    active_model_key = req.model
    model = _build_model()
    return {**_state(model), "running": model.is_running()}


@app.post("/api/select-engine")
def select_engine(req: SelectEngineRequest):
    global active_engine_key, model
    if req.engine not in ENGINES:
        raise HTTPException(status_code=404, detail=f"unknown engine: {req.engine}")
    active_engine_key = req.engine
    model = _build_model()
    return {**_state(model), "running": model.is_running()}


@app.get("/api/model-source")
def model_source(model: Optional[str] = None, engine: Optional[str] = None):
    model_key = model if model in MODEL_REGISTRY else active_model_key
    engine_key = engine if engine in ENGINES else active_engine_key
    source_file = MODEL_REGISTRY[model_key]["engines"][engine_key]["source_file"]
    return {"source": (BASE_DIR / source_file).read_text()}


@app.get("/api/state")
def get_state():
    return {**_state(model), "running": model.is_running()}


@app.post("/api/setup")
def setup(params: Dict[str, Any]):
    for key, value in params.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.setup()
    return {**_state(model), "running": model.is_running()}


@app.post("/api/step")
def step():
    model.go()
    return {**_state(model), "running": model.is_running()}


@app.post("/api/mouse")
def mouse(req: MouseRequest):
    # Sets the shared mouse state (netlogo.mouse_xcor()/mouse_down()/etc.
    # then read it) and, if the active model defines a draw_cells()
    # (NetLogo's own name for this in Life -- the first model to need
    # mouse interaction), calls it once, mirroring one frame of the real
    # model's own draw-cells forever-button loop. A model with no
    # draw_cells() just gets its mouse state updated with no other effect.
    netlogo.set_mouse_state(req.xcor, req.ycor, req.down, req.inside)
    if hasattr(model, "draw_cells"):
        model.draw_cells()
    return {**_state(model), "running": model.is_running()}


@app.post("/api/command")
def command(req: CommandRequest):
    text = req.text.strip()
    lower = text.lower()
    if lower == "setup":
        model.setup()
        output = "setup done"
    elif lower == "go":
        model.go()
        output = f"tick {_state(model)['tick']}"
    elif lower.startswith("set "):
        parts = lower.split()
        if len(parts) != 3:
            output = "expected: set <param> <value>"
        else:
            name = parts[1].replace("-", "_")
            try:
                value = float(parts[2])
                if hasattr(model, name):
                    setattr(model, name, value)
                    output = f"{name} set to {value}"
                else:
                    output = f"unknown param: {parts[1]}"
            except ValueError:
                output = "expected a numeric value"
    else:
        output = f"unknown command: {text}"
    return {"output": output, "state": {**_state(model), "running": model.is_running()}}


# Raw source of the engine package, fetched as plain text by the in-browser
# WASM engine (static/pyodide-worker.js) to bootstrap its own Pyodide
# filesystem before it can `import engine...` inside the interpreter. This
# is a local single-user dev tool, so serving its own source freely here is
# the same trust boundary as /api/model-source above.
app.mount("/py/engine", StaticFiles(directory=BASE_DIR / "engine"), name="engine-source")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
