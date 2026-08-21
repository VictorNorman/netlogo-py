"""Python port of NetLogo's classic "Random Basic" (ProbLab) model -- see
Sample Models/Mathematics/Probability/ProbLab/Random Basic.nlogox (from
the full NetLogo distribution, not bundled in this repo) for the real
source this was checked against line by line. A messenger turtle picks a
random value each tick and carries it to the matching column of a growing
histogram, one frame at a time, coloring the columns red/green by where
they fall relative to a slider cutoff.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. The first
model here to use turtle labels (Turtle.label, rendered as floating text
next to a turtle) and Turtle.hide_turtle()/.show_turtle() (a hidden
turtle still exists for ask/where queries, it just isn't drawn) -- both
added to engine/netlogo.py for this port, along with Turtle.face().

Deliberate deviations from the real source:
  - The messenger's `while [distance it > 3] [ fd 1; display ]` walking
    animation happens invisibly within a single go() call here -- this
    app only renders once per go() call (like every other model), not
    mid-procedure, so the messenger "teleports" to just short of its
    destination in one frame instead of visibly walking there. The final
    position (and every actual outcome) is identical either way.
  - The real model's messenger dies the instant it reaches its column,
    all within the same go(); since this app's frontend only ever sees
    state() *between* go() calls, that messenger (and its label -- the
    whole point of this port) would never actually be visible. Here the
    messenger instead dies at the *start* of the next go() -- right
    before the next one is born -- so it stays on screen, at its final
    resting spot, for exactly one rendered frame. Doesn't affect %-red/
    %-full/biggest-gap (none of them look at messengers at all).
  - Turtle size/shape (the messenger's `size 12`, frames' custom "frame"
    square shape) have no visible effect -- this app's turtle renderer
    always draws a fixed-size triangle, the same simplification several
    other models already document.
"""

INFO = """
<h2>Random Basic</h2>
<p>
  A Python port of NetLogo's classic <em>Random Basic</em>
  (ProbLab) model -- the first model in this app to use turtle
  labels. Each tick, a black "messenger" turtle picks a random
  number, its label, and walks to the matching column of a
  histogram, dropping a "frame" there -- building up the
  distribution of a random variable one draw at a time.
</p>
<p>
  The <em>red-green</em> slider splits the columns into two
  groups, colored as the histogram fills in (when
  <em>colors?</em> is on) -- watch <em>%-red</em> converge
  toward whatever share of the sample space falls left of that
  split.
</p>
"""

from engine.netlogo import *

resize_world(-50, 50, -30, 30)
set_wrap(False)

sample_space = slider("sample_space", default=100, min=1, max=100, step=1, label="sample-space")
# named histogram_height, not height -- state()'s "height" key is reserved
# for the actual world height in patches (see auto_state()'s docstring);
# the real model's own variable is called "height" (a coincidental
# collision), so the *widget label* stays "height" to match it exactly.
histogram_height = slider("histogram_height", default=30, min=1, max=50, step=1, label="height")
colors_on = switch("colors_on", default=True, label="colors?")
red_green = slider("red_green", default=50, min=0, max=100, step=1, label="red-green", units="%")
monitor("biggest_gap", "biggest gap")
monitor("percent_red", "%-red")
monitor("percent_full", "%-full")
button("setup")
button("go", forever=True)

column_counters = create_breed("column_counters", "column_counter")
frames = create_breed("frames", "frame")
messengers = create_breed("messengers", "messenger")

time_to_stop = False
the_messenger = None
max_y_histogram = 0


def setup():
    global time_to_stop, max_y_histogram
    clear_all()
    # the histogram grows up from the world's bottom edge -- this is how
    # tall (in patches) the "height" slider actually asks it to grow
    max_y_histogram = min_pycor() + histogram_height
    create_histogram_width()
    setup_column_counters()
    time_to_stop = False
    reset_ticks()


def create_histogram_width():
    for p in ask(patches):
        # centers the histogram in the world -- the red-green slider's
        # midpoint (50) always lands on the true center, whatever the
        # sample space is set to
        if -sample_space / 2 <= p.pxcor < sample_space / 2 and p.pycor < max_y_histogram:
            p.pcolor = yellow
        else:
            p.pcolor = brown


def setup_column_counters():
    # a column-counter is an invisible turtle sitting at the bottom of
    # each column, tracking (via its own position) how many values have
    # landed in that column so far
    for p in ask(patches.where(pycor=min_pycor(), pcolor=yellow)):
        for t in column_counters.sprout(p, 1):
            t.hide_turtle()
            t.heading = 0
            t.my_column = floor(t.xcor + sample_space / 2 + 1)
            t.my_column_patches = patches.where(pxcor=t.xcor)


def go():
    global time_to_stop
    if time_to_stop:
        stop()
        return
    select_random_value()
    send_messenger_to_its_column()
    if colors_on:
        paint()
    else:
        for p in ask(patches):
            if p.pcolor != brown:
                p.pcolor = yellow
    tick()


def select_random_value():
    global the_messenger
    if the_messenger is not None:
        # deferred from the end of last tick's send_messenger_to_its_column()
        # -- see the module docstring on why the death is delayed a tick
        the_messenger.die()
    p = patch_at(0, max_y_histogram + 4)
    for t in messengers.sprout(p, 1):
        t.color = black
        t.heading = 180
        t.label = 1 + random(sample_space)
        the_messenger = t


def send_messenger_to_its_column():
    global time_to_stop
    it = one_of(column_counters.where(my_column=the_messenger.label))
    the_messenger.face(it)
    while the_messenger.distance_to(it) > 3:
        the_messenger.forward(1)

    create_frame(it)
    it.forward(1)
    if it.ycor == max_y_histogram:
        time_to_stop = True


def create_frame(counter):  # counter: the column-counter turtle whose column just grew
    p = counter.patch_here()
    for f in frames.sprout(p, 1):
        f.color = black


def paint():
    for t in ask(column_counters):
        # the patches in this column that already have a frame stacked on
        # them -- everything strictly below the counter's current height
        filled_patches = [p for p in t.my_column_patches if p.pycor < t.ycor]
        fill_color = red if t.my_column <= red_green * sample_space / 100 else green
        for p in ask(filled_patches):
            p.pcolor = fill_color


def percent_red():
    frame_count = frames.count()
    if frame_count == 0:
        return 0.0
    return round(100 * patches.where(pcolor=red).count() / frame_count, 2)


def percent_full():
    return round(100 * frames.count() / (histogram_height * sample_space), 2)


def biggest_gap():
    counts = [len([p for p in t.my_column_patches if p.pycor < t.ycor]) for t in column_counters]
    if not counts:
        return 0
    return max(counts) - min(counts)


def is_running():
    return not time_to_stop
