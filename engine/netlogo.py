"""A from-scratch NetLogo-flavored Python runtime: free functions and
module-level ambient state (one shared `turtles`/`patches`/tick counter)
instead of explicit World/Turtle/Patch objects passed around through
`self` -- mirroring how real NetLogo has exactly one world, and any
procedure can touch it directly, with no class or instance in sight.

A model file (e.g. models/fire.py) does `from engine.netlogo import *` and
writes `setup()`/`go()` as free functions, the same shape as NetLogo's own
`to setup`/`to go` -- see models/fire.py for the worked example this was
built against (itself checked against the real
orig-src/NetLogo/models/Sample Models/Earth Science/Fire.nlogox).

Design choices made across a long back-and-forth, kept here as a summary
since none of them are obvious in isolation:
  - breed is a plain string attribute (`t.breed = "embers"`), not a
    subclass -- `set breed embers` is just an attribute set.
  - `turtles`/`patches` are live singleton objects (bare names, no
    parens); breed handles from create_breed() are the same shape.
  - `ask(agents)` returns a plain list (a frozen snapshot), used with
    `for`, not by handing it a callback -- matches what real NetLogo's
    `ask` guarantees (safe even if the loop kills/creates agents) without
    needing higher-order functions to explain it.
  - `.where(**kwargs)` only expresses equality (`patches.where(pcolor=green)`
    for `patches with [pcolor = green]`) -- no lambdas, but also no
    pretense of covering `<`/`>`/`or`; anything beyond equality is a plain
    `for`/`if` loop instead, which covers every case, simple or not.
  - `slider(name, default, ...)` registers widget metadata as a side
    effect (attached to the *calling model's own module*, not a shared
    list here, so multiple models using this runtime don't mix each
    other's widgets) and returns the plain default value, so the bound
    name (e.g. `density`) is always a real number, never a wrapper object.
"""

import copy
import itertools
import math
import random as _random
import sys

# --- colors --------------------------------------------------------------
# Real NetLogo represents color as a single float on a ~140-value color
# wheel (so `set color color - 0.3` gradually darkens whatever hue you're
# already on, and `scale-color <color> ...` reports a shade of any hue).
# Reimplementing the whole wheel as one general numbering scheme is more
# machinery than this port needs, so this is a deliberately small stand-in:
# named colors are fixed RGB tuples, plain arithmetic on `red` falls back
# to a shade-of-red interpolation (all Fire needs), and scale_color() below
# covers every other "shade of a named color" need generically via
# ScaledColor, without requiring a full color-wheel numbering underneath.
black = 0.0
green = 100.0
red = 15.0
white = -1.0
violet = 115.0
cyan = 85.0
sky = 95.0
blue = 105.0
yellow = 45.0
brown = 35.0

_NAMED_RGB = {
    black: (0, 0, 0),
    green: (0, 180, 0),
    white: (255, 255, 255),
    violet: (135, 55, 220),
    cyan: (0, 200, 200),
    sky: (100, 165, 235),
    blue: (50, 90, 220),
    yellow: (210, 210, 0),
    brown: (120, 80, 40),
}


class ScaledColor:
    """What scale_color() returns: a shade of a base color, from
    near-black to near-white, carrying its own base color + position so
    color_to_rgb() can resolve it directly -- unlike the red-only shading
    below (a bare number, `red - 3.5` etc.), this doesn't need to guess
    "shade of what?" from the number alone. Not itself a NetLogo
    primitive -- real NetLogo's scale-color reports a plain color-wheel
    number; this engine doesn't have a general color wheel to report a
    number *onto* (see the module note above), so it reports this small
    object instead, which every model use of scale-color (assigning it
    straight to `pcolor`/`color`, never arithmetic on it) works fine
    against."""

    __slots__ = ("base", "fraction")

    def __init__(self, base, fraction):
        self.base = base
        self.fraction = fraction  # 0.0 (near-black) .. 1.0 (near-white), 0.5 = pure base


def scale_color(base_color, number, low, high):
    """NetLogo's `scale-color <color> <number> <low> <high>`: a shade of
    `base_color`, from near-black (at `low`) to near-white (at `high`),
    scaled to where `number` falls between them -- `low` can be greater
    than `high` to reverse the direction, same as real NetLogo."""
    span = high - low
    fraction = 0.5 if span == 0 else (number - low) / span
    return ScaledColor(base_color, max(0.0, min(1.0, fraction)))


