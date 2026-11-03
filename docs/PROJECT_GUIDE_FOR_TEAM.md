# Congestion-Aware Traffic Rerouting: Team Guide

This guide explains the project from the networking idea to the live demo. It
is written for a teammate who has not used Mininet, SDN, or this repository
before. Commands below are run inside the Kali Linux VM, from the repository
folder, unless a note says otherwise.

## 1. Project in one paragraph

We build a small network in software with two different routes between a UDP
sender and receiver. An SDN controller reads real Open vSwitch port counters.
When the active route stays above a chosen load threshold, adaptive mode changes
the OpenFlow rules to use the other route. We verify the new rules and require
the alternate route's counters to increase before calling the reroute
successful. The receiver measures delivered UDP traffic, and each finished run
is saved as a row in a CSV file.

This is a Mininet emulation on one Linux computer. It does not change physical
network equipment.

## 2. What the project demonstrates

- Build a topology with two hosts and four OpenFlow switches.
- Send real UDP datagrams with sequence numbers from `h1` to `h2`.
- Limit link rates to create a controlled bottleneck.
- Read directional switch-port counters through OS-Ken/OpenFlow 1.3.
- Calculate link load and detect sustained congestion.
- Compare static routing with controller-driven adaptive rerouting.
- Verify forwarding rules and traffic-counter movement after a route change.
- Measure receiver throughput, packet loss, and recovery time.
- Repeat tests with a reset and keep the results in CSV.

## 3. Network layout

```text
                              PATH A (2 Mbps bottleneck links)
                         +--- s2 ----------------+
                         |                       |
 h1 (UDP sender) -- s1 --+                       +-- s4 -- h2 (UDP receiver)
                         |                       |
                         +--- s3 ----------------+
                              PATH B (5 Mbps bottleneck links)

 Path A: h1 -> s1 -> s2 -> s4 -> h2
 Path B: h1 -> s1 -> s3 -> s4 -> h2
```

Both routes share the sender link (`h1-s1`) and the receiver-side link
(`s4-h2`). They differ in the middle. Path A's `s1-s2` and `s2-s4` links are
each configured at 2 Mbps. Path B's `s1-s3` and `s3-s4` links are each 5 Mbps.
Host-facing links are 10 Mbps.

The topology is defined in `topology.py`. Mininet creates Linux network
interfaces and Open vSwitch bridges. At startup, the manager discovers the
actual interface and switch-port numbers and writes `run/port_map.json`. The
controller uses this discovered map for both counter requests and flow rules,
so its port assumptions match the topology Mininet created.

## 4. Software and each part's job

| Software / file | Job in this project |
|---|---|
| Kali Linux VM | Provides the Linux kernel and root access required by Mininet and OVS. |
| Mininet | Creates virtual hosts, links, interfaces, and a commandable network. |
| Open vSwitch (OVS) | Acts as the four software switches and forwards packets using flow rules. |
| OpenFlow 1.3 | Protocol used by the switches to communicate with the controller. |
| OS-Ken | Python SDN controller framework; runs `controller.py`. |
| `experiment_manager.py` | Starts/stops Mininet and traffic processes, exposes the local HTTP API, and saves final results. |
| `udp_receiver.py` | Runs inside Mininet host `h2`; counts received UDP packets and writes measurements. |
| `udp_sender.py` | Runs inside Mininet host `h1`; sends numbered UDP packets at a controlled rate. |
| `web/` dashboard | Browser controls and live view served by the experiment manager at port 8765. |
| `raw_demo.py` | Optional terminal client for the same manager commands and state. |
| Wireshark | Optional packet capture tool for showing actual UDP traffic. |

Python's built-in HTTP server serves the dashboard and API. The browser UI has
no Node, React, Flask, or external runtime dependency.

## 5. SDN and OpenFlow in simple terms

In a traditional switch, the forwarding logic is configured inside the switch.
In Software Defined Networking (SDN), a controller makes forwarding decisions
and communicates them to programmable switches.

In this project:

1. OS-Ken is the control plane. It watches switch statistics and decides which
   route should carry the selected UDP flow.
2. OVS switches are the data plane. They forward packets according to flow
   entries installed by the controller.
