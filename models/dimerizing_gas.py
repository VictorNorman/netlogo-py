"""Dimerizing Gas: a 2D hard-sphere gas with one addition layered on top:
the reversible reaction 2 A <=> B. This is an original model for this
app, not a NetLogo Sample Models port -- inspired by the request that led
to it (a professor wanting a dynamic-equilibrium demo for their course,
citing https://www.falstad.com/gas/gas.html -- "everything about this is
great, just want to add a dimerization reaction to the mix") -- so
there's no real .nlogox source to check it against line by line.

The first model in this app to declare more than one plot_widget() -- a
population-history line plot and a live particle-speed histogram.

Reaction mechanics -- how a collision becomes a chemical event:
  - Two A particles that share a patch (see check_for_collision()) react
    with probability `dimerization_chance` instead of just bouncing off
    each other. combine() replaces them with one B at their midpoint,
    momentum-conserving (B's velocity is the mass-weighted average of the
    two A velocities -- an exact center-of-mass calculation, not a
    shortcut).
  - A B particle that shares a patch with anything (A, B, or a wall)
    reacts with probability `dissociation_chance` instead of colliding/
    bouncing normally. dissociate() replaces it with two A particles at
    its position, splitting its momentum symmetrically about its own
    center-of-mass velocity plus a random-direction "kick" (see below).

Energy bookkeeping deliberately does NOT conserve total kinetic energy
exactly, on purpose:
  - combine() conserves momentum exactly but NOT translational kinetic
    energy -- forming a bond releases the two A's *relative* KE around
    their shared center of mass (real dimerization is exothermic; that
    energy is spent making the bond, not "lost" in some unphysical
    accounting sense).
  - dissociate() conserves momentum too, and adds back translational KE
    via a random-direction relative-velocity kick sized off the current
    `temperature` slider (thermal_speed() with the fragment pair's
    reduced mass) -- i.e. bond-breaking draws its energy from an ambient
    thermal bath at that temperature, not from whatever the original B
    happened to store.
  This makes the system quasi-isothermal (coupled to a bath at
  `temperature`) rather than perfectly adiabatic/energy-closed -- which is
  actually the more accurate physical picture for what "B/A^2 should be
  constant at equilibrium" (the mass-action law, Kc) describes: a
  constant-temperature reaction vessel, not an insulated one. Ordinary
  elastic collisions (collide_with()) remain exactly momentum- AND
  energy-conserving classical mechanics throughout -- only the reactive
  events touch the thermal bath. Mass is exactly conserved always:
  count_a + 2 * count_b never changes (see total_a_equivalent below),
  regardless of temperature bookkeeping.

Units: temperature and particle-mass are labeled K and amu because that's
the intuitive way to think about them (raise the temperature slider, the
gas gets hotter), but this is NOT a dimensionally-real physics model --
there's no Boltzmann constant anywhere, thermal_speed() below just
defines temperature AS average kinetic energy per particle directly
(equipartition with k_B = 1, the standard "reduced units" convention in
molecular simulation, same idea as Lennard-Jones reduced units). So "500
K" doesn't correspond to a literal 500 kelvin the way "10 amu" doesn't
correspond to a literal 10 atomic mass units -- they're consistent with
each other and with speed/energy, just not calibrated against real-world
SI constants. Box dimensions (box_size) are a legitimate, dimensionless
"%" of the world's half-width.
"""

INFO = """
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
"""

from engine.netlogo import *

resize_world(-40, 40, -40, 40)
set_wrap(False)

KEQ_WINDOW_SIZE = 20  # see keq_estimate's rolling-average note in update_variables()

initial_a = slider("initial_a", default=200, min=0, max=500, step=2, label="initial number of A particles")
initial_b = slider("initial_b", default=0, min=0, max=250, step=1, label="initial number of B particles")
particle_mass = slider("particle_mass", default=2, min=1, max=10, step=1, label="particle-mass (A)", units="amu")
# max raised from 40 -> 500 K; see the module docstring's "Units" note --
# this is a reduced-units temperature (average KE per particle, k_B = 1),
# not literally calibrated to real kelvin.
temperature = slider("temperature", default=8, min=1, max=500, step=1, label="temperature", units="K")
dimerization_chance = slider(
    "dimerization_chance", default=40, min=0, max=100, step=1, label="Dimerization Probability", units="%"
)
dissociation_chance = slider(
    "dissociation_chance", default=4, min=0, max=100, step=1, label="Dissociation Probability", units="%"
)
box_size = slider("box_size", default=95, min=5, max=100, step=1, label="box size", units="%")
monitor("count_a", "# of A")
monitor("count_b", "# of B")
monitor("total_a_equivalent", "A + 2xB (conserved)")
monitor("measured_temperature", "temperature (measured)")
monitor("keq_estimate", f"Kc x10^4 (B / A^2, {KEQ_WINDOW_SIZE}-tick avg)")
plot_widget(
    "Populations",
    x_label="time (ticks)",
    y_label="count",
    pens=[("A", "#3a7ca5", "line"), ("B", "#c1444c", "line")],
)
plot_widget(
    "Speed Distribution",
    x_label="speed (relative units)",
    y_label="# molecules",
    pens=[("A speed", "rgba(58, 124, 165, 0.6)", "bar"), ("B speed", "rgba(193, 68, 76, 0.6)", "bar")],
)
button("setup")
button("go", forever=True)