def _lerp_rgb(a, b, t):
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def color_to_rgb(color):
    """Not a NetLogo primitive -- this app's own rendering plumbing (its
    frontend needs real RGB, not a NetLogo color number). Public, unlike
    the other module-internal state below, because every model's state()
    needs it to build the color grid it hands to the frontend."""
    if isinstance(color, ScaledColor):
        # (220, 0, 0) matches the shade-of-red fallback below, in case a
        # model ever scale_color()s a base this engine hasn't named.
        base_rgb = _NAMED_RGB.get(color.base, (220, 0, 0))
        if color.fraction < 0.5:
            return _lerp_rgb((0, 0, 0), base_rgb, color.fraction * 2)
        return _lerp_rgb(base_rgb, (255, 255, 255), (color.fraction - 0.5) * 2)
    if color in _NAMED_RGB:
        return _NAMED_RGB[color]
    # Treat anything else as a shade of red: `red` (15) is pure/bright,
    # `red - 5` is as dark as this model ever asks for (effectively black).
    # Fire's the only model that still shades a color via bare arithmetic
    # (`color - 0.3`, `color < red - 3.5`) rather than scale_color() --
    # this fallback is what makes that arithmetic render sensibly.
    brightness = max(0.0, min(1.0, (color - (red - 5)) / 5))
    return (int(220 * brightness), 0, 0)


# --- world state (module-level, singleton -- there is exactly one world) -
_turtles = {}
_patches = {}
_who_counter = itertools.count()
_ticks = 0
_default_shapes = {}
_running = True

_min_pxcor = -16
_max_pxcor = 16
_min_pycor = -16
_max_pycor = 16
_wrap = False


def resize_world(new_min_pxcor, new_max_pxcor, new_min_pycor, new_max_pycor):
    """NetLogo's `resize-world`."""
    global _min_pxcor, _max_pxcor, _min_pycor, _max_pycor
    _min_pxcor, _max_pxcor = new_min_pxcor, new_max_pxcor
    _min_pycor, _max_pycor = new_min_pycor, new_max_pycor


def set_wrap(wrap):
    """Not itself a NetLogo primitive -- in real NetLogo, world wrapping is
    a Model Settings checkbox, not something a running model queries or
    sets. Fire's world doesn't wrap (its fire/ember turtles never move
    anyway); Flocking's does. `Turtle.forward()`/`distance_to()`/
    `towards()` all read this."""
    global _wrap
    _wrap = wrap


# Like ticks() (see below): min-pxcor/max-pxcor/min-pycor/max-pycor are
# plain numbers that can change (via resize_world()), and
# `from engine.netlogo import *` copies a *value* into the importing
# module at import time, not a live link back here -- a bare `min_pxcor`
# name in a model file would silently go stale the moment resize_world()
# ran. Only genuinely live objects (turtles, patches) can be bare names;
# anything that's really just a number needs the explicit call.
def min_pxcor():
    return _min_pxcor


def max_pxcor():
    return _max_pxcor


def min_pycor():
    return _min_pycor


def max_pycor():
    return _max_pycor


def patch_at(x, y):
    """NetLogo's `patch x y`: the patch at those exact coordinates (spelled
    patch_at, not patch, so it doesn't read like it's related to the
    `Patch` class -- it just looks one up). None if out of range."""
    return _patches.get((x, y))


def diffuse(attr_name, rate):
    """NetLogo's `diffuse <patch-var> <rate>`: each patch keeps `1 - rate`
    of its own value of the named patches-own variable and distributes
    `rate` evenly across its 8 neighbors. Spelled with the variable name as
    a string (`diffuse("chemical", 0.5)`) since Python has no equivalent of
    NetLogo's bare-variable-reference syntax for `diffuse chemical 0.5`.

    At a non-wrapping world's edge, a patch has fewer than 8 real
    neighbors; the share that would have gone to a missing neighbor is
    simply lost rather than kept or redistributed (matches this runtime's
    other edge-of-world conventions -- see _wrapped_delta above)."""
    old_values = {p: getattr(p, attr_name) for p in _patches.values()}
    for p in _patches.values():
        neighbor_sum = sum(old_values[n] for n in p.neighbors8())
        new_value = old_values[p] * (1 - rate) + neighbor_sum * (rate / 8)
        setattr(p, attr_name, new_value)


