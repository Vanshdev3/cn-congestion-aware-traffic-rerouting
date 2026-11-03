# Congestion-Aware Traffic Rerouting

## Complete guide for the project team

This guide explains the project from the networking basics to the Kali demo. It is for teammates who are new to SDN, Mininet, and this codebase.

It covers:

- The network layout and what each software component does
- Static and adaptive routing
- The three-terminal setup and demo sequence
- The measurements, formulas, and CSV results
- What counts as proof that rerouting worked

The project runs inside a Kali Linux virtual machine. Mininet creates a virtual network on that Linux machine. The experiment sends real UDP packets through that virtual network, but it does not control physical routers or switches.

> **How to read this guide:** implementation descriptions are based on the repository. Full end-to-end completion still requires evidence from a run in the team's Kali VM. Example numbers below explain calculations; they are not claimed as measured project results.

---

## 1. Project overview

The project asks a practical networking question:

> If the route carrying traffic becomes congested, can a controller move that traffic to a better route and verify that packets actually use it?

We build two routes between a UDP sender and receiver. An SDN controller reads Open vSwitch port counters. In adaptive mode, when the active route remains above a configured congestion threshold, the controller checks the alternative route, changes the forwarding rules, and verifies counter movement on the new route.

The receiver measures delivered traffic. Each completed experiment is appended to a CSV file so static and adaptive runs can be compared.

### What the project demonstrates

1. Create a two-path network in Mininet.
2. Send numbered UDP packets from `h1` to `h2`.
3. Set different capacities on the two middle paths.
4. Collect directional port statistics from Open vSwitch.
5. Calculate link utilisation and detect sustained congestion.
6. Compare static and adaptive routing.
7. Verify flow rules and traffic movement after rerouting.
8. Measure throughput, packet loss, and recovery time.
9. Reset the experiment and retain completed results in CSV.

---

## 2. The network layout

```text
                            PATH A
                       2 Mbps links
                  +---- s2 ---------+
                  |                 |
h1 (sender) -- s1-+                 +-- s4 -- h2 (receiver)
                  |                 |
                  +---- s3 ---------+
                            PATH B
                       5 Mbps links

Path A: h1 -> s1 -> s2 -> s4 -> h2
Path B: h1 -> s1 -> s3 -> s4 -> h2
```

There are **two hosts** and **four switches**. The hosts and switches are virtual Mininet nodes.

| Link group | Configured capacity | Purpose |
|---|---:|---|
| `h1-s1` and `s4-h2` | 10 Mbps each | Host-facing links shared by both routes |
| `s1-s2` and `s2-s4` | 2 Mbps each | Path A's middle bottleneck |
| `s1-s3` and `s3-s4` | 5 Mbps each | Path B's middle bottleneck |

The bottleneck is the link that limits the route's end-to-end traffic. Path A is intentionally narrower in the middle than Path B. At an offered rate of 3 Mbps, Path A may become congested while Path B may have enough capacity to carry the flow.

`topology.py` defines the links and expected ports. When the network starts, the manager discovers the actual Mininet interface and switch-port numbers and saves them in `run/port_map.json`. The controller uses that discovered map for its counter requests and forwarding rules.

---

## 3. Software: what each part does

| Component | Job |
|---|---|
| Kali Linux VM | Runs the Linux networking tools and gives Mininet the required system access. |
| Mininet | Creates the virtual hosts, links, interfaces, and network topology. |
| Open vSwitch (OVS) | Provides the four software switches and forwards packets using flow rules. |
| OpenFlow 1.3 | Carries statistics requests and rule updates between OVS and the controller. |
| OS-Ken | Runs `controller.py`; reads switch statistics and decides whether to change the route. |
| Experiment manager | Runs `experiment_manager.py`; starts Mininet and traffic, serves the dashboard/API, and saves results. |
| UDP sender | Runs inside `h1`; sends numbered packets at a configured rate. |
| UDP receiver | Runs inside `h2`; counts arrivals and calculates receiver statistics. |
| Browser dashboard | Provides real controls and displays manager/controller measurements at `127.0.0.1:8765`. |
| `raw_demo.py` | Optional terminal client for sending the same commands and reading manager state. |
| Wireshark | Captures and inspects packets on a Mininet interface. |

The dashboard uses Python's built-in HTTP server. It does not need Node.js, React, Flask, or an internet connection.

### SDN in plain language

In Software Defined Networking (SDN), a controller makes forwarding decisions and programmable switches carry them out.

