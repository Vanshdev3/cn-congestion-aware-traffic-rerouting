# Congestion-Aware Traffic Rerouting

A small learning project that uses Mininet and Open vSwitch to carry real UDP
packets over two routes. An OS-Ken controller measures switch counters and
moves the selected flow to the second route when the first route stays busy.

The project is an emulation on one Linux machine. It does not control physical
routers. We use measured switch and receiver counters in the results. The
normal demo is terminal-based, so the network and controller can be inspected
directly instead of relying on a graphical view.

## Requirements and completion status

This repository implements Project 27, **Congestion Detection and Traffic
Rerouting**, from the team's SDN/socket-project allocation workbook. The
original project plan is also kept as the source of the detailed expectations.

| Project expectation | Current implementation | Evidence still needed |
|---|---|---|
| Generate UDP traffic across multiple paths | Numbered Python UDP sender and receiver; Path A and Path B in Mininet | Linux VM run |
| Create controlled congestion | 2 Mbps Path A, 5 Mbps Path B, configurable sender rate | Linux VM run at a rate above Path A capacity |
| Monitor flow statistics | OS-Ken requests flow statistics, verifies rules, and records UDP packet/byte counters | Linux controller output |
| Define and detect congestion thresholds | Configurable threshold, three consecutive high samples, cooldown | Linux controller output |
| Dynamically reroute traffic | Controller installs rules for the alternate path in adaptive mode | Linux flow-table and counter evidence |
| Measure recovery time and throughput | Separate timestamps, receiver throughput, packet loss, and path utilisation | Completed experiment CSV from Linux |
| Compare static and adaptive routing | Both modes use the same resettable manager and test controls | Matching static/adaptive runs |
| Use real measurements, not mock values | Counters and receiver summaries come from live processes; no sample results are committed | Do not present unrun values as results |
| Repeat experiments cleanly | Reset restores Path A and clears measurement baselines | Repeat twice in the VM |
| Provide packet-level evidence | Wireshark instructions and UDP filter are documented | Optional capture or screenshots |

The code and local unit/loopback tests are complete. The rows that require a
Linux kernel, Mininet, Open vSwitch, and OS-Ken cannot be honestly marked
experimentally verified from this Windows development environment. Follow
[`docs/TEAM_RUNBOOK.md`](docs/TEAM_RUNBOOK.md) to collect that evidence.

The optional Tkinter dashboard is not the networking implementation. The raw
terminal workflow is the primary demo and source of truth.

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
7. Keep the optional Tkinter dashboard as a later convenience layer.

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
The local control API and the simple terminal client are described in
[docs/HTTP_API.md](docs/HTTP_API.md).
The complete VM setup and presentation sequence are in
[docs/TEAM_RUNBOOK.md](docs/TEAM_RUNBOOK.md).

## Run the raw Linux demo

In Linux, start OS-Ken and the experiment manager in separate terminals. Use
`raw_demo.py` from another terminal to start the network, run tests, inspect
state, and stop the network. The exact commands are in [docs/SETUP.md](docs/SETUP.md).
The controller uses port 6653 explicitly so its listener matches the Mininet
switches.

## Getting started

Read [docs/SETUP.md](docs/SETUP.md) before installing anything. The complete
demo runs on Linux and requires root privileges for Mininet and Open vSwitch.
The project files, controller, manager, and test commands should all be run
inside that Linux environment.

## Team workflow

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch and commit conventions and
[docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md) for suggested roles. The final demo
sequence is in [docs/DEMO_CHECKLIST.md](docs/DEMO_CHECKLIST.md).
Use [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md) to publish this local history
to the public GitHub repository and invite the team.
See [docs/TESTING.md](docs/TESTING.md) for unit/UDP checks and the Linux
network acceptance checks.

## References

- [Mininet walkthrough](https://mininet.org/walkthrough/)
- [Mininet download and VM setup](https://mininet.org/download/)
- [OS-Ken documentation](https://docs.openstack.org/os-ken/latest/)
- [Wireshark User's Guide](https://www.wireshark.org/docs/wsug_html/)

