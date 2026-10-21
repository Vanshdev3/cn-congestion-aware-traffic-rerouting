# Team guide

Everyone should understand the end-to-end path, even if work is split:

```text
UDP sender on h1 -> Open vSwitch path -> UDP receiver on h2
                             ^
                     OS-Ken reads counters
                     and changes flow rules
                             ^
               Tkinter controls the experiment
```

Suggested responsibilities for four people:

| Area | Main tasks | Evidence to hand off |
|---|---|---|
| Linux environment | VM, Mininet, OVS, package/version notes | Successful smoke-test output |
| Topology | Two paths, link rates, automatic port map | Topology printout and connectivity result |
| Traffic and measurements | UDP sender/receiver, sequence accounting, capture | Receiver summary and packet capture |
| Controller and demo | OS-Ken, congestion response, dashboard, run sheet | Flow tables, logs, CSV, demo screenshots |

For a smaller team, combine areas. Pair on the controller and topology because
their port mapping and flow rules must agree.

## Experiment terms

- **Offered rate:** the rate configured at the sender.
- **Link utilisation:** rate derived from a switch egress-byte-counter delta
  divided by that link's configured capacity.
- **Receiver throughput:** bytes received by h2 divided by the measurement time.
- **Packet loss estimate:** expected sequence numbers minus unique sequence
  numbers received, finalized after the sender stops.
- **Recovery time:** congestion-confirmed timestamp to verified traffic on Path
  B. Rule-installation time is reported separately.

The UDP programs count application datagram bytes. Those throughput numbers do
not include Ethernet, IP, or UDP headers. The sender increments its sequence
only after `sendto` succeeds. The receiver separates duplicates from
out-of-order packets and finalizes loss using the sender's first/last sequence
and successful packet count.

