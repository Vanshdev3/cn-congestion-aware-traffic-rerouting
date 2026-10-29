# Linux Demo Runbook

This is the practical guide for the team demo. The project runs inside Linux.
Mininet, Open vSwitch, OS-Ken, the sender, receiver, and experiment manager
must all run in the same Linux VM or Linux computer. The Windows machine, if
used, is only the host for the VM; it is not part of the experiment.

## 1. What the project demonstrates

The project sends real UDP datagrams from `h1` to `h2` through an emulated
software-defined network. There are two possible routes:

```text
Path A: h1 -- s1 -- s2 -- s4 -- h2    2 Mbps links
Path B: h1 -- s1 -- s3 -- s4 -- h2    5 Mbps links
```

The links from `h1` to `s1` and from `s4` to `h2` are 10 Mbps. Path A is the
narrower route, so a sender rate above roughly 2 Mbps should make it the route
that demonstrates congestion. Path B has more capacity and is the alternate
route.

The controller does not use fake traffic or made-up measurements. It:

1. Reads actual Open vSwitch port counters.
2. Converts counter changes into bits per second and link utilisation.
3. Confirms congestion over several consecutive samples.
4. Installs OpenFlow rules for the alternate path in adaptive mode.
5. Verifies the rules using flow statistics.
6. Verifies that counters on the new path actually increase.
7. Records congestion, rule-installation, flow-verification, and recovery times.

The sender adds a sequence number to every UDP packet. The receiver counts
unique packets, duplicates, out-of-order packets, and final loss after the
sender summary is available.

## 2. Repository map

| File | Purpose |
|---|---|
| `topology.py` | Defines hosts, switches, capacities, paths, and port mapping |
| `start_network.py` | Opens the plain Mininet CLI for topology inspection |
| `controller.py` | OS-Ken controller for counters, routing, and verification |
| `flow_rules.py` | Converts the discovered map into input/output switch ports |
| `metrics.py` | Counter-rate and utilisation calculations |
| `udp_sender.py` | Sends numbered, rate-controlled UDP packets |
| `udp_receiver.py` | Receives packets and writes measurement summaries |
| `experiment_manager.py` | Owns Mininet and coordinates repeatable runs |
| `raw_demo.py` | Beginner-friendly terminal client for the manager |
| `dashboard.py` | Optional Tkinter client; not required for the demo |
| `run/` | Temporary controller, port-map, and live-test files |
| `results/experiments.csv` | Completed experiment results; generated locally |

## 3. Linux VM preparation

Inside the Linux VM, open a terminal and install the packages:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3 python3-pip python3-venv wireshark
sudo systemctl enable --now openvswitch-switch
```

Clone the repository or copy it into Linux, then enter it:

```bash
cd ~/cn-congestion-aware-traffic-rerouting
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Record versions for the report:

```bash
python3 --version
mn --version
ovs-vsctl --version
python -m pip show os-ken
```

## 4. Test the project before starting the network

