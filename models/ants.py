"""Python port of NetLogo's classic "Ants" model -- see
orig-src/NetLogo/models/Sample Models/Biology/Ants.nlogox for the real
source this was checked against line by line.

Deliberate deviations from the real source:
  - Carrying-food state is tracked with an explicit `carrying` boolean
    attribute, not by turtle color (`color = red` / `color = orange + 1`
    in the real model) -- this app's frontend already renders ants by a
    carrying flag (see static/app.js's drawTurtles), and an explicit
    boolean reads more directly than "the color IS the state."
  - `food_in_nest`/`food_remaining` monitors and a self-terminating
    is_running() (real Ants just runs forever) are this app's own
    additions beyond the source, a value-add rather than a real-source
    deviation.
"""

from engine.netlogo import *

resize_world(-35, 35, -35, 35)
set_wrap(False)

population = slider("population", default=125, min=0, max=200, step=1)
diffusion_rate = slider("diffusion_rate", default=50, min=0, max=99, step=1, label="diffusion-rate")
evaporation_rate = slider("evaporation_rate", default=10, min=0, max=99, step=1, label="evaporation-rate")
monitor("food_in_nest", "food in nest")
monitor("food_remaining", "food remaining")
plot_widget(
    "Food in each pile",
    x_label="time",
    y_label="food",
    pens=[
        # Matching each pen's color to the pile's own patch color (cyan/
        # sky/blue) rather than the real source's arbitrary pen colors --
        # makes the pen-to-pile mapping obvious at a glance.
        ("food-in-pile1", "#00c8c8"),
        ("food-in-pile2", "#64a5eb"),
        ("food-in-pile3", "#325adc"),
    ],
)
button("setup")
button("go", forever=True)

NEST_RADIUS = 5
FOOD_RADIUS = 5
CHEMICAL_DEPOSIT = 60

food_in_nest = 0


def setup():
    global food_in_nest
    clear_all()
    set_default_shape(turtles, "bug")
    for t in create_turtles(int(population)):
        t.size = 2
        t.carrying = False
        # real source also does `set color red` here -- skipped, since
        # this app colors ants by the carrying flag directly (see
        # module docstring).
    setup_patches()
    food_in_nest = 0
    reset_ticks()


def setup_patches():
    for p in ask(patches):
        setup_nest(p)
        setup_food(p)
        recolor_patch(p)


def setup_nest(p):  # patch procedure
    p.chemical = 0.0
    p.is_nest = p.distance_to_xy(0, 0) < NEST_RADIUS
    p.nest_scent = 200 - p.distance_to_xy(0, 0)


def setup_food(p):  # patch procedure
    p.food_source_number = 0
    p.food = 0
    if p.distance_to_xy(0.6 * max_pxcor(), 0) < FOOD_RADIUS:
        p.food_source_number = 1
    if p.distance_to_xy(-0.6 * max_pxcor(), -0.6 * max_pycor()) < FOOD_RADIUS:
        p.food_source_number = 2
    if p.distance_to_xy(-0.8 * max_pxcor(), 0.8 * max_pycor()) < FOOD_RADIUS:
        p.food_source_number = 3
    if p.food_source_number > 0:
        p.food = one_of([1, 2])


def recolor_patch(p):  # patch procedure
    if p.is_nest:
        p.pcolor = violet
    elif p.food > 0:
        if p.food_source_number == 1:
            p.pcolor = cyan
        elif p.food_source_number == 2:
            p.pcolor = sky
        elif p.food_source_number == 3:
            p.pcolor = blue
    else:
        p.pcolor = scale_color(green, p.chemical, 0.1, 5)


def go():
    for t in ask(turtles):
        if t.who >= ticks():  # delay initial departure -- ants trickle out, not burst out
            continue
        if not t.carrying:
            look_for_food(t)
        else:
            return_to_nest(t)
        wiggle(t)
        t.forward(1)

    diffuse("chemical", diffusion_rate / 100)

    for p in ask(patches):
        p.chemical = p.chemical * (100 - evaporation_rate) / 100
        recolor_patch(p)

    tick()

    plotxy("food-in-pile1", ticks(), food_in_pile(cyan))
    plotxy("food-in-pile2", ticks(), food_in_pile(sky))
    plotxy("food-in-pile3", ticks(), food_in_pile(blue))


def food_in_pile(pile_color):
    return sum(p.food for p in patches.where(pcolor=pile_color))


def return_to_nest(t):  # turtle procedure
    global food_in_nest
    p = t.patch_here()
    if p.is_nest:
        food_in_nest += 1
        t.carrying = False
        t.right(180)
    else:
        p.chemical += CHEMICAL_DEPOSIT
        uphill_nest_scent(t)


def look_for_food(t):  # turtle procedure
    p = t.patch_here()
    if p.food > 0:
        t.carrying = True
        p.food -= 1
        t.right(180)
        return
    if 0.05 <= p.chemical < 2:
        uphill_chemical(t)


def uphill_chemical(t):  # turtle procedure, "sniff left and right, go where the smell is strongest"
    scent_ahead = chemical_scent_at_angle(t, 0)
    scent_right = chemical_scent_at_angle(t, 45)
    scent_left = chemical_scent_at_angle(t, -45)
    if scent_right > scent_ahead or scent_left > scent_ahead:
        if scent_right > scent_left:
            t.right(45)
        else:
            t.left(45)


def uphill_nest_scent(t):  # turtle procedure
    scent_ahead = nest_scent_at_angle(t, 0)
    scent_right = nest_scent_at_angle(t, 45)
    scent_left = nest_scent_at_angle(t, -45)
    if scent_right > scent_ahead or scent_left > scent_ahead:
        if scent_right > scent_left:
            t.right(45)
        else:
            t.left(45)


def chemical_scent_at_angle(t, angle):
    p = t.patch_right_and_ahead(angle, 1)
    return 0 if p is None else p.chemical


def nest_scent_at_angle(t, angle):
    p = t.patch_right_and_ahead(angle, 1)
    return 0 if p is None else p.nest_scent


def wiggle(t):  # turtle procedure
    t.right(random(40))
    t.left(random(40))
    if not t.can_move(1):
        t.right(180)


def food_remaining():
    return sum(p.food for p in patches)


def is_running():
    return not (food_remaining() == 0 and not any(t.carrying for t in turtles))


def _turtle_extra(t):
    # In place of the turtle's real color -- see the module docstring on
    # why carrying is an explicit flag rather than color-encoded state.
    return 1.0 if t.carrying else 0.0


def state():
    # tick/width/height, every slider, the food_in_nest/food_remaining
    # monitors, and the patches grid (recolor_patch() already stores the
    # real chemical-trail shade straight into pcolor via scale_color(),
    # same as real NetLogo, so the default color_to_rgb(p.pcolor) needs no
    # override) are all built automatically -- see engine/netlogo.py's
    # auto_state(). Only turtle coloring is Ants-specific.
    return auto_state(turtle_color=_turtle_extra)
