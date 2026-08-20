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
    return both at once. The "render" field below is documentation only,
    not consumed by the frontend. Most models don't define state() at
    all -- see _state() below and engine/netlogo.py's auto_state(), which
    builds it automatically from a model's already-declared widgets.
Slider "name"s below are exactly the model's attribute names, so the setup
and command endpoints can apply them with plain setattr()/hasattr() and
never need to know which model is active.

Each model is available on one server-side engine, "vectorized" -- despite
the name, no model actually uses NumPy anymore (see engine/netlogo.py's
module docstring: every model is now a class-less module of free functions
operating on plain per-agent Python objects, closer to real NetLogo than
an array-vectorized implementation could read). The name has stuck around
as the engine key/label since renaming it is cosmetic, not worth touching
for its own sake.

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

import pathlib
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engine.netlogo as netlogo


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


import models.fire as fire_module

FIRE_WORLD = _world_snapshot()
import models.flocking as flocking_module

FLOCKING_WORLD = _world_snapshot()
import models.gas_lab as gas_lab_module

GAS_LAB_WORLD = _world_snapshot()
import models.ants as ants_module

ANTS_WORLD = _world_snapshot()
import models.wolf_sheep as wolf_sheep_module

WOLF_SHEEP_WORLD = _world_snapshot()
import models.virus_on_network as virus_module

VIRUS_WORLD = _world_snapshot()
import models.life as life_module

LIFE_WORLD = _world_snapshot()
import models.sierpinski as sierpinski_module

SIERPINSKI_WORLD = _world_snapshot()
import models.preferential_attachment as preferential_attachment_module

PREFERENTIAL_ATTACHMENT_WORLD = _world_snapshot()
import models.rock_paper_scissors as rock_paper_scissors_module

ROCK_PAPER_SCISSORS_WORLD = _world_snapshot()
import models.random_basic as random_basic_module

RANDOM_BASIC_WORLD = _world_snapshot()
import models.diffusion_on_directed_network as diffusion_module

DIFFUSION_WORLD = _world_snapshot()
import models.dimerizing_gas as dimerizing_gas_module