class Patch:
    def __init__(self, pxcor, pycor):
        self.pxcor = pxcor
        self.pycor = pycor
        self.pcolor = black

    def neighbors4(self):
        """NetLogo's `neighbors4`: the (up to 4) orthogonally-adjacent
        patches that exist -- fewer at a non-wrapping world's edge."""
        deltas = ((1, 0), (-1, 0), (0, 1), (0, -1))
        found = (_patches.get((self.pxcor + dx, self.pycor + dy)) for dx, dy in deltas)
        return AgentSet(p for p in found if p is not None)

    def neighbors8(self):
        """NetLogo's `neighbors` (8 neighbors, including diagonals)."""
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                p = _patches.get((self.pxcor + dx, self.pycor + dy))
                if p is not None:
                    found.append(p)
        return AgentSet(found)

    def distance_to_xy(self, x, y):
        """NetLogo's `distancexy`, used from a patch: distance from this
        patch's center to the point (x, y). Unlike Turtle.distance_to(),
        not wrap-aware -- no model built against this runtime yet places
        patches in a wrapping world and cares about patch-to-point
        distance, so it hasn't been needed."""
        return math.hypot(x - self.pxcor, y - self.pycor)

    def __repr__(self):
        return f"Patch({self.pxcor}, {self.pycor})"


def _wrap_coord(value, lo, hi):
    span = hi - lo + 1
    return ((value - (lo - 0.5)) % span) + (lo - 0.5)


def _wrapped_delta(dx, dy):
    """The shortest-path (dx, dy) between two points -- going the other
    way around the torus if that's shorter -- when the world wraps.
    Distance/direction between agents (distance_to, towards, in_radius)
    all need this; only the *span* of the world matters for a delta, not
    where it starts, unlike _wrap_coord() above for an absolute position."""
    if _wrap:
        w = _max_pxcor - _min_pxcor + 1
        h = _max_pycor - _min_pycor + 1
        dx = ((dx + w / 2) % w) - w / 2
        dy = ((dy + h / 2) % h) - h / 2
    return dx, dy


