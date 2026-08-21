"""Python port of NetLogo's classic "Preferential Attachment" model -- see
Sample Models/Networks/Preferential Attachment.nlogox (from the full
NetLogo distribution, not bundled in this repo) for the real source this
was checked against line by line.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. The first
model here to use a real histogram-mode plot pen (histogram(), added to
engine/netlogo.py for this port), plus Turtle.move_to() and
Link.both_ends() (also added for this port).

Deliberate deviations from the real source:
  - Only the bar-mode "Degree Distribution" plot is ported, not the real
    model's second "Degree Distribution (log-log)" plot -- that one is a
    second view of the exact same data (built from plotxy() + log(), both
    of which this app already supports), and this app's small plot canvas
    already tells the story with one histogram.
  - No resize-nodes button -- it toggles turtle *size*, which this app's
    renderer doesn't use (every turtle draws as a fixed-size triangle,
    same simplification several other models already document).
  - No separate "redo layout" forever-button -- layout already runs
    automatically inside go() when layout? is on; a standalone button to
    keep re-running it while idle is a minor convenience this app's fixed
    Setup/Go button pair has no room for.
"""

INFO = """
<h2>Preferential Attachment</h2>
<p>
  A Python port of NetLogo's classic <em>Preferential
  Attachment</em> model -- the first model in this app to use a
  real histogram-mode plot pen. Starting from two connected
  nodes, each tick adds one new node, linked to a random END of
  a random EXISTING link -- so a node with more connections is
  proportionally more likely to gain new ones ("rich get
  richer"), the mechanism behind real-world "scale-free"
  networks like the web or social graphs.
</p>
<p>
  Watch the <em>Degree Distribution</em> histogram develop a
  long tail: most nodes stay small, but a few "hubs" accumulate
  a disproportionate share of the connections.
</p>
"""

from engine.netlogo import *

resize_world(-45, 45, -45, 45)
set_wrap(False)

layout_on = switch("layout_on", default=True, label="layout?")
plot_on = switch("plot_on", default=True, label="plot?")
monitor("node_count", "# of nodes")
plot_widget(
    "Degree Distribution",
    x_label="degree",
    y_label="# of nodes",
    pens=[("degree", "#222222", "bar")],
)
button("setup")
button("go", forever=True)


def setup():
    clear_all()
    set_default_shape(turtles, "circle")
    # the initial network: two turtles and an edge
    first = make_node(None)
    make_node(first)
    reset_ticks()


def go():
    for link in ask(links):
        link.color = gray
    make_node(find_partner())
    tick()
    if layout_on:
        layout()
    if plot_on:
        update_plot()


def make_node(old_node):
    for t in create_turtles(1):
        t.color = red
        if old_node is not None:
            link = t.create_link_with(old_node)
            link.color = green
            t.move_to(old_node)
            t.forward(8)
        return t


def find_partner():
    # the heart of "preferential attachment": pick a random link, then a
    # random end of it -- a node with more links is proportionally more
    # likely to already show up as an end of whichever link gets picked.
    link = one_of(links)
    return one_of(link.both_ends())


def layout():
    # the number 3 here is arbitrary; more repetitions slows down the
    # model, but too few gives poor layouts
    for _ in range(3):
        factor = turtles.count() ** 0.5
        layout_spring(turtles, links, 1 / factor, 7 / factor, 1 / factor)
    # don't bump the edges of the world -- big jumps look funny, so only
    # adjust a little each time
    x_offset = limit_magnitude(max(t.xcor for t in turtles) + min(t.xcor for t in turtles), 0.1)
    y_offset = limit_magnitude(max(t.ycor for t in turtles) + min(t.ycor for t in turtles), 0.1)
    for t in ask(turtles):
        t.xcor -= x_offset / 2
        t.ycor -= y_offset / 2


def limit_magnitude(number, limit):
    if number > limit:
        return limit
    if number < -limit:
        return -limit
    return number


def update_plot():
    degrees = [t.link_neighbors().count() for t in turtles]
    histogram("degree", degrees)


def node_count():
    return turtles.count()


def is_running():
    return True