- **Control plane:** OS-Ken decides which route should carry the selected flow.
- **Data plane:** OVS forwards packets using flow entries installed by OS-Ken.
- **Control protocol:** OpenFlow 1.3 carries statistics and rule changes between them.
- **Experiment manager:** starts and coordinates the network and traffic programs.

A flow entry matches packet fields and specifies an action, such as sending a packet out a particular switch port. During a route change, the controller installs the required rules, waits for switch barriers, checks the flow entries, and then checks counters on the new route.

---

## 4. Static mode and adaptive mode

Both modes begin from a known route, Path A, and both continue monitoring the paths.

### Static mode

1. The manager resets the experiment and prepares Path A.
2. The sender sends UDP packets at the chosen offered rate.
3. The controller measures path utilisation.
4. If the threshold is met for three consecutive samples, it reports congestion.
5. Static mode keeps the traffic on Path A; it does not reroute because of congestion.

Static mode is the comparison run. It shows what happens when the route remains fixed.

### Adaptive mode

1. The manager resets the experiment and prepares Path A.
2. The sender sends at the chosen offered rate while the controller samples both paths.
3. If Path A meets or exceeds the threshold for three consecutive samples, congestion is confirmed.
4. The controller checks whether Path B has a fresh, lower, eligible measured load.
5. If Path B is eligible, the controller installs its forwarding rules.
6. The controller checks the flow entries and waits for counters on Path B's unique links to increase.
7. After counter movement is verified, the controller records the route change and recovery time.

The intended experiment is to keep the verified alternate route for the remainder of the run, then use **Reset to Path A** before another experiment. A route change at a low offered rate such as 1 Mbps should not be assumed correct: check the mode, threshold, counter samples, and controller events to find the cause.

### Why use both modes?

Static mode is the baseline. Adaptive mode is the response being evaluated. Use the same offered rate, duration, threshold, and initial route for both runs so the comparison is meaningful.

---

## 5. Three-terminal setup in Kali

Open three terminal windows in the VM. Run commands from the project folder. Keep Terminals 1 and 2 running while you use the dashboard.

Do not also start a separate `sudo mn` network or `start_network.py` while the experiment manager is controlling Mininet.

### Terminal 1: OS-Ken controller

```bash
cd ~/cn-congestion-aware-traffic-rerouting
source .venv/bin/activate
sudo .venv/bin/osken-manager --ofp-tcp-listen-port 6653 controller.py
```

Leave it open. The controller should stay running and later log that the OpenFlow switches connected. The Eventlet deprecation notice is a dependency warning; it does not by itself mean the controller failed.

### Terminal 2: experiment manager

```bash
cd ~/cn-congestion-aware-traffic-rerouting
sudo python3 experiment_manager.py
```

Wait for:

```text
Experiment manager listening at http://127.0.0.1:8765
```

The manager needs root privileges to create Mininet and OVS interfaces. On network start, it prints the discovered interface and switch-port map.

### Terminal 3: dashboard

```bash
firefox http://127.0.0.1:8765/
```

The dashboard can open before the network starts. After pulling updated files from GitHub, press `Ctrl+Shift+R` in Firefox to reload them.

### Optional terminal controls

Instead of using the dashboard controls, Terminal 3 can call the same experiment manager:

```bash
python3 raw_demo.py status
python3 raw_demo.py start-network
python3 raw_demo.py events
```

The dashboard and `raw_demo.py` are two ways to control the same running experiment.

---

## 6. Clean start and common recovery commands

Stop foreground services with `Ctrl+C` in their own terminal windows.

If port 8765 is already in use, inspect and stop the old manager listener:

```bash
sudo fuser -v 8765/tcp
sudo fuser -k 8765/tcp
```

If Mininet reports `RTNETLINK answers: File exists`, stop the manager and clear stale Mininet state:

```bash
sudo mn -c
```

Then start the controller, manager, and dashboard again in that order. Do not run `sudo mn -c` while an experiment is active.

To update the Kali checkout:

```bash
cd ~/cn-congestion-aware-traffic-rerouting
git pull
```

Restart the manager after pulling because it serves the dashboard files from disk. Restart the controller as well if `controller.py` changed.

---

## 7. Recommended demonstration

Use the same settings for the static and adaptive comparison:

| Setting | Example value |
|---|---:|
| Offered rate | 3 Mbps |
| Duration | 15 seconds |
| Congestion threshold | 75% |
| Starting route | Path A |

These are demonstration settings, not guaranteed results. Three Mbps is above Path A's configured 2 Mbps middle-link capacity and below Path B's 5 Mbps middle-link capacity.

### Adaptive demo steps