class Turtle:
    def __init__(self, xcor=0.0, ycor=0.0, breed="turtles"):
        self.who = next(_who_counter)
        self.xcor = xcor
        self.ycor = ycor
        # Real NetLogo's create-turtles/sprout/crt give every new turtle a
        # random heading by default (a model overrides it with `set
        # heading ...` if it wants something else) -- Fire never notices,
        # since its fire/ember turtles never move or render direction in a
        # way the model logic cares about, but Flocking's whole premise
        # depends on turtles starting genuinely disordered.
        self.heading = _random.uniform(0, 360)
        self.color = white
        self.breed = breed
        self.shape = _default_shapes.get(breed, _default_shapes.get("turtles", "default"))

    def patch_here(self):
        return _patches.get((round(self.xcor), round(self.ycor)))

    def _patch_at_heading(self, heading, distance):
        rad = math.radians(heading)
        x = round(self.xcor + distance * math.sin(rad))
        y = round(self.ycor + distance * math.cos(rad))
        return _patches.get((x, y))

    def patch_ahead(self, distance=1):
        """NetLogo's `patch-ahead`."""
        return self._patch_at_heading(self.heading, distance)

    def patch_right_and_ahead(self, angle, distance=1):
        """NetLogo's `patch-right-and-ahead`."""
        return self._patch_at_heading(self.heading + angle, distance)

    def patch_left_and_ahead(self, angle, distance=1):
        """NetLogo's `patch-left-and-ahead`."""
        return self._patch_at_heading(self.heading - angle, distance)

    def can_move(self, distance):
        """NetLogo's `can-move? <number>`: would moving forward by that
        distance keep this turtle inside the world? Always True if the
        world wraps."""
        if _wrap:
            return True
        rad = math.radians(self.heading)
        new_x = self.xcor + distance * math.sin(rad)
        new_y = self.ycor + distance * math.cos(rad)
        return (_min_pxcor - 0.5 <= new_x < _max_pxcor + 0.5) and (_min_pycor - 0.5 <= new_y < _max_pycor + 0.5)

    def forward(self, distance):
        rad = math.radians(self.heading)
        self.xcor += distance * math.sin(rad)
        self.ycor += distance * math.cos(rad)
        if _wrap:
            self.xcor = _wrap_coord(self.xcor, _min_pxcor, _max_pxcor)
            self.ycor = _wrap_coord(self.ycor, _min_pycor, _max_pycor)

    fd = forward
    jump = forward  # NetLogo's `jump` is `forward` under a different name

    def right(self, degrees):
        self.heading = (self.heading + degrees) % 360

    rt = right

    def left(self, degrees):
        self.heading = (self.heading - degrees) % 360

    lt = left

    @property
    def dx(self):
        """NetLogo's `dx`: sin(heading) -- how much xcor would change per
        one step forward."""
        return math.sin(math.radians(self.heading))

    @property
    def dy(self):
        """NetLogo's `dy`: cos(heading)."""
        return math.cos(math.radians(self.heading))

    def distance_to(self, other):
        """NetLogo's `distance <agent>`: Euclidean distance to another
        turtle, wrapping across the world's edges if it wraps."""
        dx, dy = _wrapped_delta(other.xcor - self.xcor, other.ycor - self.ycor)
        return math.hypot(dx, dy)

    def towards(self, other):
        """NetLogo's `towards <agent>`: the heading from this turtle to
        another (wrap-aware)."""
        dx, dy = _wrapped_delta(other.xcor - self.xcor, other.ycor - self.ycor)
        return math.degrees(math.atan2(dx, dy)) % 360

    def in_radius(self, agents, distance):
        """NetLogo's `<agentset> in-radius <number>`, called as
        `asker.in_radius(agentset, distance)` since Python has no implicit
        "distance from me" the way NetLogo's own turtle procedures do."""
        return AgentSet(a for a in agents if self.distance_to(a) <= distance)

    def other(self, agents):
        """NetLogo's `other <agentset>`: agents excluding this turtle."""
        return AgentSet(a for a in agents if a is not self)

    def here(self, agents):
        """NetLogo's `<breed>-here`, called as `t.here(agents)`: agents (this
        turtle included) standing on this turtle's own patch. Compose with
        `.other()` for NetLogo's `other <breed>-here`, e.g.
        `t.other(t.here(particles))`."""
        px, py = round(self.xcor), round(self.ycor)
        return AgentSet(a for a in agents if round(a.xcor) == px and round(a.ycor) == py)

    def nearest(self, agents):
        """NetLogo's `min-one-of <agentset> [distance myself]`, specialized
        to the one thing min-one-of is used for in this port (finding the
        closest agent) so no lambda/callback is needed -- for anything
        else min-one-of could minimize, a plain loop tracking a running
        best candidate works the same way this is implemented internally."""
        best = None
        best_dist = None
        for a in agents:
            d = self.distance_to(a)
            if best is None or d < best_dist:
                best, best_dist = a, d
        return best

    def die(self):
        _turtles.pop(self.who, None)

    def hatch(self, n=1):
        """NetLogo's `hatch <n>`: n new turtles that are exact copies of
        this one (same breed, position, and any custom attributes already
        set on it, e.g. `energy`) -- unlike Breed.create()/sprout(), which
        make fresh default turtles. Returns the new turtles directly (not
        via a callback) -- use a `for` loop to adjust them, same as
        Breed.sprout()/create()."""
        created = []
        for _ in range(n):
            clone = copy.copy(self)
            clone.who = next(_who_counter)
            _turtles[clone.who] = clone
            created.append(clone)
        return created

    def __repr__(self):
        return f"Turtle({self.who})"


class AgentSet:
    """A frozen snapshot -- what ask() and .where() both return -- safe to
    iterate even if the loop kills or creates agents partway through."""

    def __init__(self, agents):
        self._agents = list(agents)

    def __iter__(self):
        return iter(self._agents)

    def where(self, **conditions):
        """NetLogo's `with [ ... ]`, restricted to `attribute = value`
        checks. For anything else (comparators, `or`, a computed
        condition), use a plain `for`/`if` loop instead."""
        return AgentSet(
            a for a in self._agents if all(getattr(a, key) == value for key, value in conditions.items())
        )

    def count(self):
        return len(self._agents)

    def any(self):
        return bool(self._agents)


