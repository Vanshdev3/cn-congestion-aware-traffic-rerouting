# Local dashboard API

The Tkinter window talks to `experiment_manager.py` over HTTP on
`127.0.0.1:8765`. The server uses Python's standard library and listens only
on the local machine.

| Request | Purpose |
|---|---|
| `GET /health` | Check the manager process and whether the network/controller are ready |
| `GET /state` | Read current network, controller, traffic, and last-run state |
| `GET /events` | Read recent manager and controller events |
| `POST /command/start-network` | Create the Mininet network and verify Path A rules |
| `POST /command/stop-network` | Stop traffic and remove the Mininet network |
| `POST /command/start-test` | Reset to Path A, then start the receiver and sender |
| `POST /command/stop-test` | Stop traffic and finalize packet counts and loss |
| `POST /command/set-rate` | Change the running sender's rate; the sender reads the new setting within about a quarter second |
| `POST /command/configure` | Apply static/adaptive mode and the congestion threshold |
| `POST /command/reset` | Reset counters/baselines and restore Path A |
| `POST /export` | Return the path to the accumulated experiment CSV |

Command requests and results use JSON. The dashboard shows a connection error
when the manager is unreachable. The manager hides controller measurements
when the controller heartbeat is old or the switches are not connected. It
also marks individual link measurements unavailable when their sample is old.
Completed test results remain labeled as a past run, separate from live values.