These checks do not require Mininet and are useful for catching ordinary Python
mistakes:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
git diff --check
```

The loopback test sends real UDP packets through Linux's loopback interface.
It does not replace the Mininet test; it only checks the sender and receiver.

## 5. Start the three Linux terminals

Use three terminals in the project directory. Activate the virtual environment
in each terminal if necessary.

Terminal 1, start OS-Ken:

```bash
sudo .venv/bin/osken-manager --ofp-tcp-listen-port 6653 controller.py
```

The controller should remain running and print switch connections after the
network starts.

Terminal 2, start the experiment manager:

```bash
sudo python3 experiment_manager.py
```

Terminal 3 is the raw demo terminal. The commands below send HTTP requests to
the manager, but the actual experiment remains in Mininet and Open vSwitch.

## 6. Start and inspect the network

```bash
python3 raw_demo.py start-network
python3 raw_demo.py status
python3 raw_demo.py events
```

The first command must report a discovered map and verified Path A rules. The
status should eventually show:

```text
network_running: true
controller_available: true
active_path: A
route_status: active
flow_entries_verified: true
```

The topology mapping should show these planned switch ports:

```text
s1 port 1: h1
s1 port 2: s2
s1 port 3: s3
s2 port 1: s1
s2 port 2: s4
s3 port 1: s1
s3 port 2: s4
s4 port 1: s2
s4 port 2: s3
s4 port 3: h2
```

The exact interface names may include names such as `s1-eth2`; the important
part is that the printed interface and OpenFlow port agree.

Useful raw Open vSwitch checks from another Linux terminal are:

```bash
sudo ovs-vsctl show
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
sudo ovs-ofctl -O OpenFlow13 dump-flows s3
sudo ovs-ofctl -O OpenFlow13 dump-flows s4
```

The selected path has IPv4 forwarding rules and a more specific UDP rule. The
UDP rule should contain source `10.0.0.1`, destination `10.0.0.2`, and UDP
destination port `5001`.

The controller state also exposes `flow_statistics`. These are the packet and
byte counters returned by OpenFlow for the selected UDP rules. They are
separate from the port counters used for link utilisation, so the demo can
show both network-level load and application-flow evidence.

## 7. Run a normal UDP test

Start with a low rate to prove delivery without intentional congestion:

```bash
python3 raw_demo.py reset --mode static --threshold 75
python3 raw_demo.py start-test --mode static --rate 1 --duration 10
```

While it runs, inspect live state:

```bash
python3 raw_demo.py status
```

When the sender finishes, ask for status again. The final result should include
sent packets, received packets, packet loss, receiver throughput, and path
utilisation. The result is also appended to `results/experiments.csv`.

## 8. Compare static and adaptive routing

Use the same rate, duration, and threshold in both runs. A 4 Mbps sender is a
reasonable starting point because Path A has 2 Mbps links:

Static run:

```bash
python3 raw_demo.py reset --mode static --threshold 75
python3 raw_demo.py start-test --mode static --rate 4 --duration 20
python3 raw_demo.py status
```

Adaptive run:

```bash
python3 raw_demo.py reset --mode adaptive --threshold 75
python3 raw_demo.py start-test --mode adaptive --rate 4 --duration 20
python3 raw_demo.py status
python3 raw_demo.py events
```

In static mode, congestion may be reported but the active path should remain
Path A. In adaptive mode, after three high-utilisation samples, the controller
should install Path B, verify its flow entries, and then verify increasing
counters on Path B's unique links (`s1-s3` and `s3-s4`).

The exact result depends on VM performance and scheduling. Do not invent a
specific recovery time or packet-loss percentage. Copy the values printed by
the manager and saved in the CSV.

## 9. Live rate control

Start a longer run:

```bash
python3 raw_demo.py reset --mode adaptive --threshold 75
python3 raw_demo.py start-test --mode adaptive --rate 1 --duration 30
```

Change the sender while it is running:

```bash
python3 raw_demo.py set-rate 4
python3 raw_demo.py status
```

The sender checks the rate file about every quarter second. The final sender
summary records the configured starting rate, final rate, and rate changes.

## 10. Wireshark evidence

Start Wireshark inside Linux and capture on the interface carrying the Mininet
traffic. Use this display filter:

```text
udp.port == 5001
```

The packets should contain the custom sequence header. Save the capture only
after confirming that packets are visible. The capture is supporting evidence;
the controller and receiver JSON/CSV measurements remain the main results.

## 11. Stop, reset, and export

Stop only the current traffic test:

```bash
python3 raw_demo.py stop-test
```

Reset the experiment to Path A and clear measurement baselines before a new
comparison:

```bash
python3 raw_demo.py reset --mode adaptive --threshold 75
```

Stop the complete Mininet network:

```bash
python3 raw_demo.py stop-network
```

Show the result file:

```bash
python3 raw_demo.py export
less results/experiments.csv
```

If a run is interrupted, clean up Mininet before trying again:

```bash
sudo mn -c
```

Use that cleanup only after stopping the manager or when Mininet reports stale
interfaces. It removes leftover emulation state, not the source files.

## 12. What to show during the presentation

Show the topology map first, then the controller terminal showing switch
connections. Show `ovs-ofctl dump-flows` before and after adaptive rerouting.
Show `raw_demo.py status` for live counters and the final result for measured
loss and recovery time. Finally open `results/experiments.csv` and compare the
static and adaptive rows using the same traffic settings.

The project is complete for the demo only when the Linux VM proves all of the
following with real output:

- both paths are created and their ports match the printed map;
- all four switches connect to OS-Ken;
- the UDP packets reach `h2`;
- static mode stays on Path A under the chosen test;
- adaptive mode verifies a Path B rule change and Path B counter movement;
- reset restores Path A and a new run produces a separate measured result.