class LiveAgentSet:
    """Like AgentSet, but membership is computed fresh every time it's
    iterated instead of frozen at construction -- what lets bare names
    like `turtles`, `patches`, and breed handles always reflect who
    currently exists, the way NetLogo's own agentset variables do."""

    def __iter__(self):
        raise NotImplementedError

    def where(self, **conditions):
        return AgentSet(a for a in self if all(getattr(a, key) == value for key, value in conditions.items()))

    def count(self):
        return sum(1 for _ in self)

    def any(self):
        return any(True for _ in self)


class _AllTurtles(LiveAgentSet):
    def __iter__(self):
        return iter(_turtles.values())


class _AllPatches(LiveAgentSet):
    def __iter__(self):
        return iter(_patches.values())


turtles = _AllTurtles()
patches = _AllPatches()


class Breed(LiveAgentSet):
    def __init__(self, plural, singular):
        self.plural = plural
        self.singular = singular

    def __iter__(self):
        return (t for t in _turtles.values() if t.breed == self.plural)

    def sprout(self, patch, n=1):
        """NetLogo's `sprout-<breed> n`: n new turtles of this breed, born
        on `patch`. Returns the new turtles directly (not via a callback)
        -- use a `for` loop to set them up."""
        created = []
        for _ in range(n):
            t = Turtle(xcor=patch.pxcor, ycor=patch.pycor, breed=self.plural)
            _turtles[t.who] = t
            created.append(t)
        return created

    def create(self, n=1):
        """NetLogo's `create-<breed> n`: n new turtles of this breed, born
        at the origin."""
        created = []
        for _ in range(n):
            t = Turtle(breed=self.plural)
            _turtles[t.who] = t
            created.append(t)
        return created


def create_breed(plural, singular):
    """NetLogo's `breed [<plural> <singular>]`."""
    return Breed(plural, singular)


def create_turtles(n=1):
    """NetLogo's `create-turtles n`: n new plain turtles (breed
    "turtles"), each at the origin. Like Breed.create()/Breed.sprout(),
    returns them directly -- use a `for` loop to set them up, not a
    callback."""
    created = []
    for _ in range(n):
        t = Turtle()
        _turtles[t.who] = t
        created.append(t)
    return created


def random_xcor():
    """NetLogo's `random-xcor`: a uniform value anywhere in the world's
    width, including the half-patch margin at each edge."""
    return _min_pxcor - 0.5 + random_float(_max_pxcor - _min_pxcor + 1)


def random_ycor():
    """NetLogo's `random-ycor`."""
    return _min_pycor - 0.5 + random_float(_max_pycor - _min_pycor + 1)


def sin(degrees):
    """NetLogo's `sin`: unlike Python's math.sin, NetLogo's trig
    primitives take degrees, not radians."""
    return math.sin(math.radians(degrees))


def cos(degrees):
    """NetLogo's `cos` (degrees, see sin())."""
    return math.cos(math.radians(degrees))


def atan(dx, dy):
    """NetLogo's two-argument `atan dx dy`: the heading (0 = north,
    clockwise, degrees, wrapped to 0-360) of the vector (dx, dy)."""
    return math.degrees(math.atan2(dx, dy)) % 360


def subtract_headings(h1, h2):
    """NetLogo's `subtract-headings`: the signed short way around from
    heading h2 to heading h1, in (-180, 180]."""
    return (h1 - h2 + 540) % 360 - 180


def mean(values):
    """NetLogo's `mean`."""
    values = list(values)
    return sum(values) / len(values)


def ceiling(x):
    """NetLogo's `ceiling`."""
    return math.ceil(x)


def floor(x):
    """NetLogo's `floor`."""
    return math.floor(x)


def ask(agents):
    """NetLogo's `ask`: snapshots the (possibly live) agentset so the
    for-loop over it is safe even if the loop kills or creates agents
    partway through. Used with `for`:
        for p in ask(patches):
            p.pcolor = green
    """
    return list(agents)


def set_default_shape(agents_or_breed, shape_name):
    """NetLogo's `set-default-shape`. Registers the shape newly-created
    turtles get from now on if nothing else sets one -- it does not
    retroactively change any turtle that already exists."""
    key = agents_or_breed.plural if isinstance(agents_or_breed, Breed) else "turtles"
    _default_shapes[key] = shape_name


