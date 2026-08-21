"""Python port of NetLogo's classic "Wolf Sheep Predation" model -- see
orig-src/NetLogo/models/Sample Models/Biology/Wolf Sheep Predation.nlogox
for the real source this was checked against line by line.

Deliberate deviations from the real source:
  - No turtle labels (`show-energy?` displaying each turtle's energy as
    floating text) -- this app's turtle renderer has no text-label
    capability. The switch is still ported (and still functional -- it's
    just that nothing reads it yet).
  - `netlogo-web?`-based max-sheep cap (10000 vs 30000) collapses to the
    single desktop value, 30000 -- there's no separate "web" vs "desktop"
    distinction in this app.
"""

INFO = """
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
"""

from engine.netlogo import *

resize_world(-25, 25, -25, 25)
set_wrap(True)

MAX_SHEEP = 30000  # real source's desktop value; keeps sheep from growing unbounded once wolves die out

model_version = chooser(
    "model_version",
    ["sheep-wolves", "sheep-wolves-grass"],
    label="model-version",
)
initial_number_sheep = slider(
    "initial_number_sheep",
    default=100,
    min=0,
    max=250,
    step=1,
    label="initial-number-sheep",
)
initial_number_wolves = slider(
    "initial_number_wolves",
    default=50,
    min=0,
    max=250,
    step=1,
    label="initial-number-wolves",
)
sheep_gain_from_food = slider(
    "sheep_gain_from_food",
    default=4,
    min=0,
    max=50,
    step=1,
    label="sheep-gain-from-food",
)
wolf_gain_from_food = slider(
    "wolf_gain_from_food",
    default=20,
    min=0,
    max=100,
    step=1,
    label="wolf-gain-from-food",
)
sheep_reproduce = slider(
    "sheep_reproduce",
    default=4,
    min=1,
    max=20,
    step=1,
    label="sheep-reproduce",
    units="%",
)
wolf_reproduce = slider(
    "wolf_reproduce",
    default=5,
    min=0,
    max=20,
    step=1,
    label="wolf-reproduce",
    units="%",
)
grass_regrowth_time = slider(
    "grass_regrowth_time",
    default=30,
    min=0,
    max=100,
    step=1,
    label="grass-regrowth-time",
)
show_energy = switch("show_energy", default=False, label="show-energy?")
monitor("sheep_count", "sheep")
monitor("wolves_count", "wolves")
monitor("grass_count_over_4", "grass")
plot_widget(
    "populations",
    x_label="time",
    y_label="pop.",
    pens=[
        ("sheep", "#f2c14e"),
        ("wolves", "#3a5a9c"),
        ("grass / 4", "#39d353"),
    ],
)
button("setup")
button("go", forever=True)

sheep = create_breed("sheep", "a_sheep")
wolves = create_breed("wolves", "wolf")


def setup():
    clear_all()

    if model_version == "sheep-wolves-grass":
        for p in ask(patches):
            p.pcolor = one_of([green, brown])
            if p.pcolor == green:
                p.countdown = grass_regrowth_time
            else:
                p.countdown = random(grass_regrowth_time)
    else:
        for p in ask(patches):
            p.pcolor = green

    for t in sheep.create(int(initial_number_sheep)):
        t.color = white
        t.energy = random(2 * sheep_gain_from_food)
        t.xcor = random_xcor()
        t.ycor = random_ycor()

    for t in wolves.create(int(initial_number_wolves)):
        t.color = black
        t.energy = random(2 * wolf_gain_from_food)
        t.xcor = random_xcor()
        t.ycor = random_ycor()

    reset_ticks()


def go():
    if not turtles.any():
        stop()
        return
    if not wolves.any() and sheep.count() > MAX_SHEEP:
        stop()
        return

    for t in ask(sheep):
        move(t)
        if model_version == "sheep-wolves-grass":
            t.energy -= 1
            eat_grass(t)
            death(t)
        reproduce_sheep(t)

    for t in ask(wolves):
        move(t)
        t.energy -= 1
        eat_sheep(t)
        death(t)
        reproduce_wolves(t)

    if model_version == "sheep-wolves-grass":
        for p in ask(patches):
            grow_grass(p)

    plot("sheep", sheep.count())
    plot("wolves", wolves.count())
    if model_version == "sheep-wolves-grass":
        plot("grass / 4", grass_count() / 4)

    tick()


def move(t):  # turtle procedure (sheep and wolves)
    t.right(random(50))
    t.left(random(50))
    t.forward(1)


def eat_grass(t):  # sheep procedure
    p = t.patch_here()
    if p.pcolor == green:
        p.pcolor = brown
        t.energy += sheep_gain_from_food


def reproduce_sheep(t):  # sheep procedure
    if random_float(100) < sheep_reproduce:
        t.energy = t.energy / 2
        for child in t.hatch():
            child.right(random_float(360))
            child.forward(1)


def reproduce_wolves(t):  # wolf procedure
    if random_float(100) < wolf_reproduce:
        t.energy = t.energy / 2
        for child in t.hatch():
            child.right(random_float(360))
            child.forward(1)


def eat_sheep(t):  # wolf procedure
    prey = one_of(t.here(sheep))
    if prey is not None:
        prey.die()
        t.energy += wolf_gain_from_food


def death(t):  # turtle procedure (sheep and wolves)
    if t.energy < 0:
        t.die()


def grow_grass(p):  # patch procedure
    if p.pcolor == brown:
        if p.countdown <= 0:
            p.pcolor = green
            p.countdown = grass_regrowth_time
        else:
            p.countdown -= 1


def grass_count():
    return patches.where(pcolor=green).count()


# Each monitor's key must be something auto_state() can resolve directly
# off this module -- a plain stored value or a zero-argument function (see
# engine/netlogo.py's auto_state()). `sheep`/`wolves` are breed handles,
# not counts, so the sheep/wolves/grass monitors point at these small
# wrappers instead of the breeds (or grass_count()) directly.
def sheep_count():
    return sheep.count()


def wolves_count():
    return wolves.count()


def grass_count_over_4():
    return grass_count() / 4


def is_running():
    if not turtles.any():
        return False
    if not wolves.any() and sheep.count() > MAX_SHEEP:
        return False
    return True


# No state() here -- tick/width/height, every slider/switch/chooser, the
# three monitors above, the plot (declared via plot_widget() above), and
# the patches/turtles grids (already exactly auto_state()'s defaults: real
# pcolor, real turtle color) are all built automatically. See
# engine/netlogo.py's auto_state() and the note above it.