3. OpenFlow is the control channel between the switches and OS-Ken. The switches
   connect to TCP port 6653 using OpenFlow 1.3.
4. The experiment manager is the experiment operator. It creates Mininet,
   starts the sender and receiver, and gives the dashboard a local API.

A flow entry is a rule with match fields and an action. Here, the important
match fields identify the UDP flow; the action chooses an output port. The
controller installs matching forwarding steps on each switch along the route.
It waits for switch barriers and checks the flow entries before reporting the
route as installed.

## 6. Three-terminal setup

Open three terminal windows inside Kali. Keep Terminals 1 and 2 running for the
whole demonstration. Do not start Mininet separately with `sudo mn` or
`start_network.py` while the experiment manager owns the network.

### Terminal 1: start OS-Ken

From the project directory:

```bash
cd ~/cn-congestion-aware-traffic-rerouting
source .venv/bin/activate
sudo .venv/bin/osken-manager --ofp-tcp-listen-port 6653 controller.py
```

Leave this terminal open. It should load `controller.py` and wait for switches.
The Eventlet deprecation notice is a dependency warning; the key check is that
the process stays running and later logs switch connections.

### Terminal 2: start the experiment manager

```bash
cd ~/cn-congestion-aware-traffic-rerouting
sudo python3 experiment_manager.py
```

It should print that it is listening at `http://127.0.0.1:8765`. When the
network starts, it also prints the real Mininet interface and port map. Keep
this terminal open. The manager needs root because it creates Mininet and OVS
interfaces.

### Terminal 3: open the dashboard

```bash
firefox http://127.0.0.1:8765/
```

The browser can also be opened before starting the network. It will show the
manager connection and a network-stopped state. After updating the repository,
use `Ctrl+Shift+R` in Firefox to reload the current dashboard files.

### Optional terminal control

Instead of clicking the browser UI, Terminal 3 can send commands directly:

```bash
python3 raw_demo.py status
python3 raw_demo.py start-network
python3 raw_demo.py events
```

Use either the UI or `raw_demo.py` for a given action. They both call the same
experiment manager; they are not separate experiments.

## 7. Start cleanly and recover from a stale Mininet run

Stop foreground processes with `Ctrl+C` in their terminals. If an old manager
is still occupying port 8765, inspect it and stop only that listener:

```bash
sudo fuser -v 8765/tcp
sudo fuser -k 8765/tcp
```

If Mininet reports `RTNETLINK answers: File exists` while creating virtual
interfaces, clean its stale network state:

```bash
sudo mn -c
```

Then start Terminal 1, Terminal 2, and Terminal 3 in that order. `sudo mn -c`
cleans Mininet-created state; it is a recovery step, not a command to run during
an active experiment.

To update code from GitHub before a demo:

```bash
cd ~/cn-congestion-aware-traffic-rerouting
git pull
```

Restart the experiment manager after pulling because it serves the dashboard
files from disk. Restart the controller too if `controller.py` changed.

## 8. Recommended demo sequence

Use these settings for a clear adaptive reroute: Adaptive mode, 3 Mbps offered
rate, 15 seconds, and 75% threshold. Three Mbps exceeds Path A's 2 Mbps
bottleneck but is below Path B's 5 Mbps bottleneck.

1. Start the network from the dashboard. Wait for all switches and the
   controller to become available.
2. Choose **Adaptive**, set **3 Mbps**, **15 seconds**, and **75%**.
3. Click **Reset to Path A**. Confirm the event log reports Path A rules
   installed and verified.
4. Click **Start test**.
5. Watch Path A load rise. After the controller confirms sustained congestion,
   it installs Path B rules.
6. The controller verifies the expected flow entries and waits for counters on
   Path B's unique links to increase. Only then is the switch reported as
   verified and recovery time recorded.
7. When the test finishes, packet animation stops. The selected route may stay
   set to Path B until reset; this does not mean packets are still flowing.
8. Click **Export CSV** or inspect `results/experiments.csv`.
9. Reset to Path A before starting a comparison run.