def random_float(n):
    """NetLogo's `random-float n`: a uniform value in [0, n)."""
    return _random.uniform(0, n)


def random(n):
    """NetLogo's `random n`: a uniform random *integer* in [0, n) -- unlike
    random_float(), which reports a real number."""
    return _random.randrange(int(n))


def one_of(items):
    """NetLogo's `one-of`: a uniformly random element of a list/agentset, or
    None (NetLogo's `nobody`) if it's empty."""
    items = list(items)
    return _random.choice(items) if items else None


def tick():
    """NetLogo's `tick` (command): advance the counter by one."""
    global _ticks
    _ticks += 1


def tick_advance(delta):
    """NetLogo's `tick-advance`: like tick(), but by an arbitrary --
    typically fractional -- amount instead of always exactly 1. Used by
    models with an adaptive timestep (see models/gas_lab.py) instead of
    tick()."""
    global _ticks
    _ticks += delta


def ticks():
    """NetLogo's `ticks` (reporter): the current count. Unlike `turtles`/
    `patches`, this can't be a bare live object -- a tick count is a plain
    number, and numbers can't silently update themselves the way an
    object's __iter__ can, so this needs the same explicit-call shape any
    other NetLogo reporter would (`ticks`, no args, but still a call)."""
    return _ticks


def reset_ticks():
    global _ticks
    _ticks = 0


def stop():
    """NetLogo's `stop`: marks the current `go` as finished. In this port
    a model's own go() is expected to `return` right after calling stop()
    -- Python has no way to unwind an arbitrary caller's stack the way
    NetLogo's `stop` does, so the return is still the model author's job."""
    global _running
    _running = False


def clear_all():
    """NetLogo's `clear-all`: wipes every turtle, rebuilds the patch grid
    at the world's current size (see resize_world()), and clears every
    plot pen's history (real NetLogo's `clear-all` includes
    `clear-all-plots`)."""
    global _turtles, _patches, _ticks, _running
    _turtles = {}
    _patches = {
        (x, y): Patch(x, y) for x in range(_min_pxcor, _max_pxcor + 1) for y in range(_min_pycor, _max_pycor + 1)
    }
    _ticks = 0
    _running = True
    _plot_pens.clear()


def _register_widget(fields):
    """Shared by slider()/monitor()/button() below: attaches a widget's
    metadata to the *calling model's own module* (so multiple models
    sharing this runtime don't mix each other's widgets into one list).
    `depth` counts frames from here: _register_widget -> slider() -> the
    model file, so the model file's globals are two frames up."""
    caller_globals = sys._getframe(2).f_globals
    widgets = caller_globals.setdefault("__widgets__", [])
    widgets.append(fields)


def slider(name, default: float, min: float = 0, max: float = 100, step: float = 1, **extra):
    """NetLogo's slider widget: `<slider variable="density" default="57.0"
    min="0.0" max="99.0" step="1.0" ...>`. Returns the plain default value
    -- `density = slider("density", default=57, ...)` binds `density` to a
    real number, not a wrapper object, so ordinary arithmetic/comparison on
    it just works."""
    _register_widget(
        {
            "type": "slider",
            "name": name,
            "label": extra.pop("label", name),
            "default": default,
            "min": min,
            "max": max,
            "step": step,
            **extra,
        }
    )
    return default


def switch(name, default=True, **extra):
    """NetLogo's switch widget: `<switch variable="collide?" on="true">`.
    Same shape as slider() -- registers the widget and returns the plain
    default value, so `collide = switch("collide?", default=True)` binds a
    real bool, not a wrapper object. The model's own `if collide:` reads
    the module-level value directly, same as any other slider-backed
    variable -- see server/main.py's setattr()-based slider application,
    which works the same way for a bool as for a number."""
    _register_widget(
        {
            "type": "switch",
            "name": name,
            "label": extra.pop("label", name),
            "default": default,
            **extra,
        }
    )
    return default


