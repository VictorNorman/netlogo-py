"""Python port of NetLogo's classic "Rock Paper Scissors" model -- see
Sample Models/Biology/Rock Paper Scissors.nlogox (from the full NetLogo
distribution, not bundled in this repo) for the real source this was
checked against line by line.

Written directly against engine/netlogo.py's free-function runtime -- see
models/fire.py for the design decisions behind that runtime. Needs
engine/netlogo.py's random_poisson() and shuffle(), both added for this
port. NetLogo's own n-values/sentence/foreach don't get dedicated
wrappers here -- Python's own list repetition (`[x] * n`), concatenation
(`+`), and a plain `for` loop already say exactly the same thing, more
directly than a NetLogo-primitive-named wrapper would.

Performance note: this model's world is large (151x151 patches, matching
the real view) and go() calls one_of() on the whole patch agentset up to
several thousand times per tick -- see one_of()'s own docstring for the
already-materialized-list fast path this relies on to stay fast; go()
below builds that list once per tick rather than passing the live
`patches` agentset to one_of() on every single event.

Deliberate deviations from the real source: none -- this is a direct,
line-by-line transliteration.
"""

INFO = """
<h2>Rock Paper Scissors</h2>
<p>
  A Python port of NetLogo's classic <em>Rock Paper Scissors</em>
  model. Every patch is red, green, blue, or blank; red beats
  green, green beats blue, blue beats red. Each tick, random
  pairs of neighboring patches swap, reproduce, or compete, at
  rates drawn from a Poisson distribution -- producing the
  chasing spirals characteristic of cyclic-dominance ecosystems.
</p>
<p>
  The three <code>*-rate-exponent</code> sliders each scale
  their event's rate by a power of 10 -- watch how much faster
  <em>swap</em> (movement) needs to be, relative to
  <em>select</em> (competition), to keep the spirals stable
  instead of collapsing to one color.
</p>
"""

from engine.netlogo import *

resize_world(-75, 75, -75, 75)
set_wrap(True)

swap_rate_exponent = slider(
    "swap_rate_exponent",
    default=0,
    min=-1,
    max=1,
    step=0.1,
    label="swap-rate-exponent",
)
reproduce_rate_exponent = slider(
    "reproduce_rate_exponent",
    default=0,
    min=-1,
    max=1,
    step=0.1,
    label="reproduce-rate-exponent",
)
select_rate_exponent = slider(
    "select_rate_exponent",
    default=0,
    min=-1,
    max=1,
    step=0.1,
    label="select-rate-exponent",
)
monitor("swap_percentage", "swap-%")
monitor("reproduce_percentage", "reproduce-%")
monitor("select_percentage", "select-%")
plot_widget(
    "Populations",
    pens=[
        ("red", "#dd3333"),
        ("green", "#39d353"),
        ("blue", "#3355aa"),
    ],
)
button("setup")
button("go", forever=True)

SWAP_EVENT = 0
REPRODUCE_EVENT = 1
SELECT_EVENT = 2


def setup():
    clear_all()
    for p in ask(patches):
        # start populations at roughly even levels
        p.pcolor = one_of([red, green, blue, black])
    reset_ticks()


def go():
    # Compute how many events of each type should occur this tick, build a
    # combined shuffled list of event markers, then run through it -- see
    # the module docstring on why we can't just have each patch run all of
    # its own actions in one go (the events need to be interleaved randomly
    # across all patches, not grouped per patch).
    repetitions = patches.count() / 3  # at default settings, ~1 event per patch
    events = (
        [SWAP_EVENT] * random_poisson(repetitions * swap_rate())
        + [REPRODUCE_EVENT] * random_poisson(repetitions * reproduce_rate())
        + [SELECT_EVENT] * random_poisson(repetitions * select_rate())
    )
    events = shuffle(events)

    patch_list = list(patches)  # built once -- see the module docstring
    for event in events:
        p = one_of(patch_list)
        target = one_of(p.neighbors4())
        if target is None:
            continue
        if event == SWAP_EVENT:
            swap(p, target)
        elif event == REPRODUCE_EVENT:
            reproduce(p, target)
        elif event == SELECT_EVENT:
            select(p, target)
    tick()

    plot("red", patches.where(pcolor=red).count())
    plot("green", patches.where(pcolor=green).count())
    plot("blue", patches.where(pcolor=blue).count())


def swap(p, target):  # patch procedure -- swap pcolor with target
    p.pcolor, target.pcolor = target.pcolor, p.pcolor


def select(p, target):  # patch procedure -- compete with target; the loser goes blank
    if beats(p, target):
        target.pcolor = black
    elif beats(target, p):
        p.pcolor = black


def reproduce(p, target):  # patch procedure
    # if target is blank, reproduce onto it; if I'm blank, target reproduces onto me
    if target.pcolor == black:
        target.pcolor = p.pcolor
    elif p.pcolor == black:
        p.pcolor = target.pcolor


def beats(p, other):
    return (
        (p.pcolor == red and other.pcolor == green)
        or (p.pcolor == green and other.pcolor == blue)
        or (p.pcolor == blue and other.pcolor == red)
    )


def rate_from_exponent(exponent):
    return 10**exponent


def swap_rate():
    return rate_from_exponent(swap_rate_exponent)


def reproduce_rate():
    return rate_from_exponent(reproduce_rate_exponent)


def select_rate():
    return rate_from_exponent(select_rate_exponent)


def percentage(rate):
    return 100 * rate / (swap_rate() + reproduce_rate() + select_rate())


def swap_percentage():
    return percentage(swap_rate())


def reproduce_percentage():
    return percentage(reproduce_rate())


def select_percentage():
    return percentage(select_rate())


def is_running():
    return True