To compare static and adaptive fairly, use the same offered rate, duration,
threshold, and initial reset in both runs. Static mode reports congestion but
keeps the flow on Path A. Adaptive mode may move the flow when the threshold
logic confirms congestion and the alternate path is eligible.

## 9. Dashboard guide

### Status strip

The top strip says whether the network is offline, waiting for switches, ready,
running, congested, or finished. During a test it names the controller's
selected route. After completion it describes the last route as historical and
states that sending has stopped.

### Traffic offered slider and number

The slider selects the sender's target UDP rate in Mbps. The adjacent number
box lets you enter an exact value; moving either control updates the other.
During a running test, **Apply live rate** writes a new sender rate that the
sender reads within about a quarter second. Before a test, the selected rate is
used when starting it.

### Run length

The duration is how long the sender sends UDP packets. When it ends, the manager
stops the processes, finalizes packet loss using the sender summary, and appends
one result row to the CSV.

### Congestion threshold

This is the utilisation percentage at which a path is considered busy. The
controller requires three consecutive samples at or above the threshold to
confirm congestion. That avoids rerouting because of one brief counter spike.

### Routing mode

- **Static:** the controller monitors and logs congestion but does not move the
  route due to congestion. The traffic stays on the configured path unless a
  manual reset or route operation changes it.
- **Adaptive:** after congestion is confirmed on the current route, the
  controller checks the alternate path. If its measured load is below the
  threshold and lower than the congested path, it installs the alternate-path
  rules and verifies traffic movement.

### Buttons

| Button | Effect |
|---|---|
| Start network | Creates the Mininet topology, prints/saves the discovered port map, waits for switches, installs initial Path A rules, and verifies them. |
| Start test | Resets to Path A with the selected mode/threshold, starts the receiver on `h2`, then the sender on `h1`. |
| Apply live rate | Changes the active sender rate while a test is running. |
| Apply settings | Sends the selected routing mode and threshold to the controller. |
| Reset to Path A | Stops/finalizes an active test as applicable, resets measurements/baselines and controller state, then installs and verifies the initial Path A route. |
| Stop test | Stops sender and receiver and saves final measurements. |
| Stop network | Stops the test if necessary and tears down Mininet. |
| Export CSV | Shows the location of the accumulated `results/experiments.csv` file. |

### Topology visualization

The topology has sender `h1`, switches `s1` to `s4`, and receiver `h2`.
Path A goes through `s2`; Path B goes through `s3`. The highlighted route is
the selected route while traffic is running. Orange indicates confirmed
congestion on the active route. After a successful route change, the new route
is verified using switch counters. The moving packet markers are a visual aid;
the underlying proof comes from the real sender/receiver and OpenFlow counters.

### Live measurements

Path A and Path B values are displayed together because the controller samples
both alternatives. They are not two competing receiver-throughput numbers.
Each path load is its busiest measured directed link, normalized by that link's
configured capacity. The other route can have a nonzero value from background,
control, or transition traffic; the selected route comes from controller flow
state and counter verification.

### Metric formulas

**Directional link rate** (computed between two switch counter samples):

```text
rate_bps = (current_bytes - previous_bytes) * 8 / elapsed_seconds
```

**Link utilisation:**

```text
utilisation_percent = rate_bps / (configured_capacity_mbps * 1,000,000) * 100
```

Utilisation can exceed 100% if the observed counter rate briefly exceeds the
configured emulated capacity, due to sample timing, burstiness, counter
direction, or emulator scheduling. It means the measured rate exceeded the
denominator for that interval; it is not a display cap. Interpret short spikes
with the configured bottleneck and the consecutive-sample threshold.

**Path utilisation:**

```text
path_utilisation = maximum utilisation among the measured forward links on that path
```

Using the maximum identifies the bottleneck link; averaging could hide one
congested link behind less-loaded links.

**Receiver throughput:**

```text
received_bytes * 8 / measured_seconds / 1,000,000 = Mbps
```

The receiver measures packet arrivals at `h2`. This is delivered throughput,
which can be lower than the sender's offered rate because of link limits,
queuing, packet loss, or VM scheduling.

**Packet loss** (final value, after sender completes):

```text
lost_packets = sent_packets - unique_expected_packets_received
loss_percent = lost_packets / sent_packets * 100
```

