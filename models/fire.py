"""Python port of NetLogo's classic "Fire" model -- see
orig-src/NetLogo/models/Sample Models/Earth Science/Fire.nlogox for the
real source this was checked against line by line.

Written directly against engine/netlogo.py's free-function runtime instead
of a class: no __init__, no self -- module-level globals and top-level
procedures, the same shape as NetLogo's own `globals [...]` / `to setup` /
`to go`. See engine/netlogo.py's module docstring for the design decisions
behind that runtime (breed as a plain attribute, ask() returning a plain
list for `for`, .where() as an equality-only shorthand, slider() binding a
real number rather than a wrapper object).

Unlike this repo's old vectorized fire.py (deleted), which modeled burning
as a direct patch-color state machine (green -> red -> gray, one tick per
stage, no turtles at all), this is a faithful port of what the real model
actually does: burning patches sprout a "fires" turtle (the patch itself
goes black immediately), each fire ignites its green neighbors and then
downgrades to an "embers" turtle, and embers gradually darken over several
ticks before finally dying and stamping their color onto the patch. That
multi-tick fade is real NetLogo behavior this repo's earlier, simplified
port never had.
"""

from engine.netlogo import *

# The view: real Fire.nlogox is minPxcor="-125" maxPxcor="125" (same for y)
# -- shrunk here to fit a browser canvas. Declared once, like NetLogo's own
# view widget (fixed model config, not something setup() recomputes every
# time it runs), not inside setup() itself.
resize_world(-30, 30, -30, 30)

initial_trees = 0
burned_trees = 0

density = slider("density", default=55, min=0, max=99, step=1, units="%")
monitor("percent_burned", "percent burned")
button("setup")
button("go", forever=True)

fires = create_breed("fires", "fire")
embers = create_breed("embers", "ember")


def setup():
    global initial_trees, burned_trees
    clear_all()
    set_default_shape(turtles, "square")

    for p in ask(patches):
        if random_float(100) < density:
            p.pcolor = green

    for p in ask(patches.where(pxcor=min_pxcor())):
        ignite(p)

    initial_trees = patches.where(pcolor=green).count()
    burned_trees = 0
    reset_ticks()


def ignite(p):  # patch procedure
    global burned_trees
    for f in fires.sprout(p, 1):
        f.color = red
    p.pcolor = black
    burned_trees += 1


def go():
    if not turtles.any():
        stop()
        return

    for f in ask(fires):
        neighbors = f.patch_here().neighbors4().where(pcolor=green)
        for p in ask(neighbors):
            ignite(p)
        f.breed = "embers"

    fade_embers()
    tick()


def fade_embers():
    for e in ask(embers):
        e.color = e.color - 0.3
        if e.color < red - 3.5:
            e.patch_here().pcolor = e.color
            e.die()


def percent_burned():
    if initial_trees == 0:
        return 0.0
    return burned_trees / initial_trees * 100


def is_running():
    return turtles.any()


def state():
    # tick/width/height/density (slider)/percent_burned (monitor)/colors
    # are all built automatically -- see engine/netlogo.py's auto_state().
    # The only thing Fire needs to say for itself: it has real turtles
    # (fires/embers), but they're represented purely by patch color, so
    # don't also draw them as triangles.
    return auto_state(turtles=False)