DIMERIZING_GAS_WORLD = _world_snapshot()

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

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
    "vectorized": {"label": "Vectorized (NumPy)"},
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
    "fire": {
        "label": "Fire",
        "world": FIRE_WORLD,
        "render": "patches",
        # Sliders/monitors come from the module itself (models/fire.py's
        # `density = slider("density", ...)` / `monitor("percent_burned",
        # ...)`), not hand-copied here -- see engine/netlogo.py's slider()/
        # monitor() and _sliders_from_module()/_monitors_from_module() above.
        "sliders": _sliders_from_module(fire_module),
        "switches": _switches_from_module(fire_module),
        "choosers": _choosers_from_module(fire_module),
        "monitors": _monitors_from_module(fire_module),
        "plots": _plots_from_module(fire_module),
        "info": """
            <h2>Fire</h2>
            <p>
              Trees (green) are scattered across the world at the given density.
              The left edge is set alight; a burning patch turns black and sprouts
              a "fires" turtle (bright red). Each tick, every fire ignites its
              green neighbor patches, then becomes an "embers" turtle, which
              gradually darkens over several ticks before finally dying out. The
              model stops once no fires or embers remain.
            </p>
            <p>
              This models the idea of a percolation threshold: below a critical
              density the fire tends to die out quickly, while above it the fire
              tends to spread across the whole forest.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": fire_module,
                "source_file": "models/fire.py",
            },
        },
    },
    "flocking": {
        "label": "Flocking",
        "world": FLOCKING_WORLD,
        "render": "turtles",
        "sliders": _sliders_from_module(flocking_module),
        "switches": _switches_from_module(flocking_module),
        "choosers": _choosers_from_module(flocking_module),
        "monitors": _monitors_from_module(flocking_module),
        "plots": _plots_from_module(flocking_module),
        "info": """
            <h2>Flocking</h2>
            <p>
              A Python port of NetLogo's classic <em>Flocking</em> (boids) model.
              Each tick, every turtle applies three rules based on nearby
              flockmates (other turtles within <code>vision</code>):
            </p>
            <ul>
              <li><strong>separate</strong> — if the nearest flockmate is closer
                than <code>minimum-separation</code>, turn away from it and do
                nothing else;</li>
              <li><strong>align</strong> — otherwise, turn toward the average
                heading of all flockmates;</li>
              <li><strong>cohere</strong> — then turn toward the average
                direction to those same flockmates.</li>
            </ul>
            <p>
              The order parameter monitor is the mean resultant length of all
              headings: near 0 means headings are scattered/random, near 1 means
              the flock has aligned into unified movement.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": flocking_module,
                "source_file": "models/flocking.py",
            },
        },
    },
    "gaslab": {
        "label": "GasLab",
        "world": GAS_LAB_WORLD,
        "render": "patches_and_turtles",
        "sliders": _sliders_from_module(gas_lab_module),
        "switches": _switches_from_module(gas_lab_module),
        "choosers": _choosers_from_module(gas_lab_module),
        "monitors": _monitors_from_module(gas_lab_module),
        "plots": _plots_from_module(gas_lab_module),
        "info": """
            <h2>GasLab</h2>
            <p>
              A Python port of NetLogo's classic <em>GasLab: Gas in a Box</em>
              model: particles bounce elastically off the walls of a closed
              box (yellow) and off each other, conserving total kinetic
              energy exactly. Particles are colored by speed: blue (slow),
              green (medium), red (fast).
            </p>
            <p>
              Like Flocking, collision detection is an O(N&sup2;) turtle-turtle
              comparison every tick -- one of the most commonly cited "NetLogo
              is slow" examples, since GasLab pairs that cost with actual
              physics (not just a heading nudge). Watch <em>average speed</em>
              drift away from the initial uniform speed while <em>total KE</em>
              stays exactly constant: collisions redistribute energy into a
              spread of speeds even though the total is conserved.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": gas_lab_module,
                "source_file": "models/gas_lab.py",
            },
        },
    },
    "ants": {
        "label": "Ants",
        "world": ANTS_WORLD,
        "render": "patches_and_turtles",
        "sliders": _sliders_from_module(ants_module),
        "switches": _switches_from_module(ants_module),
        "choosers": _choosers_from_module(ants_module),
        "monitors": _monitors_from_module(ants_module),
        "plots": _plots_from_module(ants_module),
        "info": """
            <h2>Ants</h2>
            <p>
              A Python port of NetLogo's classic <em>Ants</em> model. Ants
              (white) wander randomly from the nest (violet) until they find
              food (cyan/sky/blue, one shade per pile); carrying food home,
              they lay a chemical trail (green) other ants can follow, and
              home in on the nest using a fixed nest-scent gradient. Ants
              currently carrying food are drawn red.
            </p>
            <p>
              Unlike Fire (which only ever conditionally recolors patches),
              every tick here runs <code>diffuse</code> unconditionally over
              every patch to spread the chemical trail -- an O(patches) cost
              that has nothing to do with how many ants exist or where they
              are, the other classic expensive NetLogo patch workload
              alongside Flocking/GasLab's O(N&sup2;) turtle-turtle cost.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": ants_module,
                "source_file": "models/ants.py",
            },
        },
    },
    "wolf_sheep": {
        "label": "Wolf Sheep Predation",
        "world": WOLF_SHEEP_WORLD,
        "render": "patches_and_turtles",
        "sliders": _sliders_from_module(wolf_sheep_module),
        "switches": _switches_from_module(wolf_sheep_module),
        "choosers": _choosers_from_module(wolf_sheep_module),
        "monitors": _monitors_from_module(wolf_sheep_module),
        "plots": _plots_from_module(wolf_sheep_module),
        "info": """
            <h2>Wolf Sheep Predation</h2>
            <p>
              A Python port of NetLogo's classic <em>Wolf Sheep Predation</em>
              model. Sheep (tan) and wolves (dark) wander randomly; a wolf
              that shares a patch with a sheep eats it, and both species
              reproduce at a random rate each tick. Switch <code>model-version</code>
              to <code>sheep-wolves-grass</code> to also model grass (green,
              eaten by sheep and regrowing over time) -- without it, sheep
              never need to eat, which produces interesting but ultimately
              unstable population swings; with it, the system is a much
              closer (and generally stable) match to the classic
              Lotka-Volterra predator-prey oscillation.
            </p>
            <p>
              The <em>populations</em> plot below is this app's first: each
              tick, the model calls <code>plot("sheep", ...)</code> /
              <code>plot("wolves", ...)</code> / <code>plot("grass / 4", ...)</code>
              (engine/netlogo.py's `plot()`) to append a point per pen,
              exactly mirroring the real model's own three plot pens.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": wolf_sheep_module,
                "source_file": "models/wolf_sheep.py",
            },
        },
    },
    "virus_on_network": {
        "label": "Virus on a Network",
        "world": VIRUS_WORLD,
        "render": "turtles_and_links",
        "sliders": _sliders_from_module(virus_module),
        "switches": _switches_from_module(virus_module),
        "choosers": _choosers_from_module(virus_module),
        "monitors": _monitors_from_module(virus_module),
        "plots": _plots_from_module(virus_module),
        "info": """
            <h2>Virus on a Network</h2>
            <p>
              A Python port of NetLogo's classic <em>Virus on a Network</em>
              model -- the first model in this app to use links. Nodes
              (turtles) are susceptible (blue), infected (red), or resistant
              (gray), connected by a randomly-built, spatially-clustered
              network. Each tick, infected nodes may spread the virus to
              their uninfected neighbors along a link, then periodically
              check whether they recover (possibly gaining resistance) or
              stay infected.
            </p>
            <p>
              The network's layout is computed once during setup (a simple
              force-directed <code>layout_spring</code>, added to
              engine/netlogo.py for this port) -- turtles never move again
              once <code>go</code> starts, so what you're watching is purely
              color/link changes as the epidemic spreads across a fixed graph.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": virus_module,
                "source_file": "models/virus_on_network.py",
            },
        },
    },
    "life": {
        "label": "Life",
        "world": LIFE_WORLD,
        "render": "patches",
        "sliders": _sliders_from_module(life_module),
        "switches": _switches_from_module(life_module),
        "choosers": _choosers_from_module(life_module),
        "monitors": _monitors_from_module(life_module),
        "plots": _plots_from_module(life_module),
        "info": """
            <h2>Life</h2>
            <p>
              A Python port of NetLogo's classic <em>Life</em> (Conway's Game
              of Life) model -- the first model in this app that responds to
              the mouse. Each patch is alive or dead; every tick, a cell is
              born if it has exactly 3 living neighbors, survives if it has
              2 or 3, and dies otherwise.
            </p>
            <p>
              Click and drag on the grid (with or without <em>go</em>
              running) to draw or erase cells by hand -- whether the drag
              draws or erases is decided by whatever the first cell you
              touch already was, so dragging across a mix of live and dead
              cells stays consistent for the whole gesture, matching the
              real model's own draw-cells behavior.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": life_module,
                "source_file": "models/life.py",
            },
        },
    },
    "sierpinski": {
        "label": "Sierpinski Simple",
        "world": SIERPINSKI_WORLD,
        "render": "turtles",
        "sliders": _sliders_from_module(sierpinski_module),
        "switches": _switches_from_module(sierpinski_module),
        "choosers": _choosers_from_module(sierpinski_module),
        "monitors": _monitors_from_module(sierpinski_module),
        "plots": _plots_from_module(sierpinski_module),
        "info": """
            <h2>Sierpinski Simple</h2>
            <p>
              A Python port of NetLogo's classic <em>Sierpinski Simple</em>
              model -- the first model in this app to use a pen. One turtle
              starts with its pen down; each tick, every living turtle
              hatches three children (one per leg of a Y shape), each
              moving forward and leaving a trail, then the parent dies. The
              legs get half as long each generation, tracing out Sierpinski's
              self-similar tree.
            </p>
            <p>
              Click <em>go</em> repeatedly (or hold it) to grow the tree one
              generation at a time -- watch <em>Num Turtles</em> triple
              (3, 9, 27, ...) each tick as the fractal branches.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": sierpinski_module,
                "source_file": "models/sierpinski.py",
            },
        },
    },
    "preferential_attachment": {
        "label": "Preferential Attachment",
        "world": PREFERENTIAL_ATTACHMENT_WORLD,
        "render": "turtles",
        "sliders": _sliders_from_module(preferential_attachment_module),
        "switches": _switches_from_module(preferential_attachment_module),
        "choosers": _choosers_from_module(preferential_attachment_module),
        "monitors": _monitors_from_module(preferential_attachment_module),
        "plots": _plots_from_module(preferential_attachment_module),
        "info": """
            <h2>Preferential Attachment</h2>
            <p>
              A Python port of NetLogo's classic <em>Preferential
              Attachment</em> model -- the first model in this app to use a
              real histogram-mode plot pen. Starting from two connected
              nodes, each tick adds one new node, linked to a random END of
              a random EXISTING link -- so a node with more connections is
              proportionally more likely to gain new ones ("rich get
              richer"), the mechanism behind real-world "scale-free"
              networks like the web or social graphs.
            </p>
            <p>
              Watch the <em>Degree Distribution</em> histogram develop a
              long tail: most nodes stay small, but a few "hubs" accumulate
              a disproportionate share of the connections.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": preferential_attachment_module,
                "source_file": "models/preferential_attachment.py",
            },
        },
    },
    "rock_paper_scissors": {
        "label": "Rock Paper Scissors",
        "world": ROCK_PAPER_SCISSORS_WORLD,
        "render": "patches",
        "sliders": _sliders_from_module(rock_paper_scissors_module),
        "switches": _switches_from_module(rock_paper_scissors_module),
        "choosers": _choosers_from_module(rock_paper_scissors_module),
        "monitors": _monitors_from_module(rock_paper_scissors_module),
        "plots": _plots_from_module(rock_paper_scissors_module),
        "info": """
            <h2>Rock Paper Scissors</h2>
            <p>
              A Python port of NetLogo's classic <em>Rock Paper Scissors</em>
              model. Every patch is red, green, blue, or blank; red beats
              green, green beats blue, blue beats red. Each tick, random
              pairs of neighboring patches swap, reproduce, or compete, at
              rates drawn from a Poisson distribution -- producing the
              chasing spirals characteristic of cyclic-dominance ecosystems.
            </p>
            <p>
              The three <code>*-rate-exponent</code> sliders each scale
              their event's rate by a power of 10 -- watch how much faster
              <em>swap</em> (movement) needs to be, relative to
              <em>select</em> (competition), to keep the spirals stable
              instead of collapsing to one color.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": rock_paper_scissors_module,
                "source_file": "models/rock_paper_scissors.py",
            },
        },
    },
    "random_basic": {
        "label": "Random Basic",
        "world": RANDOM_BASIC_WORLD,
        "render": "patches_and_turtles",
        "sliders": _sliders_from_module(random_basic_module),
        "switches": _switches_from_module(random_basic_module),
        "choosers": _choosers_from_module(random_basic_module),
        "monitors": _monitors_from_module(random_basic_module),
        "plots": _plots_from_module(random_basic_module),
        "info": """
            <h2>Random Basic</h2>
            <p>
              A Python port of NetLogo's classic <em>Random Basic</em>
              (ProbLab) model -- the first model in this app to use turtle
              labels. Each tick, a black "messenger" turtle picks a random
              number, its label, and walks to the matching column of a
              histogram, dropping a "frame" there -- building up the
              distribution of a random variable one draw at a time.
            </p>
            <p>
              The <em>red-green</em> slider splits the columns into two
              groups, colored as the histogram fills in (when
              <em>colors?</em> is on) -- watch <em>%-red</em> converge
              toward whatever share of the sample space falls left of that
              split.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": random_basic_module,
                "source_file": "models/random_basic.py",
            },
        },
    },
    "diffusion_on_directed_network": {
        "label": "Diffusion on a Directed Network",
        "world": DIFFUSION_WORLD,
        "render": "turtles_and_links",
        "sliders": _sliders_from_module(diffusion_module),
        "switches": _switches_from_module(diffusion_module),
        "choosers": _choosers_from_module(diffusion_module),
        "monitors": _monitors_from_module(diffusion_module),
        "plots": _plots_from_module(diffusion_module),
        "info": """
            <h2>Diffusion on a Directed Network</h2>
            <p>
              A Python port of NetLogo's classic <em>Diffusion on a
              Directed Network</em> model -- the first model in this app
              to use directed links and more than one link breed. Each
              tick, every node keeps a share of its own "value" and
              divides the rest evenly among its outgoing links -- since
              links are directed, node B can give value to node A without
              A giving anything back.
            </p>
            <p>
              A node's size shows how much value it holds; a link's
              brightness shows how much value just flowed through it.
              Watch the network settle toward an equilibrium -- sometimes
              one node ends up with nearly everything, sometimes value
              stays spread across many.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": diffusion_module,
                "source_file": "models/diffusion_on_directed_network.py",
            },
        },
    },
    "dimerizing_gas": {
        "label": "Dimerizing Gas (2A ⇌ B)",
        "world": DIMERIZING_GAS_WORLD,
        "render": "patches_and_turtles",
        "sliders": _sliders_from_module(dimerizing_gas_module),
        "switches": _switches_from_module(dimerizing_gas_module),
        "choosers": _choosers_from_module(dimerizing_gas_module),
        "monitors": _monitors_from_module(dimerizing_gas_module),
        "plots": _plots_from_module(dimerizing_gas_module),
        "info": """
            <h2>Dimerizing Gas (2A &#8652; B)</h2>
            <p>
              An original model for this app (not a NetLogo Sample Models port)
              -- the same hard-sphere box-of-particles physics as
              <em>GasLab</em>, plus a reversible reaction: two A particles
              (light blue) that collide may fuse into one B particle (red,
              drawn larger -- it has twice the mass), and a B particle that
              hits anything -- another particle or a wall -- may fall back
              apart into two A's. <code>dimerization-chance</code> and
              <code>dissociation-chance</code> control how likely each event
              is, per collision.
            </p>
            <p>
              This is a classic demonstration of <strong>dynamic
              equilibrium</strong>: even though individual molecules keep
              reacting in both directions constantly, the population counts
              (see the <em>Populations</em> plot) settle into a stable
              balance where the forward and reverse reaction rates match.
              <code>A + 2&times;B</code> (the total A-equivalent mass) never
              changes -- only how it's distributed between the two species
              does. If the reaction is behaving like real mass-action
              chemistry, <code>B / A&sup2;</code> (the <em>Kc</em> monitor)
              should hold roughly steady once equilibrium is reached, however
              you got there -- try starting from all-A (<code>initial-B =
              0</code>) versus starting with some B already present.
            </p>
            <p>
              The <em>Speed Distribution</em> histogram (the first plot in
              this app to share its canvas with a second plot_widget) shows
              each species' molecular speeds converging toward a Maxwell-
              Boltzmann-shaped spread, exactly like GasLab's -- <code>
              temperature</code> sets the initial speeds (equal average
              kinetic energy per particle for both species) and also scales
              how energetic a freshly-dissociated pair of A's comes apart.
            </p>
        """,
        "engines": {
            "vectorized": {
                "module": dimerizing_gas_module,
                "source_file": "models/dimerizing_gas.py",
            },
        },
    },
}

active_model_key = "flocking"
active_engine_key = "vectorized"


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
                "render": entry["render"],
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
