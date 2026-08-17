"""Python port of NetLogo's classic "Sierpinski Simple" model -- see
Sample Models/Mathematics/Fractals/Sierpinski Simple.nlogox (from the full
NetLogo distribution, not bundled in this repo) for the real source this
was checked against line by line.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. The first
model in this app to use a pen -- Turtle.pen_down()/pen_up(), added to
engine/netlogo.py for this port.

Deliberate deviations from the real source:
  - The real widget set has a "Go Once" (non-forever) button and a
    Turtle-kind "hide turtles" button -- this app's frontend only has one
    fixed Setup/Go pair. go() here is bound to the forever button, so
    holding it down repeatedly grows the fractal automatically instead of
    needing repeated clicks; there's no way to hide turtles from this
    app's UI, so the small triangle turtle markers stay visible riding
    along the tips of the tree (harmless -- they just show where the
    next round of growth will branch from).
"""

from engine.netlogo import *

resize_world(-17, 17, -17, 17)
set_wrap(False)

monitor("turtle_count", "Num Turtles")
button("setup")
button("go", forever=True)


def setup():
    clear_all()
    for t in create_turtles(1):
        t.heading = 0
        t.xcor = 0
        t.ycor = -3
        t.modulus = 0.5 * max_pycor()
        t.pen_down()
    reset_ticks()


def grow(t):  # turtle procedure -- move forward by t's modulus, create a new
    # turtle to draw the next iteration of the tree, and return to place
    for child in t.hatch(1):
        child.forward(child.modulus)
        child.modulus = 0.5 * child.modulus  # new turtle's modulus is half its parent's


def go():  # draw the sierpinski tree
    for t in ask(turtles):
        for _ in range(3):
            grow(t)
            t.right(120)  # turn counter-clockwise to draw more legs
        t.die()  # kill all the living turtles
    tick()


def turtle_count():
    return turtles.count()


def is_running():
    return True
