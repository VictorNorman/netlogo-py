# NetLogo.py

A Python runtime for [NetLogo](https://ccl.northwestern.edu/netlogo/)-style agent-based models, plus a small FastAPI server and a zero-build browser frontend to run and watch them — either on the server or **entirely inside the browser** via [Pyodide](https://pyodide.org/) (CPython compiled to WebAssembly), with the model's source live-editable and re-runnable without a page reload.

Twelve classic NetLogo Sample Models are ported so far — **Fire**, **Flocking**, **GasLab**, **Ants**, **Wolf Sheep Predation**, **Virus on a Network**, **Life**, **Sierpinski Simple**, **Preferential Attachment**, **Rock Paper Scissors**, **Random Basic**, and **Diffusion on a Directed Network** — each checked against its real `.nlogox` source line by line, not reimplemented from memory. A thirteenth model, **Dimerizing Gas**, is original to this app rather than a port — see below.

```
python -m uvicorn server.main:app --reload --port 8765
```

Then open `http://localhost:8765`, pick a model, hit **setup** then **go**.

## The twelve ported models

| Model | What it shows | Real source |
|---|---|---|
| **Fire** | A percolation threshold: below a critical tree density a fire dies out quickly; above it, it engulfs the forest. | `Sample Models/Earth Science/Fire.nlogox` |
| **Flocking** | Boids — three simple per-turtle rules (separate / align / cohere) producing emergent flocking. | `Sample Models/Biology/Flocking.nlogox` |
| **GasLab** | Molecular dynamics: elastic, mass-aware particle collisions in a walled box, with an adaptive timestep so fast particles never tunnel through a wall. Kinetic energy is conserved exactly while the speed distribution spreads out. | `Sample Models/Chemistry & Physics/GasLab/GasLab Gas in a Box.nlogox` |
| **Ants** | Stigmergy: ants lay a pheromone trail while carrying food home, and other ants follow the gradient — a decentralized shortest-path search. | `Sample Models/Biology/Ants.nlogox` |
| **Wolf Sheep Predation** | Predator-prey population dynamics (Lotka-Volterra-style oscillation) in an optional grass-scarcity variant. | `Sample Models/Biology/Wolf Sheep Predation.nlogox` |
| **Virus on a Network** | SIR epidemic spread over a social-network graph — the first model here to use links, connecting nodes drawn as circles with lines. | `Sample Models/Networks/Virus on a Network.nlogox` |
| **Life** | Conway's Game of Life — the first model here to use the mouse: click and drag on the grid to draw or erase cells by hand, running or not. | `Sample Models/Computer Science/Cellular Automata/Life.nlogox` |
| **Sierpinski Simple** | A single turtle recursively hatches three children per tick, each drawing a trail and shrinking by half — the first model here to use a pen, tracing out Sierpinski's self-similar tree. | `Sample Models/Mathematics/Fractals/Sierpinski Simple.nlogox` |
| **Preferential Attachment** | "Rich get richer" scale-free network growth — the first model here to use a real histogram-mode plot pen, showing the resulting hub-heavy degree distribution. | `Sample Models/Networks/Preferential Attachment.nlogox` |
| **Rock Paper Scissors** | Three colors compete in a cyclic-dominance ecosystem on a wrapping patch grid, producing chasing spiral patterns; event rates are drawn from a Poisson distribution. | `Sample Models/Biology/Rock Paper Scissors.nlogox` |
| **Random Basic** | A messenger turtle picks a random value each tick and carries it to the matching column of a growing histogram — the first model here to use turtle labels (floating text next to a turtle). | `Sample Models/Mathematics/Probability/ProbLab/Random Basic.nlogox` |
| **Diffusion on a Directed Network** | A quantity diffuses across a grid of nodes along directed links — the first model here to use directed links and more than one link breed; node size shows how much value it holds, link brightness shows how much just flowed through it. | `Sample Models/Networks/Diffusion on a Directed Network.nlogox` |

Every model documents its own deliberate deviations from the real source in its module docstring (an explicit boolean instead of color-encoded turtle state, a simplified color model, app-specific monitors like Flocking's `order_parameter`, etc.) — nothing is silently dropped.

### A thirteenth, original model

**Dimerizing Gas** (`models/dimerizing_gas.py`) isn't a NetLogo Sample Models port — there's no real `.nlogox` source to check it against. It's GasLab's hard-sphere box physics with one addition: the reversible reaction 2 A ⇌ B, built for a dynamic-equilibrium chemistry demo. Two colliding A particles can combine into a B (momentum-conserving, releasing their relative kinetic energy — real dimerization is exothermic); a B can dissociate back into two A's, drawing the energy for that from a thermal bath at the current `temperature`. Mass is exactly conserved always (`count_a + 2*count_b` never changes); the `Kc` monitor is a trailing 20-tick average of `B / A²`, since the raw ratio jitters too much tick to tick to show convergence on its own. It's also the first model here to render its turtles as circles (`shape`, alongside `size`, now flow all the way through `turtles_grid()` to the frontend) rather than the usual heading-indicating triangle, and the first to declare more than one `plot_widget()` (a population history and a live speed histogram, both engines and `static/app.js` generalized to a list to support this).

## Two engines, one model source

The **same** model files run two ways:

- **Server** — the FastAPI app in `server/main.py` runs the model in the Python process and the browser polls `/api/step` roughly every 60ms.
- **WASM (browser)** — `static/pyodide-worker.js` runs a full CPython interpreter in a Web Worker via Pyodide, fetches the model's source as plain text, and `exec()`s it directly. Every tick runs client-side with zero network round-trips, and the **Code** tab lets you edit the running model's source and hit Run to see the change immediately — no rebuild, no reload, the same "edit and go" workflow NetLogo itself has.

Switching the engine dropdown swaps the transport; the rendering code (`drawPatches`/`drawTurtles`/`drawPlot` in `static/app.js`) doesn't know or care which engine produced the state it's drawing.

## Architecture

```
engine/netlogo.py     the runtime: primitives, world state, widget system, auto_state()
models/*.py           twelve ported models + one original (Dimerizing Gas)
models/registry.json  which models are active, their key/label, and dropdown order
server/main.py        FastAPI app: model registry + HTTP API + static file serving
static/               zero-build frontend: index.html, app.js, style.css, pyodide-worker.js
```

Adding a model doesn't require touching `server/main.py` at all: drop the new `models/<key>.py` (with a module-level `INFO = """<h2>...</h2>..."""` HTML blurb next to its docstring, same as every other model) and add one `{"key": "<key>", "label": "..."}` to `models/registry.json`. Everything else in its registry entry — world size/wrapping, every slider/switch/chooser/monitor/plot, which source file the Code tab shows — is read straight off the module itself.

### `engine/netlogo.py` — the runtime

One module, ~1,450 lines, no external dependencies. It gives every model:

**World & agents**
`resize_world`, `set_wrap`, `min_pxcor`/`max_pxcor`/`min_pycor`/`max_pycor`, `patch_at`, `clear_all`, `Patch` (`.pcolor`, `.neighbors4()`/`.neighbors8()` — wrap around the torus if the world wraps, `.distance_to_xy()`, `.turtles_here()`, `.sprout()`), `Turtle` (`.xcor`/`.ycor`/`.heading`/`.color`/`.label`/`.size`, `.forward()`/`.right()`/`.left()`/`.move_to()`/`.face()`, `.patch_here()`/`.patch_ahead()`/`.patch_left_and_ahead()`/`.patch_right_and_ahead()`, `.distance_to()`/`.towards()`/`.in_radius()`/`.other()`/`.here()`/`.nearest()`, `.hatch()`, `.die()`, `.hide_turtle()`/`.show_turtle()`), `turtles`/`patches`/`links` (live agentsets), `create_breed`, `create_turtles`, `ask`, `.where(**kwargs)` (NetLogo's `with`), `.count()`/`.any()`. A turtle's `.label` (any value, shown as floating text; see Random Basic) and `.size` (scales how big it's drawn; see Diffusion on a Directed Network) are both optional — every turtle defaults to no label and `size=1.0`, matching the fixed-size, unlabeled triangle every earlier model already drew.

**Links**
`Link` (`.end1`/`.end2`/`.color`/`.breed`/`.directed`, `.other_end()`, `.both_ends()`, `.hide_link()`/`.show_link()`), `Turtle.create_link_with()`/`.link_neighbor()`/`.link_neighbors()`/`.my_links()` (the single unnamed, undirected default breed — see Virus on a Network), `layout_spring(turtles, links, spring_constant, spring_length, repulsion_constant)` (a one-time, cosmetic force-directed layout). `directed_link_breed`/`undirected_link_breed` declare a *named* breed (`LinkBreed`, with its own `.create_to()`, `.out_neighbors()`, `.in_from()`) — several can coexist, and "rewiring" a link between breeds is just reassigning its `.breed` (see Diffusion on a Directed Network, the first model here to use either).

**Pen drawing**
`Turtle.pen_down()`/`.pen_up()`, `clear_drawing` — moving a turtle with its pen down leaves a trail (an append-only history, unlike links: a segment stays even after the turtle that drew it dies; see Sierpinski Simple, the first model to use it).

**Math & randomness**
`sin`/`cos`/`atan` (degrees, matching NetLogo), `subtract_headings`, `mean`, `ceiling`/`floor`, `log(number, base)`, `random`/`random_float`/`random_poisson`/`one_of`/`n_of`/`shuffle`, `random_xcor`/`random_ycor`.

**Time**
`tick`/`tick_advance`/`ticks`/`reset_ticks`, `stop`.

**Color**
Named colors as plain floats (`black`, `gray`, `green`, `red`, `white`, `violet`, `cyan`, `sky`, `blue`, `yellow`, `brown`) with a small RGB table, `scale_color(base, number, low, high)` (NetLogo's `scale-color`, producing a genuine black→base→white gradient for *any* named color, not just a hardcoded one), and `color_to_rgb` for rendering.

**Diffusion**
`diffuse(attr_name, rate)` — a real 8-neighbor grid convolution over any patches-own attribute (NetLogo's `diffuse`).

**Mouse**
`mouse_xcor`/`mouse_ycor`/`mouse_down`/`mouse_inside` — read whatever the browser last reported over the world canvas (`set_mouse_state`, called by `POST /api/mouse`/the WASM engine's equivalent; see Life, the first model to use it).

**Widgets**
`slider`, `switch`, `chooser`, `monitor`, `button`, `plot_widget`/`plot`/`plotxy`/`histogram` — each is a plain function call at module load time that both returns the widget's default value *and* registers its metadata, so the model file is simultaneously the model and its own UI declaration. No separate spec to keep in sync. A plot pen defaults to an ordinary line/time-series pen; `plot_widget(..., pens=[(name, color, "bar")])` declares a real histogram-mode pen instead, fed by `histogram(pen, values)` (see Preferential Attachment).

**`auto_state()`**
NetLogo's own IDE never makes you write a serialization function — it just inspects turtles/patches/links/pen-drawing/plots directly to render them. `state()` only exists in this app because it needs one JSON snapshot per tick; `auto_state()` builds that snapshot automatically by reading whatever a model has already declared (every slider/switch/chooser value, every monitor — resolved by calling it if it's a function, else using it directly — the patch/turtle/link/drawing grids, plot data). Eleven of the thirteen models don't define `state()` at all; the other two override just the one or two things `auto_state()` can't guess (Ants' chemical-gradient patch coloring, Fire suppressing turtles it has but doesn't want drawn).

### Widget system → automatic UI

A model declares its own controls inline, at the top of the file, the same way NetLogo widgets sit on the model's Interface tab:

```python
population = slider("population", default=300, min=1, max=1000, step=1)
show_energy = switch("show_energy", default=False, label="show-energy?")
model_version = chooser("model_version", ["sheep-wolves", "sheep-wolves-grass"])
monitor("order_parameter", "order parameter")
plot_widget("populations", x_label="time", y_label="pop.", pens=[("sheep", "#f2c14e"), ("wolves", "#3a5a9c")])
```

`server/main.py` never hand-maintains a duplicate slider/monitor list — it reads each model's `__widgets__` (built as a side effect of the calls above) and the frontend renders sliders, switches, dropdowns, monitors, and a live line-chart plot purely from that, for whichever model is active.

## The HTTP API

All endpoints are relative to the running server (default `http://localhost:8765`). Every mutating endpoint returns the full current state (see **State shape** below) plus a `running: bool` flag.

| Method & path | Body | Returns |
|---|---|---|
| `GET /` | — | the frontend (`static/index.html`) |
| `GET /api/models` | — | the full model registry: for every model, its label and every slider/switch/chooser/monitor/plot spec (see below) |
| `POST /api/select-model` | `{"model": "wolf_sheep"}` | state after switching to that model and calling `setup()` |
| `POST /api/select-engine` | `{"engine": "server-side"}` | state after switching engines (`"server-side"` \| `"wasm"` — `wasm` is client-only, see below) |
| `GET /api/model-source?model=ants&engine=server-side` | — | `{"source": "<the model's .py file as text>"}` — powers the Code tab and the WASM engine's bootstrap |
| `GET /api/state` | — | the current state, without advancing |
| `POST /api/setup` | `{"<slider_name>": <value>, ...}` | applies each given value via `setattr`, calls `setup()`, returns state |
| `POST /api/step` | — | calls `go()` once, returns state |
| `POST /api/mouse` | `{"xcor": 3.2, "ycor": -1.0, "down": true, "inside": true}` | sets the shared mouse state, calls the model's `draw_cells()` if it defines one (see Life), returns state |
| `POST /api/command` | `{"text": "go"}` \| `{"text": "set population 50"}` | a tiny observer command line: `setup`, `go`, or `set <param> <value>` |
| `GET /py/engine/*` | — | raw text of `engine/*.py`, fetched by the in-browser WASM worker so it can bootstrap the same runtime client-side |

**Model spec** (one entry of `/api/models`'s `"models"` list):
```jsonc
{
  "key": "wolf_sheep",
  "label": "Wolf Sheep Predation",
  "sliders":  [{"name": "...", "label": "...", "default": 0, "min": 0, "max": 0, "step": 0, "units": "..."}],
  "switches": [{"name": "...", "label": "...", "default": true}],
  "choosers": [{"name": "...", "label": "...", "options": ["..."], "default": "..."}],
  "monitors": [{"key": "...", "label": "..."}],
  "plots": [{"title": "...", "x_label": "...", "y_label": "...", "pens": [{"name": "...", "color": "#...", "mode": "line"}]}],  // usually one, can be more (see Dimerizing Gas)
  "info": "<h2>...</h2>..."               // HTML description, shown in the Info tab
}
```

**State shape** (every mutating endpoint's response, model-dependent):
```jsonc
{
  "tick": 42,
  "width": 51, "height": 51,             // world size in patches
  "<slider_name>": 100,                  // every declared slider/switch/chooser, echoed back
  "<monitor_key>": 12.5,                 // every declared monitor's current value
  "plot_data": {"sheep": [[0, 100], [1, 98], ...]},  // present only if the model declares a plot
  "colors": [[[r,g,b], ...], ...],       // present only if the model has patches to draw
  "links": [[x1, y1, x2, y2, [r,g,b]], ...],  // present only if the model has links to draw
  "drawing": [[x1, y1, x2, y2, [r,g,b]], ...],  // present only if the model uses a pen -- same shape as "links"
  "turtles": [[xcor, ycor, heading, extra], ...],  // present only if the model has turtles to draw;
                                          // `extra` is a [r,g,b] real color, a 0/1 flag (e.g. Ants'
                                          // carrying-food state), or absent (draw a plain default color)
  "running": true
}
```

## Running it

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --reload --port 8765
```

Open `http://localhost:8765`. No build step, no bundler — `static/*.js`/`*.css`/`*.html` are served as-is. The first time you switch to the **WASM** engine it downloads Pyodide (~20MB, cached by the browser after that) into a Web Worker; every model runs identically on both engines.

## Adding a new model

1. Find the model's real `.nlogox` source (NetLogo ships a large Sample Models library) and read its `to setup`/`to go` code and `<widgets>` section.
2. Write `models/your_model.py`: `from engine.netlogo import *`, declare breeds/sliders/switches/monitors/a plot at the top, then `setup()`/`go()`/`is_running()` as free functions that read like a direct transliteration of the NetLogo procedures.
3. Only write your own `state()` if `auto_state()` can't guess something (custom patch/turtle coloring, or suppressing a rendered layer) — most models don't need one.
4. Register it in `server/main.py`'s `MODEL_REGISTRY` (a `"module"` entry plus an `"info"` blurb) — sliders/switches/choosers/monitors/plot are all pulled from the module automatically.
5. Test standalone first (`python -c "import models.your_model as m; m.setup(); ..."`), then through the server, then through the WASM engine.

## Attribution

Twelve of the thirteen models here are Python ports of designs from NetLogo's own Sample Models library (Uri Wilensky and the CCL, Northwestern University; individual model copyrights are noted in each `.nlogox` file). This repository is an independent educational reimplementation of their *behavior* in a from-scratch Python runtime — it does not include or depend on NetLogo itself. The thirteenth, Dimerizing Gas, is original to this app (see above).
