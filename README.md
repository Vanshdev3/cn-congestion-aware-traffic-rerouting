# Congestion-Aware Traffic Rerouting

A small learning project that uses Mininet and Open vSwitch to carry real UDP
packets over two routes. An OS-Ken controller measures switch counters and
moves the selected flow to the second route when the first route stays busy.

The project is an emulation on one Linux machine. It does not control physical
routers. We will use measured switch and receiver counters in the results; the
dashboard is only a way to control and observe the experiment.

## Network idea

```text
                     Path A (2 Mbps)
                +---- s2 --------+
                |                |
 h1 ---- s1 ----+                +---- s4 ---- h2
                |                |
                +---- s3 --------+
                     Path B (5 Mbps)
```

The controller starts the UDP flow on Path A. In adaptive mode, it can change
OpenFlow rules to use Path B after measured congestion is confirmed. Static
mode reports congestion but keeps the flow on Path A.

## Project milestones

1. Prepare Linux and confirm Mininet starts.
2. Build the two-path topology and print the actual interface/port map.
3. Send UDP packets and count unique, duplicate, and out-of-order sequences.
4. Connect OS-Ken to Open vSwitch and collect directional port counters.
5. Add congestion detection, rule changes, and strict path verification.
6. Repeat baseline, static, and adaptive experiments; export measured CSV.
7. Add the Tkinter dashboard and connect it to the running experiment.

Each milestone is recorded in its own Git commit. The first `pingall` check is
only a Mininet smoke test; controller connection and rerouting need separate
verification. `topology.py` defines the link/port layout, and
`start_network.py` prints the interfaces Mininet actually created before
opening its command prompt.

`udp_sender.py` sends fixed-size packets with a sequence number and monotonic
send timestamp. `udp_receiver.py` keeps unique sequence numbers, counts
duplicates and out-of-order arrivals, and writes a live JSON snapshot. Final
loss is calculated only after the sender summary is available, so a temporary
gap does not count as a lost packet.

The OS-Ken behavior and its verification steps are described in
[docs/CONTROLLER.md](docs/CONTROLLER.md). The controller and experiment manager
share small JSON files under `run/`, which are local runtime state and are not
committed to Git.
The dashboard API paths are listed in [docs/HTTP_API.md](docs/HTTP_API.md).

## Run the full application

In Linux, start OS-Ken and the experiment manager in separate terminals, then
open the dashboard in a third. The exact commands and privilege notes are in
[docs/SETUP.md](docs/SETUP.md). The controller uses port 6653 explicitly so
its listener matches the Mininet switches.
The dashboard can change the sender's rate while a test is running; the sender
reads that setting and changes its real UDP pacing.

## Getting started

Read [docs/SETUP.md](docs/SETUP.md) before installing anything. The network
requires Linux, root privileges for Mininet, Open vSwitch, and Python. Windows
is the host; the networking tools run in a Linux VM or another Linux system.

The Mininet-dependent parts have not yet been run because this computer does
not have WSL or another Linux VM installed. See the setup guide for the first
smoke test and the controller/network startup sequence.

## Team workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch and commit conventions and
[docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) for suggested roles. The final demo
sequence is in [docs/DEMO_CHECKLIST.md](docs/DEMO_CHECKLIST.md).
Use [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md) to connect this local history
to the suggested private GitHub repository after creating it.
See [docs/TESTING.md](docs/TESTING.md) for local unit/UDP checks and the Linux
network acceptance checks.

## References

- [Mininet walkthrough](https://mininet.org/walkthrough/)
- [Mininet download and VM setup](https://mininet.org/download/)
- [OS-Ken documentation](https://docs.openstack.org/os-ken/latest/)
- [Wireshark User's Guide](https://www.wireshark.org/docs/wsug_html/)

