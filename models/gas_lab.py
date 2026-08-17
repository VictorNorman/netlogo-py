"""Python port of NetLogo's classic "GasLab Gas in a Box" model -- see
orig-src/NetLogo/models/Sample Models/Chemistry & Physics/GasLab/GasLab Gas
in a Box.nlogox for the real source this was checked against line by line
(there's also a "GasLab Free Gas" variant that wraps instead of using
walls -- not the one ported here, since this app's box-with-walls framing
matches "Gas in a Box").

Deliberate deviations from the real source:
  - No `flashes` breed (the real model sprouts a fading colored patch-flash
    turtle wherever a particle bounces off a wall) -- purely decorative,
    and this app has no per-turtle-lifetime/fade rendering to show it.
  - No `trace?` switch / pen-drawing (a particle-0 motion trail) -- same
    reasoning, no pen/drawing rendering exists in this app.
  - No plot widgets (the real model's speed/energy histograms) --
    engine/netlogo.py does have plot_widget()/plot() now, just not used
    for this model yet.
  - `shade-of? yellow [pcolor] of new-patch` (real NetLogo's fuzzy
    same-hue-family check) is simplified to a direct `== yellow` -- this
    model's wall patches are always exactly yellow, never a shaded
    variant, so the fuzzy check and the exact one agree here. Same spirit
    as engine/netlogo.py's deliberately small color model generally.
  - `total_kinetic_energy` is this app's own addition (not a real-source
    monitor) alongside the real percent-fast/medium/slow and average
    speed/energy monitors -- kept because "KE stays exactly constant while
    speeds spread out" is this app's pedagogical hook for the model (see
    the info text in server/main.py).
"""

from engine.netlogo import *

resize_world(-40, 40, -40, 40)
set_wrap(False)

number_of_particles = slider("number_of_particles", default=100, min=1, max=1000, step=1, label="number-of-particles")
box_size = slider("box_size", default=95, min=5, max=100, step=1, label="box-size", units="%")
particle_mass = slider("particle_mass", default=1, min=1, max=20, step=1, label="particle-mass")
init_particle_speed = slider("init_particle_speed", default=10, min=1, max=20, step=1, label="init-particle-speed")
collide = switch("collide", default=True, label="collide?")
monitor("percent_fast", "percent fast")
monitor("percent_slow", "percent slow")
monitor("percent_medium", "percent medium")
monitor("avg_speed", "average speed")
monitor("avg_energy", "average energy")
monitor("total_kinetic_energy", "total KE")
button("setup")
button("go", forever=True)

max_tick_delta = 0.1073
tick_delta = max_tick_delta
box_edge = 0
init_avg_speed = 0.0
init_avg_energy = 0.0
avg_speed = 0.0
avg_energy = 0.0
fast = 0
medium = 0
slow = 0
percent_fast = 0.0
percent_medium = 0.0
percent_slow = 0.0

particles = create_breed("particles", "particle")


def setup():
    global box_edge, init_avg_speed, init_avg_energy
    clear_all()
    set_default_shape(particles, "circle")
    box_edge = round(max_pxcor() * box_size / 100)
    make_box()
    make_particles()
    update_variables()
    init_avg_speed = avg_speed
    init_avg_energy = avg_energy
    reset_ticks()


def make_box():
    for p in ask(patches):
        on_vertical_wall = abs(p.pxcor) == box_edge and abs(p.pycor) <= box_edge
        on_horizontal_wall = abs(p.pycor) == box_edge and abs(p.pxcor) <= box_edge
        if on_vertical_wall or on_horizontal_wall:
            p.pcolor = yellow


def make_particles():
    for p in particles.create(int(number_of_particles)):
        setup_particle(p)
        random_position(p)
        recolor(p)
    calculate_tick_delta()


def setup_particle(p):  # particle procedure
    p.speed = init_particle_speed
    p.mass = particle_mass
    p.energy = 0.5 * p.mass * p.speed * p.speed
    p.last_collision = None


def random_position(p):  # particle procedure
    p.xcor = (1 - box_edge) + random_float((2 * box_edge) - 2)
    p.ycor = (1 - box_edge) + random_float((2 * box_edge) - 2)