max_tick_delta = 0.1073
tick_delta = max_tick_delta
box_edge = 0
count_a = 0
count_b = 0
total_a_equivalent = 0
measured_temperature = 0.0
keq_estimate = 0.0
_keq_window = []  # trailing Kc snapshots -- see update_variables()

a_particles = create_breed("a_particles", "a_particle")
b_particles = create_breed("b_particles", "b_particle")


def setup():
    global box_edge
    clear_all()
    _keq_window.clear()
    set_default_shape(a_particles, "circle")
    set_default_shape(b_particles, "circle")
    box_edge = round(max_pxcor() * box_size / 100)
    make_box()
    make_particles(a_particles, int(initial_a), particle_mass)
    make_particles(b_particles, int(initial_b), particle_mass * 2)
    calculate_tick_delta()
    update_variables()
    reset_ticks()


def make_box():
    for p in ask(patches):
        on_vertical_wall = abs(p.pxcor) == box_edge and abs(p.pycor) <= box_edge
        on_horizontal_wall = abs(p.pycor) == box_edge and abs(p.pxcor) <= box_edge
        if on_vertical_wall or on_horizontal_wall:
            p.pcolor = yellow


def make_particles(breed, n, mass):
    for p in breed.create(n):
        setup_particle(p, mass)
        random_position(p)
        recolor(p)


def setup_particle(p, mass):  # particle procedure
    p.mass = mass
    p.speed = thermal_speed(mass)
    p.energy = 0.5 * p.mass * p.speed * p.speed
    p.last_collision = None


def random_position(p):  # particle procedure
    p.xcor = (1 - box_edge) + random_float((2 * box_edge) - 2)
    p.ycor = (1 - box_edge) + random_float((2 * box_edge) - 2)


def thermal_speed(mass):
    # The speed at which a particle of this mass has kinetic energy exactly
    # equal to `temperature` -- the equipartition-theorem statement that
    # "temperature" is average KE per particle, independent of mass, which
    # is also literally how the temperature slider description reads.
    return (2 * temperature / mass) ** 0.5


def update_variables():
    global count_a, count_b, total_a_equivalent, measured_temperature, keq_estimate
    count_a = a_particles.count()
    count_b = b_particles.count()
    total_a_equivalent = count_a + 2 * count_b
    all_particles = list(turtles)
    measured_temperature = mean(0.5 * t.mass * t.speed * t.speed for t in all_particles) if all_particles else 0.0
    # keq_estimate is a trailing KEQ_WINDOW_SIZE-tick average, not an
    # instantaneous snapshot -- count_a/count_b are small integers that
    # fluctuate tick to tick even once the system has settled into
    # equilibrium, so the raw ratio jitters a lot; averaging over a short
    # recent window is what actually makes "Kc converges to a constant"
    # visible on the monitor instead of just noise. Ticks where count_a is
    # 0 (undefined ratio) are skipped rather than counted as 0.
    if count_a > 0:
        _keq_window.append(count_b / (count_a * count_a))
        del _keq_window[: -KEQ_WINDOW_SIZE]  # keep at most the most recent KEQ_WINDOW_SIZE entries
    keq_estimate = (mean(_keq_window) * 10000) if _keq_window else 0.0
    plot("A", count_a)
    plot("B", count_b)
    histogram("A speed", [t.speed for t in a_particles], bin_width=0.5)
    histogram("B speed", [t.speed for t in b_particles], bin_width=0.5)


def go():
    for p in ask(turtles):
        bounce(p)
    for p in ask(turtles):
        move(p)
    for p in ask(turtles):
        check_for_collision(p)

    ticks_before = ticks()
    tick_advance(tick_delta)
    if floor(ticks()) > floor(ticks_before):
        update_variables()
    calculate_tick_delta()


def calculate_tick_delta():
    global tick_delta
    speeds = [t.speed for t in turtles if t.speed > 0]
    if speeds:
        tick_delta = min(1 / ceiling(max(speeds)), max_tick_delta)
    else:
        tick_delta = max_tick_delta


def bounce(p):  # particle procedure
    # Checks the exact upcoming position, not a rounded 1-unit lookahead
    # -- the wall is only 1 patch wide, so rounding could occasionally
    # miss it at high speed and let a particle sail straight through.
    dx, dy = _components(p.speed * tick_delta, p.heading)
    hit_x = abs(p.xcor + dx) >= box_edge - 0.5  # about to enter the left/right wall
    hit_y = abs(p.ycor + dy) >= box_edge - 0.5  # about to enter the top/bottom wall
    if not (hit_x or hit_y):
        return
    if p.breed == b_particles.plural and random_float(100) < dissociation_chance:
        dissociate(p)
        return
    if hit_x:
        p.heading = -p.heading
    if hit_y:
        p.heading = 180 - p.heading


