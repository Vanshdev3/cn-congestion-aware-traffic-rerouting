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
verification.

## Getting started

Read [docs/SETUP.md](docs/SETUP.md) before installing anything. The network
requires Linux, root privileges for Mininet, Open vSwitch, and Python. Windows
is the host; the networking tools run in a Linux VM or another Linux system.

The implementation will be added milestone by milestone. Until the Linux
environment is ready, the Mininet-dependent parts cannot be run on Windows.

## Team workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch and commit conventions and
[docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) for suggested roles. The final demo
sequence is in [docs/DEMO_CHECKLIST.md](docs/DEMO_CHECKLIST.md).

## References

- [Mininet walkthrough](https://mininet.org/walkthrough/)
- [Mininet download and VM setup](https://mininet.org/download/)
- [OS-Ken documentation](https://docs.openstack.org/os-ken/latest/)
- [Wireshark User's Guide](https://www.wireshark.org/docs/wsug_html/)