def chooser(name, options, default=None, **extra):
    """NetLogo's chooser widget: `<chooser variable="model-version"
    current="0"><choice value="sheep-wolves"/>...</chooser>` (`current` is
    an index into the choices). Here `default` is the actual option value
    instead of an index -- defaulting to the first option, same spirit as
    slider()'s `default` being a real number rather than a separate index
    into some range. Returns the default value, like slider()/switch()."""
    if default is None:
        default = options[0]
    _register_widget(
        {
            "type": "chooser",
            "name": name,
            "label": extra.pop("label", name),
            "options": list(options),
            "default": default,
        }
    )
    return default


def monitor(key, label=None, **extra):
    """NetLogo's monitor widget: `<monitor display="percent burned">
    (burned-trees / initial-trees) * 100</monitor>`. Real NetLogo monitors
    hold an arbitrary reporter expression; here `key` just names the
    state()-dict key the frontend already reads to display it (so the
    reporter itself is whatever function computes that key, e.g.
    percent_burned() feeding state()'s "percent_burned" entry) -- nothing
    to return, this is a pure declaration, same as slider()."""
    _register_widget({"type": "monitor", "key": key, "label": label or key})


def button(label, forever=False, **extra):
    """NetLogo's button widget: `<button forever="true">go</button>`. Not
    consumed by this app's frontend yet -- it already has fixed setup/go
    buttons that happen to match every current model exactly -- but models
    still declare their buttons here so they're self-describing, the same
    as slider()/monitor(), ready for whenever a model needs one that
    isn't just setup/go."""
    _register_widget({"type": "button", "label": label, "forever": forever, **extra})


# --- plots -----------------------------------------------------------------
# Real NetLogo plots track an ambient "current plot"/"current pen" (set via
# set-current-plot/set-current-plot-pen) that a pen's own `update` code then
# implicitly plots into. This runtime has no hidden ambient state anywhere
# else (see the module docstring), so plot() below names its pen directly
# instead -- a model calls `plot("sheep", sheep.count())` from its own go(),
# the same way it would call any other function.
_plot_pens = {}  # pen name -> list of (x, y) points, oldest first


def plot_widget(title, x_label="", y_label="", pens=()):
    """NetLogo's plot widget: `<plot display="populations" xAxis="time"
    yAxis="pop."><pen display="sheep" color="...">...`. `pens` is a list of
    (name, color) pairs -- color is a plain CSS color string for this app's
    own frontend to draw with, not a NetLogo color number. Pure
    declaration, like button()."""
    _register_widget(
        {
            "type": "plot",
            "title": title,
            "x_label": x_label,
            "y_label": y_label,
            "pens": [{"name": name, "color": color} for name, color in pens],
        }
    )


def plot(pen, value):
    """NetLogo's `plot <value>`, called directly with which pen (see the
    note above). x auto-increments by 1 each time *this pen* is plotted --
    0, 1, 2, ... -- matching a NetLogo pen's default interval of 1. If a
    pen isn't plotted every tick (e.g. a pen only used in one mode of a
    model), its x values count *plots*, not ticks, exactly as in real
    NetLogo."""
    history = _plot_pens.setdefault(pen, [])
    history.append((len(history), value))


def plotxy(pen, x, y):
    """NetLogo's `plotxy <x> <y>`: like plot(), but with an explicit x
    instead of auto-incrementing -- use this when a pen's x should track
    something specific (e.g. `plotxy ticks ...`, so the pen's x is always
    the real tick count) rather than "how many times has this pen been
    plotted." See models/ants.py's food-per-pile plot."""
    history = _plot_pens.setdefault(pen, [])
    history.append((x, y))


def plot_data():
    """Every pen's current (x, y) points so far -- what a model's state()
    hands to the frontend to draw, e.g. {"sheep": [[0, 100], [1, 98], ...]}."""
    return {pen: [list(point) for point in points] for pen, points in _plot_pens.items()}


# --- state() -- turning the world into what the frontend draws -------------
# Nothing below here is a NetLogo primitive -- NetLogo's own IDE never makes
# a model author write anything like this, it just inspects turtles/patches/
# plots directly to render them. state() only exists because this app needs
# one JSON snapshot per tick (server/main.py's HTTP responses, or the WASM
# worker's postMessage payloads) -- so auto_state() below builds that
# snapshot automatically from what a model has already declared, and most
# models don't need to write a state() function at all (server/main.py and
# static/pyodide-worker.js's _ModuleAdapter both call auto_state() directly
# for any model that doesn't define its own). A model only writes a short
# state() when it wants something auto_state() can't guess -- see
# models/ants.py's chemical-trail patch coloring, or models/fire.py
# suppressing turtles it has but doesn't want drawn.


