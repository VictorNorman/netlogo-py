"""Python port of NetLogo's classic "Life" (Conway's Game of Life) model
-- see Sample Models/Computer Science/Cellular Automata/Life.nlogox (from
the full NetLogo distribution, not bundled in this repo) for the real
source this was checked against line by line.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. The first
model in this app to use the mouse -- mouse_xcor()/mouse_ycor()/
mouse_down()/mouse_inside(), all added to engine/netlogo.py for this port.

Deliberate deviations from the real source:
  - Living/dead cell colors are fixed named colors (white/black) instead
    of the real model's `fgcolor`/`bgcolor` -- those are a color-picker
    text-box widget this engine doesn't have a primitive for (distinct
    from slider()/switch()/chooser()), and the real defaults (123.0/79.0)
    are only meaningful on NetLogo's full color wheel, which this engine
    deliberately doesn't implement (see engine/netlogo.py's module
    docstring on color).
  - The real widget set has four buttons (setup-blank, setup-random,
    go-once, go-forever) plus a separate draw-cells forever-button and a
    Patch-kind "recolor" button -- this app's frontend only has one fixed
    Setup/Go pair. setup() always does what setup-random did (an
    interesting starting pattern from initial-density, which you can then
    hand-edit with the mouse); setup-blank's logic is kept as its own
    function since it's genuinely useful (start from nothing and draw
    your own pattern) but isn't wired to a second button.
  - Mouse-drawing (draw_cells()) isn't gated behind its own forever-button
    toggle -- it's just always live whenever the mouse is down over the
    world canvas, whether or not go() is also running. Simpler than
    wiring a third independent forever-loop through this app's fixed
    button pair, at the cost of losing the real model's explicit
    draw/don't-draw mode switch.
"""

INFO = """
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
"""

from engine.netlogo import *

resize_world(-50, 50, -50, 50)
set_wrap(True)

LIVING_COLOR = white
DEAD_COLOR = black

initial_density = slider(
    "initial_density",
    default=35,
    min=0,
    max=100,
    step=0.1,
    label="initial-density",
    units="%",
)
monitor("current_density", "current density")
button("setup")
button("go", forever=True)

# None = not currently dragging; else the erase-vs-draw mode for this drag
# (matches the real model's `erasing?` global, reset to 0 between drags).
erasing = None


def setup():
    setup_random()


def setup_blank():
    clear_all()
    for p in ask(patches):
        cell_death(p)
    reset_ticks()


def setup_random():
    clear_all()
    for p in ask(patches):
        if random_float(100.0) < initial_density:
            cell_birth(p)
        else:
            cell_death(p)
    reset_ticks()


def cell_birth(p):  # patch procedure
    p.living = True
    p.pcolor = LIVING_COLOR


def cell_death(p):  # patch procedure
    p.living = False
    p.pcolor = DEAD_COLOR


def go():
    # Two separate passes -- as in the real source -- so every patch finishes
    # counting neighbors before any patch starts being born or dying, keeping
    # every cell in lockstep for this generation.
    for p in ask(patches):
        p.live_neighbors = p.neighbors8().where(living=True).count()
    for p in ask(patches):
        if p.live_neighbors == 3:
            cell_birth(p)
        elif p.live_neighbors != 2:
            cell_death(p)
    tick()


def draw_cells():
    global erasing
    if not mouse_down():
        erasing = None
        return
    p = patch_at(round(mouse_xcor()), round(mouse_ycor()))
    if p is None:
        return
    if erasing is None:
        erasing = p.living
    if erasing:
        cell_death(p)
    else:
        cell_birth(p)


def current_density():
    return patches.where(living=True).count() / patches.count()


def is_running():
    return True
