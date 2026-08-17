"""Python port of NetLogo's classic "Flocking" (boids) model -- see
orig-src/NetLogo/models/Sample Models/Biology/Flocking.nlogox for the real
source this was checked against line by line.

Rules per turtle, per tick (see `flock`, a near-literal transliteration of
the real `to flock` procedure):
  - find flockmates (other turtles within `vision`);
  - if any exist and the nearest is closer than `minimum_separation`, turn
    away from it (separate) and do nothing else;
  - otherwise turn toward the flockmates' average heading (align), then
    toward the average direction to them (cohere).
Real NetLogo animates movement in 5 sub-steps of 0.2 per tick purely so
`display` can force a redraw mid-tick for smoother motion; since this
app's frontend only ever redraws once per go() call regardless, that
sub-stepping buys nothing here -- the model's own comment says as much,
suggesting a single `fd 1` as the equivalent simplification, which is
what this uses.
"""

from engine.netlogo import *

resize_world(-35, 35, -35, 35)
set_wrap(True)

population = slider("population", default=300, min=1, max=1000, step=1)
vision = slider("vision", default=5, min=0, max=10, step=0.5, units="patches")
minimum_separation = slider(
    "minimum_separation",
    default=1,
    min=0,
    max=5,
    step=0.25,
    label="minimum-separation",
    units="patches",
)
max_align_turn = slider(
    "max_align_turn",
    default=5,
    min=0,
    max=20,
    step=0.25,
    label="max-align-turn",
    units="degrees",
)
max_cohere_turn = slider(
    "max_cohere_turn",
    default=3,
    min=0,
    max=20,
    step=0.25,
    label="max-cohere-turn",
    units="degrees",
)
max_separate_turn = slider(
    "max_separate_turn",
    default=1.5,
    min=0,
    max=20,
    step=0.25,
    label="max-separate-turn",
    units="degrees",
)
monitor("order_parameter", "order parameter")
button("setup")
button("go", forever=True)

speed = 1.0  # real Flocking's effective per-tick distance -- see module docstring


def setup():
    clear_all()
    for t in create_turtles(int(population)):
        t.xcor = random_xcor()
        t.ycor = random_ycor()
        t.color = green
        # Real NetLogo also does `set color yellow - 2 + random 7` (each
        # boid a slightly different shade) and `set size 1.5` -- simplified
        # to one fixed color, same spirit as this app's other deliberately
        # small color choices (see engine/netlogo.py's module docstring on
        # color); size has no visible effect since this app's turtle
        # renderer always draws a fixed-size triangle.
    reset_ticks()


def go():
    for t in ask(turtles):
        flock(t)
    for t in ask(turtles):
        t.forward(speed)
    tick()


def flock(t):  # turtle procedure
    flockmates = find_flockmates(t)
    if flockmates.any():
        nearest_neighbor = t.nearest(flockmates)
        if t.distance_to(nearest_neighbor) < minimum_separation:
            separate(t, nearest_neighbor)
        else:
            align(t, flockmates)
            cohere(t, flockmates)


def find_flockmates(t):  # turtle procedure
    return t.in_radius(t.other(turtles), vision)


# --- separate ---


def separate(t, nearest_neighbor):  # turtle procedure
    turn_away(t, nearest_neighbor.heading, max_separate_turn)


# --- align ---


def align(t, flockmates):  # turtle procedure
    target = average_flockmate_heading(flockmates)
    if target is not None:
        turn_towards(t, target, max_align_turn)


def average_flockmate_heading(flockmates):
    # Can't just average the heading numbers -- the average of 1 and 359
    # should be 0, not 180 -- so this goes through the sin/cos components
    # like the real model does.
    x_component = sum(f.dx for f in flockmates)
    y_component = sum(f.dy for f in flockmates)
    if x_component == 0 and y_component == 0:
        return None
    return atan(x_component, y_component)


# --- cohere ---


def cohere(t, flockmates):  # turtle procedure
    target = average_heading_towards_flockmates(t, flockmates)
    if target is not None:
        turn_towards(t, target, max_cohere_turn)


def average_heading_towards_flockmates(t, flockmates):
    # Real NetLogo computes this from each flockmate's own perspective
    # (`[sin (towards myself + 180)] of flockmates`), since `towards`
    # always means "from me to X". `towards myself + 180`, evaluated by a
    # flockmate, is the heading from *this* turtle to *that* flockmate --
    # exactly what t.towards(f) already gives directly, so there's no need
    # to reproduce the "ask from the other agent's perspective" indirection.
    headings_to_flockmates = [t.towards(f) for f in flockmates]
    x_component = mean(sin(h) for h in headings_to_flockmates)
    y_component = mean(cos(h) for h in headings_to_flockmates)
    if x_component == 0 and y_component == 0:
        return None
    return atan(x_component, y_component)


# --- helper procedures ---


def turn_towards(t, new_heading, max_turn):  # turtle procedure
    turn_at_most(t, subtract_headings(new_heading, t.heading), max_turn)


def turn_away(t, new_heading, max_turn):  # turtle procedure
    turn_at_most(t, subtract_headings(t.heading, new_heading), max_turn)


def turn_at_most(t, turn, max_turn):  # turtle procedure
    if abs(turn) > max_turn:
        if turn > 0:
            t.right(max_turn)
        else:
            t.left(max_turn)
    else:
        t.right(turn)


def order_parameter():
    """Not part of the real model -- this app's own addition. Mean
    resultant length of heading vectors: 0 = random/scattered headings, 1
    = perfectly aligned flock."""
    if turtles.count() == 0:
        return 0.0
    avg_sin = mean(t.dx for t in turtles)
    avg_cos = mean(t.dy for t in turtles)
    return (avg_sin**2 + avg_cos**2) ** 0.5


def is_running():
    return True


# No state() here -- tick/width/height, every slider, the order_parameter
# monitor, and the turtles list (colored by each boid's own real color,
# set in setup() above) are all built automatically. See
# engine/netlogo.py's auto_state() and the note above it.