1. Start the network and wait until the controller is live.
2. Select **Adaptive** and set the offered rate, duration, and threshold.
3. Click **Reset to Path A**. Check that Path A rules were installed and verified.
4. Click **Start test**.
5. Watch the Path A load measurements and the event log.
6. If congestion is confirmed, watch for Path B rule verification and Path B counter movement.
7. Wait for the test to finish. The final selected route may remain Path B even though the sender has stopped.
8. Export or inspect `results/experiments.csv`.

### Static comparison

Reset to Path A, keep all test settings the same, select **Static**, and run the test. The controller can report congestion, but the flow should remain on Path A. Compare the saved results only after confirming each run actually completed.

---

## 8. Dashboard controls and what they affect

| Control | Effect |
|---|---|
| **Start network** | Creates Mininet, discovers ports, waits for switches, and verifies initial Path A rules. |
| **Start test** | Resets to Path A, starts the receiver on `h2`, then the sender on `h1`. |
| **Traffic offered** slider and number | Selects the sender's target rate in Mbps. The number field allows precise entry. |
| **Apply live rate** | Writes a new sender rate while a test is running. The sender checks for changes about every 0.25 seconds. |
| **Run length** | Sets how long the sender transmits. |
| **Congestion threshold** | Sets the utilisation level used by the congestion check. |
| **Routing mode** | Chooses Static or Adaptive controller behavior. |
| **Apply settings** | Sends the selected mode and threshold to the controller. |
| **Reset to Path A** | Stops/finalizes a test as needed, clears measurement baselines, and verifies the initial route. |
| **Stop test** | Stops sender and receiver and finalizes the packet statistics. |
| **Stop network** | Stops the test if needed and tears down Mininet. |
| **Export CSV** | Reports the accumulated experiment-results file location. |

The offered rate is not the utilisation percentage. Offered rate is what the sender tries to inject. Utilisation comes from measured switch counters and the configured capacity of a link.

---

## 9. Understanding the topology animation and live measurements

The diagram shows `h1` as sender, `h2` as receiver, and switches `s1` through `s4`. Path A passes through `s2`; Path B passes through `s3`.

Both path-load values can be shown at once because the controller monitors both alternatives. They are not two receiver-throughput values. The selected route is identified separately by the controller's active flow state.

The dashboard's moving packet markers are an illustration. They do not prove packets took a route. Proof comes from the real UDP sender/receiver, installed OpenFlow rules, and increasing counters on the route's unique links.

After a test ends, live traffic stops. The controller may retain the last selected route until reset. A highlighted route after completion does not mean packets are still moving.

---

## 10. Measurements and formulas

### 10.1 Offered rate

The offered rate is the sender's target transmission rate.

For example, selecting 3 Mbps asks the sender to offer approximately 3 million bits per second. It does not promise that the receiver will get 3 Mbps.

### 10.2 Link rate from byte counters

The controller samples a switch-port byte counter twice. The difference is how many bytes passed during the time between samples.

```text
byte_delta = current_bytes - previous_bytes

rate_bps = (byte_delta * 8) / elapsed_seconds
```

The factor 8 converts bytes to bits.

### 10.3 Link utilisation

```text
capacity_bps = capacity_mbps * 1,000,000

utilisation_percent = (rate_bps / capacity_bps) * 100
```

**Worked example:** a measured 1.5 Mbps on a 2 Mbps link is:

```text
1.5 / 2 * 100 = 75% utilisation
```

That 75% is a comparison between measured bit rate and configured link capacity. It is not packet loss, and it is not the slider's Mbps value expressed as a percent.

### 10.4 Why a path load uses the maximum link value

```text
path_utilisation = maximum utilisation among the measured forward links on that path
```

The maximum represents the busiest link. An average could hide one bottleneck behind several quieter links.

The underlying measured percentage should not be silently capped: a brief reading above 100% means the measured rate exceeded the configured denominator for that sample interval. A display bar may stop at 100%, but the numeric measurement and formula should remain honest.

### 10.5 Congestion threshold and three samples

The threshold is the configured utilisation level that counts as high. The controller requires **three consecutive port-stat samples** at or above that threshold before confirming congestion.

Those three values are three time-based counter measurements. They are not three packets.

Example with a 75% threshold:

| Sample | Measured active-path load | Consecutive high samples |
|---:|---:|---:|
| 1 | 78% | 1 |
| 2 | 81% | 2 |
| 3 | 79% | 3: congestion confirmed |

If a sample falls below the threshold before confirmation, the consecutive count is reset. Requiring consecutive samples helps prevent a single short spike from causing a route change.

### 10.6 Receiver throughput

```text
receiver_mbps = (received_bytes * 8) / measured_seconds / 1,000,000
```