def move(p):  # particle procedure
    if p.patch_ahead(p.speed * tick_delta) is not p.patch_here():
        p.last_collision = None
    p.jump(p.speed * tick_delta)


def check_for_collision(p):  # particle procedure
    # Only reacts/collides when exactly one other particle shares this
    # patch, generalized to whichever breed(s) the two particles are.
    others_here = p.other(p.here(turtles))
    if others_here.count() != 1:
        return
    candidate = None
    for o in others_here:
        if o.who < p.who and o.last_collision is not p:
            candidate = o
    if candidate is None:
        return
    if p.speed <= 0 and candidate.speed <= 0:
        return

    p_is_a = p.breed == a_particles.plural
    candidate_is_a = candidate.breed == a_particles.plural

    if p_is_a and candidate_is_a:
        if random_float(100) < dimerization_chance:
            combine(p, candidate)
            return
    else:
        # At least one of the pair is a B -- each B independently gets a
        # chance to fall apart (so a rare B-meets-B collision can dissociate
        # either, both, or neither).
        reacted = False
        if not p_is_a and random_float(100) < dissociation_chance:
            dissociate(p)
            reacted = True
        if not candidate_is_a and random_float(100) < dissociation_chance:
            dissociate(candidate)
            reacted = True
        if reacted:
            return

    collide_with(p, candidate)
    p.last_collision = candidate
    candidate.last_collision = p


def collide_with(p, other):  # particle procedure
    # THE HEART OF THE PARTICLE SIMULATION: an exact elastic collision
    # between two point particles of possibly different mass. Doesn't end
    # with a recolor() -- here color encodes species (A vs B), not speed,
    # and an elastic collision never changes a particle's species.
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


def _components(speed, heading):
    """A velocity's (dx, dy) -- same sin/cos convention as Turtle.dx/dy."""
    return speed * sin(heading), speed * cos(heading)


def _speed_heading(dx, dy):
    """The inverse of _components(): a (dx, dy) velocity back to
    (speed, heading)."""
    speed = (dx * dx + dy * dy) ** 0.5
    heading = atan(dx, dy) if (dx != 0 or dy != 0) else 0
    return speed, heading


def combine(p, other):  # 2A -> B: an exothermic bond forming
    dx1, dy1 = _components(p.speed, p.heading)
    dx2, dy2 = _components(other.speed, other.heading)
    mass_b = p.mass + other.mass
    # The center-of-mass velocity -- conserves momentum exactly. The two
    # A's *relative* kinetic energy around this shared velocity isn't
    # carried forward (see the module docstring's "energy bookkeeping").
    com_dx = (p.mass * dx1 + other.mass * dx2) / mass_b
    com_dy = (p.mass * dy1 + other.mass * dy2) / mass_b
    speed_b, heading_b = _speed_heading(com_dx, com_dy)
    x = (p.xcor + other.xcor) / 2
    y = (p.ycor + other.ycor) / 2
    p.die()
    other.die()
    for child in b_particles.create(1):
        child.xcor = x
        child.ycor = y
        child.mass = mass_b
        child.speed = speed_b
        child.heading = heading_b
        child.energy = 0.5 * mass_b * speed_b * speed_b
        child.last_collision = None
        recolor(child)


def dissociate(b):  # B -> 2A: bond breaking, drawing energy from the bath
    child_mass = b.mass / 2
    reduced_mass = child_mass / 2  # two equal-mass fragments
    kick_speed = thermal_speed(reduced_mass)  # relative speed between the two fragments
    theta = random_float(360)
    com_dx, com_dy = _components(b.speed, b.heading)
    kick_dx, kick_dy = _components(kick_speed / 2, theta)
    x, y = b.xcor, b.ycor
    b.die()
    for sign in (1, -1):
        speed, heading = _speed_heading(com_dx + sign * kick_dx, com_dy + sign * kick_dy)
        for child in a_particles.create(1):
            child.xcor = x
            child.ycor = y
            child.mass = child_mass
            child.speed = speed
            child.heading = heading
            child.energy = 0.5 * child_mass * speed * speed
            child.last_collision = None
            recolor(child)


def recolor(p):  # particle procedure -- color/size encode species, not speed
    if p.breed == a_particles.plural:
        p.color = sky
        p.size = 1.0
    else:
        p.color = red
        p.size = 1.5


def is_running():
    return True


# No state() here -- tick/width/height, every slider, both monitors' worth
# of plot data, and the patches/turtles grids (walls by pcolor, particles
# colored by species via recolor()) are all built automatically. See
# engine/netlogo.py's auto_state() and the note above it.
