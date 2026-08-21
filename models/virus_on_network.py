"""Python port of NetLogo's classic "Virus on a Network" model -- see
Sample Models/Networks/Virus on a Network.nlogox (from the full NetLogo
distribution, not bundled in this repo) for the real source this was
checked against line by line.

Deliberate deviations from the real source:
  - `average-node-degree`'s and `initial-outbreak-size`'s slider maxes are
    static numbers here (real NetLogo ties them dynamically to
    `number-of-nodes - 1` / `number-of-nodes`, recomputed live if that
    other slider changes) -- this engine's slider() has fixed bounds.
  - layout_spring() (engine/netlogo.py) is a reasonable force-directed
    layout, not a port of NetLogo's exact internal algorithm -- it's
    purely cosmetic (turtles never move again once go() starts, same as
    the real model), so exact fidelity isn't behaviorally important, just
    a reasonable-looking initial network.
  - susceptible_count/infected_count/resistant_count monitors are this
    app's own addition beyond the real widget set (which only has the
    plot), a value-add rather than a real-source deviation.
"""

INFO = """
<h2>Virus on a Network</h2>
<p>
  A Python port of NetLogo's classic <em>Virus on a Network</em>
  model -- the first model in this app to use links. Nodes
  (turtles) are susceptible (blue), infected (red), or resistant
  (gray), connected by a randomly-built, spatially-clustered
  network. Each tick, infected nodes may spread the virus to
  their uninfected neighbors along a link, then periodically
  check whether they recover (possibly gaining resistance) or
  stay infected.
</p>
<p>
  The network's layout is computed once during setup (a simple
  force-directed <code>layout_spring</code>, added to
  engine/netlogo.py for this port) -- turtles never move again
  once <code>go</code> starts, so what you're watching is purely
  color/link changes as the epidemic spreads across a fixed graph.
</p>
"""

from engine.netlogo import *

resize_world(-20, 20, -20, 20)
set_wrap(False)

number_of_nodes = slider("number_of_nodes", default=150, min=10, max=300, step=5, label="number-of-nodes")
average_node_degree = slider(
    "average_node_degree",
    default=6,
    min=1,
    max=50,
    step=1,
    label="average-node-degree",
)
initial_outbreak_size = slider(
    "initial_outbreak_size",
    default=3,
    min=1,
    max=50,
    step=1,
    label="initial-outbreak-size",
)
virus_spread_chance = slider(
    "virus_spread_chance",
    default=2.5,
    min=0,
    max=10,
    step=0.1,
    label="virus-spread-chance",
    units="%",
)
virus_check_frequency = slider(
    "virus_check_frequency",
    default=1,
    min=1,
    max=20,
    step=1,
    label="virus-check-frequency",
    units="ticks",
)
recovery_chance = slider(
    "recovery_chance",
    default=5,
    min=0,
    max=10,
    step=0.1,
    label="recovery-chance",
    units="%",
)
gain_resistance_chance = slider(
    "gain_resistance_chance",
    default=5,
    min=0,
    max=100,
    step=1,
    label="gain-resistance-chance",
    units="%",
)
monitor("susceptible_count", "susceptible")
monitor("infected_count", "infected")
monitor("resistant_count", "resistant")
plot_widget(
    "Network Status",
    x_label="time",
    y_label="% of nodes",
    pens=[
        ("susceptible", "#3355aa"),
        ("infected", "#dd3333"),
        ("resistant", "#888888"),
    ],
)
button("setup")
button("go", forever=True)


def setup():
    clear_all()
    setup_nodes()
    setup_spatially_clustered_network()
    for t in ask(n_of(int(initial_outbreak_size), turtles)):
        become_infected(t)
    for link in ask(links):
        link.color = white
    reset_ticks()


def setup_nodes():
    set_default_shape(turtles, "circle")
    for t in create_turtles(int(number_of_nodes)):
        # for visual reasons, don't put any nodes *too* close to the edges
        t.xcor = random_xcor() * 0.95
        t.ycor = random_ycor() * 0.95
        become_susceptible(t)
        t.virus_check_timer = random(virus_check_frequency)


def setup_spatially_clustered_network():
    num_links = (average_node_degree * number_of_nodes) / 2
    while links.count() < num_links:
        t = one_of(turtles)
        candidates = [u for u in t.other(turtles) if not t.link_neighbor(u)]
        choice = t.nearest(candidates)
        if choice is not None:
            t.create_link_with(choice)
    # make the network look a little prettier
    spring_length = (max_pxcor() - min_pxcor() + 1) / (number_of_nodes**0.5)
    for _ in range(10):
        layout_spring(turtles, links, 0.3, spring_length, 1)


def go():
    if all(not t.infected for t in turtles):
        stop()
        return
    for t in ask(turtles):
        t.virus_check_timer += 1
        if t.virus_check_timer >= virus_check_frequency:
            t.virus_check_timer = 0
    spread_virus()
    do_virus_checks()
    tick()

    total = turtles.count()
    plot("susceptible", susceptible_count() / total * 100)
    plot("infected", infected_count() / total * 100)
    plot("resistant", resistant_count() / total * 100)


def become_infected(t):  # turtle procedure
    t.infected = True
    t.resistant = False
    t.color = red


def become_susceptible(t):  # turtle procedure
    t.infected = False
    t.resistant = False
    t.color = blue


def become_resistant(t):  # turtle procedure
    t.infected = False
    t.resistant = True
    t.color = gray
    for link in ask(t.my_links()):
        link.color = gray - 2


def spread_virus():
    for t in ask(turtles.where(infected=True)):
        for neighbor in ask(t.link_neighbors().where(resistant=False)):
            if random_float(100) < virus_spread_chance:
                become_infected(neighbor)


def do_virus_checks():
    for t in ask(turtles.where(infected=True, virus_check_timer=0)):
        if random(100) < recovery_chance:
            if random(100) < gain_resistance_chance:
                become_resistant(t)
            else:
                become_susceptible(t)


def susceptible_count():
    return turtles.where(infected=False, resistant=False).count()


def infected_count():
    return turtles.where(infected=True).count()


def resistant_count():
    return turtles.where(resistant=True).count()


def is_running():
    return any(t.infected for t in turtles)