This measures data that arrived at `h2`. It may be lower than the offered rate because of the path bottleneck, packet loss, queuing, or VM scheduling.

### 10.7 Packet counts and loss

Each UDP packet carries a sequence number. The receiver records unique arrivals, duplicates, and out-of-order arrivals separately.

Final loss is calculated after the sender finishes, so a temporary sequence gap is not mistaken for a lost packet while a delayed packet might still arrive.

```text
lost_packets = sent_packets - unique_expected_packets_received

loss_percent = (lost_packets / sent_packets) * 100
```

### 10.8 Recovery time and rule time

Recovery time measures from confirmed congestion until counters verify traffic on the alternate path.

Rule-installation time measures the forwarding-rule installation and verification stage. The project records them separately because they describe different parts of a reroute.

---

## 11. Ports and files to know

Three port numbers serve different purposes:

| Port | Protocol | Purpose |
|---:|---|---|
| 5001 | UDP | Application packets from sender `h1` to receiver `h2` |
| 6653 | OpenFlow over TCP | OVS switch connections to OS-Ken |
| 8765 | HTTP | Browser dashboard and experiment-manager API |

Important files:

```text
controller.py                 OS-Ken controller
topology.py                   Mininet topology, link capacities, port discovery
flow_rules.py                 OpenFlow rules for both routes
metrics.py                    Counter-rate and utilisation calculations
experiment_manager.py         Network lifecycle, HTTP API, tests, CSV results
udp_sender.py                 Numbered and rate-limited UDP sender
udp_receiver.py               UDP receiver and packet statistics
raw_demo.py                   Optional terminal control client
web/index.html                 Dashboard structure
web/app.css                    Dashboard presentation
web/app.js                     Dashboard polling, controls, and animation
run/port_map.json              Interfaces and switch ports discovered at runtime
run/controller_state.json     Controller measurements and route status
run/receiver_stats.json        Current receiver snapshot
results/experiments.csv        Accumulated completed experiment results
```

The `run/` files are temporary experiment state. The CSV is the accumulated experiment record. Back up results before replacing or cleaning experiment files.

---

## 12. CSV results

The manager appends one row for each completed experiment to:

```text
results/experiments.csv
```

The dashboard's **Export CSV** button does not create fake data or download a different copy. It confirms the location of this one accumulated file. After a completed run, inspect it from a normal Kali terminal with:

```bash
cd ~/cn-congestion-aware-traffic-rerouting
python3 raw_demo.py export
column -s, -t < results/experiments.csv | less -S
```

Press `q` to leave the table. To show only the header and the latest two completed runs, use:

```bash
head -n 1 results/experiments.csv
tail -n 2 results/experiments.csv
```

To copy the evidence file to the Kali desktop after the demo:

```bash
cp results/experiments.csv ~/Desktop/
```

The actual columns are created in `experiment_manager.py`. They include experiment identity, routing mode, offered and final rates, rate changes, duration, final path, sent/received/lost packets, loss percentage, receiver throughput, both path utilisations, recovery time, rule-installation time, and route-verification timestamps.

### Why a raw utilisation calculation can be above 100%

The configured capacity is the intended bottleneck rate. The controller calculates a rate from byte-counter differences over a short time interval. Linux scheduling, packet bursts already queued before traffic control applies, and the exact start/end of a one-second sample can briefly produce a calculated rate slightly above that configured capacity. This does **not** mean the physical link became faster. It means the short counter window included a burst. The dashboard therefore shows `100%+` as the saturated state in its main view, while the expandable formula card preserves the raw calculated value for technical evidence.

Resetting an experiment clears current controller measurements and restores Path A; it is not intended to erase previously completed CSV rows. Use the actual generated CSV as the source for report tables. Do not present illustrative values as measured results.

The CSV is useful for:

- Comparing Static and Adaptive runs with the same settings
- Comparing delivered throughput and packet loss
- Recording the final selected route
- Reporting recovery and rule-installation times
- Making result tables and charts for the presentation

---

## 13. Wireshark packet evidence

Start Mininet before capturing. In Kali, select a capture interface that sees Mininet traffic and use this display filter:

```text
udp.port == 5001
```

You can inspect source/destination addresses, UDP port, packet length, arrival time, and the sequence information in the payload.

A filter only selects packets after capture begins; it does not start a capture by itself.

### Three types of evidence

| Evidence | What it supports |
|---|---|
| Dashboard | Current experiment state and reported measurements |
| OpenFlow flow entries and switch counters | Controller rule installation and traffic movement between paths |
| Wireshark | Actual UDP packets on the virtual network |

