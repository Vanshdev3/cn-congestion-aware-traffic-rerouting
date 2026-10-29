# Requirements checklist

## Sources used

This checklist separates external assignment requirements from repository
implementation instructions. It is based on:

- `CN_Congestion_Rerouting_Project_Plan.md`, the team's detailed project plan.
- `SDN_Socket_Programming_30_Projects.xlsx`, row 27, Project 27: Congestion
  Detection and Traffic Rerouting.

The source workbook also lists Project 30, Adaptive Communication Network with
Failure Recovery. That is a different project and is not treated as a required
feature here. This repository implements Project 27, not full link-failure
recovery.

## Requirement-by-requirement review

| Requirement | Where it is implemented | Status |
|---|---|---|
| UDP traffic across multiple network paths | `topology.py`, `udp_sender.py`, `udp_receiver.py` | Implemented |
| Two hosts and four switches | `ReroutingTopo` in `topology.py` | Implemented |
| Path A: `h1-s1-s2-s4-h2` | `PATHS["A"]` and the discovered port map | Implemented |
| Path B: `h1-s1-s3-s4-h2` | `PATHS["B"]` and the discovered port map | Implemented |
| Controlled congestion | `TCLink` capacities and sender rate controls | Implemented; VM evidence pending |
| OpenFlow switch statistics | `controller.py` port-stat and flow-stat handlers | Implemented; VM evidence pending |
| Link utilisation from counter deltas | `metrics.py` and `finish_port_sample()` | Implemented; VM evidence pending |
| Congestion threshold | `threshold_percent`, default 75% | Implemented |
| Consecutive confirmation samples | `required_high_samples = 3` | Implemented |
| Static routing | `mode == "static"` leaves the route unchanged | Implemented; VM evidence pending |
| Adaptive routing | `try_adaptive_reroute()` and `start_route_change()` | Implemented; VM evidence pending |
| Valid forwarding rules | UDP-specific rules plus lower-priority IPv4 forwarding rules | Implemented; VM evidence pending |
| Flow-entry verification | Barrier requests and flow-stat matching | Implemented; VM evidence pending |
| Alternate-path traffic verification | Unique Path B counter movement is required | Implemented; VM evidence pending |
| Recovery time | Congestion confirmation to verified alternate-path counters | Implemented; VM evidence pending |
| Receiver throughput | Received bytes divided by measured elapsed time | Implemented |
| Packet loss | Sender sequence range compared with unique receiver sequences | Implemented |
| Duplicate/out-of-order tracking | `SequenceTracker` in `udp_receiver.py` | Implemented |
| Repeatable reset | Manager reset command and controller baseline reset | Implemented; VM evidence pending |
| CSV export | `results/experiments.csv` from `experiment_manager.py` | Implemented |
| Wireshark evidence | Linux capture instructions in the runbook | Documented; capture pending |
| Dashboard controls | Optional Tkinter client uses the real manager API | Implemented; not required for raw demo |

## What is not claimed

The repository does not claim that a particular throughput, loss percentage,
utilisation, or recovery time has already been observed. Those values depend on
the Linux VM and must come from completed runs. The repository also does not
claim Project 30's failure-detection and link-failure recovery features.

## Acceptance decision

The implementation satisfies the code-level requirements and the local
traffic/measurement tests. The project becomes experimentally complete after a
Linux VM run proves the following with saved output:

1. All four switches connect to OS-Ken.
2. Path A rules are installed and verified.
3. Real UDP packets reach `h2`.
4. Static mode remains on Path A during congestion.
5. Adaptive mode installs Path B rules and Path B counters increase.
6. Reset restores Path A before the next comparison.