Temporary sequence gaps are not called losses during the run because later UDP
packets could still arrive. Duplicates and out-of-order arrivals are counted
separately by the receiver.

**Recovery time:** elapsed time from confirmed congestion to verified byte
counter increase on the alternate path. Controller rule-installation duration
is recorded separately; the two numbers describe different parts of recovery.

## 10. Files and saved results

```text
controller.py                 OS-Ken SDN controller
topology.py                   Mininet topology, link rates, port discovery
flow_rules.py                 OpenFlow forwarding rules for Path A and Path B
metrics.py                    Counter rate and utilisation calculations
experiment_manager.py         Mininet/test lifecycle, HTTP API, CSV output
udp_sender.py                 Numbered, rate-limited UDP sender
udp_receiver.py                UDP receiver and packet statistics
raw_demo.py                    Optional terminal interface to manager API
web/index.html                 Dashboard structure
web/app.css                   Dashboard layout and styling
web/app.js                    Controls, polling, status and packet animation
run/port_map.json              Discovered interface and switch port map
run/controller_state.json     Controller heartbeat and measurements
run/receiver_stats.json        Live/final receiver snapshot for current run
results/experiments.csv        Accumulated completed test results
```

The `run/` data is temporary experiment state. The CSV is the reportable
measurement record. Back it up before cleaning or replacing experiment files.

## 11. Wireshark demonstration

Start Mininet first, then open Wireshark inside Kali. Select an interface that
shows Mininet traffic and use the display filter:

```text
udp.port == 5001
```

The sender puts a sequence number and monotonic send timestamp at the start of
each UDP payload. The capture demonstrates packets on the virtual network; the
receiver summary and switch counters are used for the project's final
measurements.

## 12. Troubleshooting

### `Address already in use` on port 8765

An experiment manager already owns the local HTTP port. Inspect and stop that
listener, then start exactly one manager:

```bash
sudo fuser -v 8765/tcp
sudo fuser -k 8765/tcp
sudo python3 experiment_manager.py
```

### `RTNETLINK answers: File exists`

Old Mininet interfaces remain after an interrupted run. Stop the manager and
run:

```bash
sudo mn -c
```

Then restart the controller and manager and click Start network once.

### Controller does not connect

Check Terminal 1 is still running, that it listens on port 6653, and that the
manager started the switches with the expected OpenFlow 1.3 configuration.
Check that all four switch IDs appear as connected before running a test.

### Dashboard shows no measurements

Check the page is `http://127.0.0.1:8765/`, the manager is running, the network
is running, and controller status is live. Hard reload the page after a Git
update with `Ctrl+Shift+R`. A stale measurement should be shown as unavailable,
not treated as a live zero.

### Test did not reroute

Check that the mode is Adaptive, the offered rate is sufficient to exceed the
Path A 2 Mbps bottleneck, the selected threshold is reached for three samples,
and Path B is eligible (below threshold and less loaded). Read the event log for
flow-rule verification and alternate-path counter verification. Do not call a
reroute successful based on animation or a log line alone.

## 13. What the team can claim and what needs VM evidence

Source code and local tests demonstrate that the topology builder, measurement
functions, UDP packet accounting, manager API logic, and dashboard assets are
implemented. They do not prove the full Mininet/OS-Ken experiment worked on a
particular Kali machine.

The assignment is experimentally demonstrated when the team saves evidence
from Kali for all of these:

1. Four OVS switches connect to OS-Ken.
2. Initial Path A rules are installed and verified.
3. Real UDP packets arrive at `h2`.
4. Static mode stays on Path A under the chosen congestion conditions.
5. Adaptive mode installs Path B rules and Path B counters increase.
6. Recovery and rule-installation times are recorded separately.
7. Reset restores Path A and a second run succeeds.
8. Static and adaptive results are saved in `results/experiments.csv`.
9. A Wireshark capture or screenshot shows the UDP packets if packet-level
   evidence is required by the instructor.

Do not present example metrics as fixed expected values. Rates, packet loss,
utilisation, and recovery time vary between VM runs; use the CSV generated by
the actual experiment.
