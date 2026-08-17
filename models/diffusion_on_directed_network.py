"""Python port of NetLogo's classic "Diffusion on a Directed Network"
model -- see Sample Models/Networks/Diffusion on a Directed Network.nlogox
(from the full NetLogo distribution, not bundled in this repo) for the
real source this was checked against line by line. Each tick, every node
keeps a share of its own "value" and divides the rest evenly among its
outgoing links -- unlike diffuse() (patches, always symmetric), a
directed link can carry value one way without any coming back.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. The first
model here to use directed links and more than one link breed --
LinkBreed/directed_link_breed(), Patch.turtles_here()/.sprout(),
Link.hide_link()/.show_link(), and Turtle.size (all added to
engine/netlogo.py for this port). "Rewiring" a link (moving it from the
active-links breed to inactive-links or back) is just reassigning its
`.breed`, same as any other attribute -- no special primitive needed.

Deliberate deviations from the real source:
  - `set-default-shape turtles "circle"` / `... links "small-arrow-link"`
    aren't ported -- this app's turtle/link renderer always draws a fixed
    triangle/line-with-arrowhead regardless of shape, the same
    simplification several other models already document.
  - The REWIRE-A-LINK / KEEP-REWIRING buttons are real, working functions
    here (rewire_a_link(), is_rewiring) but aren't wired to any UI control
    -- this app only has fixed Setup/Go buttons today (see button()'s own
    docstring), same as every other model's non-setup/go buttons.
  - The real model's histogram plot picks its bar count as
    ceiling(sqrt(count turtles)) and its bin width from that -- val_histogram()
    below reproduces that same idea (not NetLogo's exact internal
    bar-layout algorithm), matching the approach already documented in
    models/preferential_attachment.py.
"""

import math

from engine.netlogo import *

resize_world(-10, 10, -10, 10)
set_wrap(False)

grid_size = slider("grid_size", default=9, min=3, max=19, step=2, label="grid-size")
link_chance = slider("link_chance", default=50, min=0, max=100, step=1, label="link-chance", units="%")
diffusion_rate = slider("diffusion_rate", default=10, min=0, max=100, step=1, label="diffusion-rate", units="%")
monitor("total_val", "total value")
monitor("max_val", "max value")
monitor("active_link_count", "active links")
plot_widget("Histogram", x_label="val", y_label="# of nodes", pens=[("val", "#000000", "bar")])
button("setup")
button("go", forever=True)
button("rewire-a-link")
button("keep-rewiring", forever=True)

active_links = directed_link_breed("active_links", "active_link")
inactive_links = directed_link_breed("inactive_links", "inactive_link")

total_val = 0.0
max_val = 0.0
max_flow = 0.0
mean_flow = 0.0


def setup():
    clear_all()
    half = grid_size / 2
    for p in ask(patches):
        if abs(p.pxcor) < half and abs(p.pycor) < half:
            for t in p.sprout(1):
                t.color = blue

    # a directed network where each node has a link-chance% chance of an
    # established link to each of its (up to 4) orthogonal neighbors
    for t in ask(turtles):
        t.val = 1
        neighbor_nodes = [n for np in t.patch_here().neighbors4() for n in np.turtles_here()]
        for link in active_links.create_to(t, neighbor_nodes):
            link.current_flow = 0
            if random_float(100) > link_chance:
                link.breed = inactive_links.plural
                link.hide_link()

    # spread the nodes out to fill the whole view, whatever grid_size is
    x_scale = (max_pxcor() - 1) / (grid_size / 2 - 0.5)
    y_scale = (max_pycor() - 1) / (grid_size / 2 - 0.5)
    for t in ask(turtles):
        t.xcor *= x_scale
        t.ycor *= y_scale

    update_globals()
    update_visuals()
    val_histogram()
    reset_ticks()


def go():
    for t in ask(turtles):
        t.new_val = 0
    for t in ask(turtles):
        recipients = active_links.out_neighbors(t)
        if recipients.any():
            val_to_keep = t.val * (1 - diffusion_rate / 100)
            # we keep some amount of our value from one tick to the next
            t.new_val += val_to_keep
            # what we don't keep, we divide evenly among our out-link-neighbors
            val_increment = (t.val - val_to_keep) / recipients.count()
            for r in ask(recipients):
                r.new_val += val_increment
                active_links.in_from(r, t).current_flow = val_increment
        else:
            t.new_val += t.val
    for t in ask(turtles):
        t.val = t.new_val

    if is_rewiring:
        rewire_a_link()

    update_globals()
    update_visuals()
    val_histogram()
    tick()


def rewire_a_link():
    if active_links.any():
        old_link = one_of(active_links)
        old_link.breed = inactive_links.plural
        old_link.hide_link()
        new_link = one_of(inactive_links)
        new_link.breed = active_links.plural
        new_link.show_link()


is_rewiring = False  # set by the (not-yet-UI-wired) keep-rewiring button; see the module docstring


def update_globals():
    global total_val, max_val, max_flow, mean_flow
    total_val = sum(t.val for t in turtles)
    max_val = max(t.val for t in turtles)
    if active_links.any():
        flows = [link.current_flow for link in active_links]
        max_flow = max(flows)
        mean_flow = mean(flows)


def update_visuals():
    for t in ask(turtles):
        # scale the size (an area, hence sqrt) to be between 0.1 and 5.0
        t.size = 0.1 + 5 * math.sqrt(t.val / total_val)
    for link in ask(active_links):
        # brighter gray the more value just flowed through this link
        link.color = scale_color(gray, link.current_flow / (2 * mean_flow + 0.00001), -0.4, 1)


def val_histogram():
    values = [t.val for t in turtles]
    if not values:
        return
    num_bars = max(1, ceiling(math.sqrt(turtles.count())))
    span = max(values) - min(values)
    bin_width = span / num_bars if span > 0 else 1
    histogram("val", values, bin_width=bin_width)


def active_link_count():
    return active_links.count()


def is_running():
    return True