Use the switch rules and counters to prove rerouting. The dashboard animation alone is not proof.

---

## 14. Troubleshooting

### Port 8765 is already in use

An experiment manager may already be running:

```bash
sudo fuser -v 8765/tcp
sudo fuser -k 8765/tcp
```

Then start one manager from the project directory.

### `RTNETLINK answers: File exists`

Old Mininet interfaces may remain after an interrupted run. Stop the manager, then run:

```bash
sudo mn -c
```

Start the controller and manager again, then start the network once from the dashboard.

### Controller does not connect

Check that Terminal 1 is still running and listening on port 6653. Wait for all four expected switch IDs to appear before testing.

### Dashboard has no live measurements

Check that:

1. Firefox is open at `http://127.0.0.1:8765/`.
2. The experiment manager is running.
3. The Mininet network is running.
4. The controller is live and all switches are connected.

After a Git update, hard-refresh Firefox with `Ctrl+Shift+R`.

### Adaptive run does not reroute

Check that Adaptive mode is selected, the active path really reaches the threshold for three consecutive samples, and the alternate path has eligible measurements. Read the event log and controller output for rule verification and counter movement. Do not treat a moving animation or a route-colour change as proof.

---

## 15. What to verify before claiming completion

Code and local tests can show that components are implemented. They cannot prove that the full Mininet and OS-Ken experiment worked on a particular Kali VM. Save VM evidence for each acceptance point:

- [ ] Four OVS switches connect to OS-Ken.
- [ ] Initial Path A forwarding rules are installed and verified.
- [ ] Real UDP packets arrive at `h2`.
- [ ] Static mode stays on Path A during a run that confirms congestion.
- [ ] Adaptive mode installs Path B rules after congestion is confirmed.
- [ ] Path B's unique-link counters increase after the route change.
- [ ] Recovery time and rule-installation time are recorded separately.
- [ ] Reset restores Path A and a later run also succeeds.
- [ ] Static and Adaptive results are both saved in the CSV.
- [ ] A Wireshark capture is saved if packet-level evidence is required.

Do not claim a specific throughput, loss percentage, utilisation, or recovery time until it appears in the team's own completed experiment data.

---

## 16. Short presentation script

> Our project demonstrates congestion-aware traffic rerouting using Software Defined Networking. We built a two-path Mininet network with two hosts and four Open vSwitch switches. A custom Python program sends numbered UDP packets from `h1` to `h2`. The two middle routes have different configured capacities: Path A uses 2 Mbps links and Path B uses 5 Mbps links. OS-Ken reads directional switch-port counters and calculates utilisation from counter changes over time. It requires three consecutive measurements at or above the configured threshold before confirming congestion. In Static mode, congestion is reported while the flow remains on Path A. In Adaptive mode, the controller checks Path B, installs and verifies the forwarding rules, then checks that Path B counters increase. The receiver records throughput and packet delivery, and completed tests are stored in CSV for comparison.

---

## 17. Key points for the viva

### What is SDN?

SDN separates the network's decision-making control plane from the packet-forwarding data plane. In this project, OS-Ken is the controller and Open vSwitch forwards packets.

### What is a bottleneck?

A bottleneck is the lowest-capacity link that limits the route. Path A's 2 Mbps middle links are narrower than its 10 Mbps host links.

### What is a switch counter?

A counter is a running byte or packet total maintained by a switch port. Subtracting two byte-counter readings shows how much traffic passed during the sample interval.

### Why measure direction?

The experiment measures the forward `h1` to `h2` flow. Mixing reverse-direction traffic into the calculation would describe a different traffic direction.

### What is route flapping?

Route flapping is repeated switching between paths. The intended demo should show one verified move from Path A to Path B, then hold that route until reset. If it switches back, inspect the current controller logic and event/counter evidence rather than describing that as desired behavior.

### What does Mininet mean here?

Mininet creates virtual hosts, switches, links, and interfaces on Linux. The UDP application sends real packets through that emulated topology. It is a network emulation, not a test on physical routers.

### Which ports matter?

- UDP `5001`: sender to receiver application traffic
- TCP `6653`: OpenFlow connection between OVS and OS-Ken
- HTTP `8765`: browser dashboard and experiment-manager API

---

## Final reminders

1. **OS-Ken decides; OVS forwards.**
2. **Congestion is calculated from switch-counter changes and link capacity.**
3. **Three samples means three time-based measurements, not three packets.**
4. **A reroute is successful only after rules and alternate-path counter movement are verified.**
5. **Use the team's own CSV and Kali evidence when presenting results.**