def _default_patch_color(p):
    return color_to_rgb(p.pcolor)


def patches_grid(color_fn=None):
    """The current patch grid as a 2D list of [r, g, b] rows (row 0 = the
    world's north edge, matching drawPatches()'s convention in
    static/app.js) -- what state() hands the frontend as "colors".
    `color_fn`, if given, is a plain function taking a patch and returning
    its [r, g, b] -- the default colors by `pcolor`
    (color_to_rgb(p.pcolor)); pass a different one for a model that colors
    patches by something else (see models/ants.py's chemical-trail
    gradient)."""
    color_fn = color_fn or _default_patch_color
    return [
        [list(color_fn(_patches[(x, y)])) for x in range(_min_pxcor, _max_pxcor + 1)]
        for y in range(_max_pycor, _min_pycor - 1, -1)
    ]


def _default_turtle_color(t):
    return list(color_to_rgb(t.color))


def turtles_grid(color_fn=None):
    """The current turtles as a list of [xcor, ycor, heading, extra] rows
    -- what state() hands the frontend as "turtles". `color_fn`, if given,
    is a plain function taking a turtle and returning its `extra` value --
    an [r, g, b] color, or any other value drawTurtles() (static/app.js)
    understands, e.g. a carrying-food flag -- the default is the turtle's
    real color (color_to_rgb(t.color))."""
    color_fn = color_fn or _default_turtle_color
    return [[t.xcor, t.ycor, t.heading, color_fn(t)] for t in turtles]


def _resolve_widget_value(ns, name):
    """Shared by auto_state(): a slider/switch/chooser/monitor's current
    value is whatever `name` points to in the model's own namespace,
    called if it's a function -- so a monitor can name either a plain
    stored value (`food_in_nest`) or a zero-argument reporter
    (`percent_burned`), with no other ceremony. This is also why a
    monitor whose value needs computing from an agentset (e.g. `count
    sheep`) needs its own small named function (`sheep_count()`) rather
    than pointing straight at a breed handle -- see models/wolf_sheep.py."""
    value = ns[name]
    return value() if callable(value) else value


def auto_state(module=None, patches=True, turtles=True, patch_color=None, turtle_color=None, extra=None):
    """Builds a model's entire state() dict automatically -- the one JSON
    shape this app's frontend expects every tick -- from its already-
    declared widgets (slider()/switch()/chooser()/monitor()/plot_widget())
    plus its live patches/turtles. See the note above this function for
    when a model needs to call this itself instead of skipping state()
    entirely, e.g.:
        def state():
            return auto_state(turtles=False)                 # Fire
            return auto_state(patch_color=my_patch_color)     # Ants

    `module`: the model's own module (or, from the WASM engine, its
    exec() namespace dict) -- only needed when calling this from outside
    the model itself (server/main.py, static/pyodide-worker.js's
    _ModuleAdapter); a model calling auto_state() from within its own
    state() doesn't pass this, since it's found automatically from the
    caller's own globals.
    `patches`/`turtles`: whether to include the "colors"/"turtles" keys.
    `patch_color`/`turtle_color`: see patches_grid()/turtles_grid().
    `extra`: a plain dict of any further state() keys a model computes
    itself, merged in last (so it can override anything above too)."""
    if module is None:
        ns = sys._getframe(1).f_globals
    elif isinstance(module, dict):
        ns = module
    else:
        ns = module.__dict__

    result = {
        "tick": ticks(),
        "width": _max_pxcor - _min_pxcor + 1,
        "height": _max_pycor - _min_pycor + 1,
    }

    for widget in ns.get("__widgets__", []):
        if widget["type"] in ("slider", "switch", "chooser"):
            result[widget["name"]] = _resolve_widget_value(ns, widget["name"])
        elif widget["type"] == "monitor":
            result[widget["key"]] = _resolve_widget_value(ns, widget["key"])
        elif widget["type"] == "plot":
            result["plot_data"] = plot_data()

    if patches:
        result["colors"] = patches_grid(patch_color)
    if turtles:
        result["turtles"] = turtles_grid(turtle_color)

    if extra:
        result.update(extra)

    return result
