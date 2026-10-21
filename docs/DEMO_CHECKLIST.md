# Demo checklist

## Before the presentation

- [ ] Linux environment starts and versions are recorded.
- [ ] The two paths and link capacities are printed by the topology.
- [ ] Actual switch interface names and OpenFlow ports are verified.
- [ ] OS-Ken connects to every switch.
- [ ] UDP packets appear at h2 and in the selected Wireshark capture.
- [ ] Static and adaptive runs use the same traffic settings.
- [ ] Adaptive routing is verified using flow entries and Path B counters.
- [ ] Reset restores Path A and clears old measurement baselines.
- [ ] Results and screenshots contain measured values from completed runs.
- [ ] A short recording and saved logs are available as backup.

## Five-minute walkthrough

1. Identify Path A and Path B and show their configured capacities.
2. Start a low-rate UDP test and show receiver counts and Wireshark packets.
3. Run the congested static test and show the measured Path A load.
4. Reset, repeat the same settings in adaptive mode, and show congestion
   confirmation.
5. Show the installed flow rules and increasing Path B counters.
6. Compare receiver throughput, estimated loss, utilisation, and recovery time.
7. Explain that this is a Mininet emulation and point out any limitations seen
   in the measured results.

