# Controller notes

The OS-Ken app is in `controller.py`. Start it from the project directory in
the Linux environment:

```bash
source .venv/bin/activate
osken-manager controller.py
```

The topology writes the discovered port map to `run/port_map.json`. The
controller reads that file and uses the same mapping when it requests port
counters and installs rules. Its current state is written to
`run/controller_state.json`.

The experiment manager and dashboard use `run/controller_command.json` to
request a reset or change the mode and threshold. These files are runtime
state; `.gitignore` keeps the `run/` directory out of commits.

## What the controller measures

For every link in the H1-to-H2 path, the map identifies one switch port and one
counter direction. The first link uses the switch port's receive-byte counter;
the remaining links use the transmitting switch port's transmit-byte counter.
The controller compares counter samples and divides the measured bit rate by
the configured capacity.

Path utilisation is shown as the highest measured utilisation among that
path's links. A path does not become congested until three consecutive samples
meet or exceed the threshold. Static mode reports this state without changing
the route.

## What counts as a route change

The controller removes only its own marked flow entries, writes the selected
path's UDP rules, waits for OpenFlow barriers, and requests flow statistics.
It checks the expected input/output port rule on every switch in the path. For
an adaptive change, it then waits for increasing byte counters on the links
unique to the new path. Recovery time ends at that counter verification and
rule installation time is recorded separately.

If the switch table or counter verification does not finish within ten
seconds, the controller reports a verification failure and clears the active
route status. It does not label the change as successful.