def update_variables():
    global fast, medium, slow, percent_fast, percent_medium, percent_slow, avg_speed, avg_energy
    total = particles.count()
    medium = particles.where(color=green).count()
    slow = particles.where(color=blue).count()
    fast = particles.where(color=red).count()
    percent_medium = (medium / total) * 100
    percent_slow = (slow / total) * 100
    percent_fast = (fast / total) * 100
    avg_speed = mean(p.speed for p in particles)
    avg_energy = mean(p.energy for p in particles)


def go():
    for p in ask(particles):
        bounce(p)
    for p in ask(particles):
        move(p)
    if collide:
        for p in ask(particles):
            check_for_collision(p)

    ticks_before = ticks()
    tick_advance(tick_delta)
    if floor(ticks()) > floor(ticks_before):
        update_variables()
    calculate_tick_delta()


def calculate_tick_delta():
    global tick_delta
    speeds = [p.speed for p in particles if p.speed > 0]
    if speeds:
        tick_delta = min(1 / ceiling(max(speeds)), max_tick_delta)
    else:
        tick_delta = max_tick_delta


def bounce(p):  # particle procedure
    new_patch = p.patch_ahead(1)
    if new_patch is None or new_patch.pcolor != yellow:
        return
    if abs(new_patch.pxcor) == box_edge:  # hit the left or right wall
        p.heading = -p.heading
    if abs(new_patch.pycor) == box_edge:  # hit the top or bottom wall
        p.heading = 180 - p.heading


def move(p):  # particle procedure
    if p.patch_ahead(p.speed * tick_delta) is not p.patch_here():
        p.last_collision = None
    p.jump(p.speed * tick_delta)


def check_for_collision(p):  # particle procedure
    # Collisions only happen when exactly two particles share a patch --
    # see the real source's long comment on why this (rather than any
    # proximity-based rule) is what produces a realistic uniform
    # wavefront. Kept verbatim rather than re-derived.
    others_here = p.other(p.here(particles))
    if others_here.count() != 1:
        return
    candidate = None
    for o in others_here:
        if o.who < p.who and o.last_collision is not p:
            candidate = o
    if candidate is None:
        return
    if p.speed > 0 or candidate.speed > 0:
        collide_with(p, candidate)
        p.last_collision = candidate
        candidate.last_collision = p


def collide_with(p, other):  # particle procedure
    # THE HEART OF THE PARTICLE SIMULATION -- an elastic collision between
    # two point particles of possibly different mass, computed by rotating
    # into a frame along the (arbitrary, since particles are points) angle
    # theta between them, colliding the along-theta velocity components
    # only, and rotating back. See the real source's phase-by-phase
    # comments; behavior kept exact, not simplified.
    mass2 = other.mass
    speed2 = other.speed
    heading2 = other.heading

    theta = random_float(360)

    v1t = p.speed * cos(theta - p.heading)
    v1l = p.speed * sin(theta - p.heading)
    v2t = speed2 * cos(theta - heading2)
    v2l = speed2 * sin(theta - heading2)

    vcm = ((p.mass * v1t) + (mass2 * v2t)) / (p.mass + mass2)
    v1t = 2 * vcm - v1t
    v2t = 2 * vcm - v2t

    p.speed = (v1t**2 + v1l**2) ** 0.5
    p.energy = 0.5 * p.mass * p.speed**2
    if v1l != 0 or v1t != 0:
        p.heading = theta - atan(v1l, v1t)

    other.speed = (v2t**2 + v2l**2) ** 0.5
    other.energy = 0.5 * mass2 * other.speed**2
    if v2l != 0 or v2t != 0:
        other.heading = theta - atan(v2l, v2t)

    recolor(p)
    recolor(other)


def recolor(p):  # particle procedure
    # NetLogo source hardcodes 10 here (not init_particle_speed) -- these
    # thresholds are fixed display categories, not slider-relative, kept
    # exactly as the real model has it.
    if p.speed < 0.5 * 10:
        p.color = blue
    elif p.speed > 1.5 * 10:
        p.color = red
    else:
        p.color = green


def total_kinetic_energy():
    return sum(p.energy for p in particles)


def is_running():
    return True


# No state() here -- tick/width/height, every slider and switch, all six
# monitors, and the patches/turtles grids (walls by pcolor, particles by
# their own real speed-based color, both already exactly what
# auto_state()'s defaults produce) are all built automatically. See
# engine/netlogo.py's auto_state() and the note above it.
